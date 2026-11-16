"""CONTRACT-004: label-driven parsing of Raptor Crystal Reports PDF exports.

Words carry page coordinates (points). Values are matched to labels and
column headers by position relative to those labels, never by fixed
coordinates. Label and value baselines jitter by up to about 2 points.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
import re

from icontract import ensure

from . import DAY_COLUMNS, DURATION, SECTIONS, TITLES, drop_placeholders, layout, validate
from .models import Breakdown, Day, Header, KPIs, ParsedReport

SUPPORTED = ('production_summary', 'production_todate')
SAME_LINE = 3     # max top difference between words of one printed line
PHRASE_GAP = 12   # max horizontal gap between words of one phrase
NEAR = 5          # max mid difference between a metric label and its value
LANE_SLACK = 6    # max right-edge difference between a value and its column
NUMBER = re.compile(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|\d+(?:\.\d+)?%?')
DATE = re.compile(r'\d{1,2}-[A-Z][a-z]{2}-\d{4}')
PAGE = re.compile(r'Page (\d+) of (\d+)')
METRICS = ('Pieces', 'Volume', '% vol')
KPI_LABELS = ('Average BF Per Piece:', 'Lug Fill', 'Trimloss', 'Slow', 'Medium', 'Fast')


@dataclass(frozen=True)
class Word:
    """A word or a phrase (adjacent words of one line) on one page."""
    page: int
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def mid(self):
        return (self.top + self.bottom) / 2


def read_pages(path, file):
    import pdfplumber  # Imported here so run/schedule/check never load it (ADR-002).

    try:
        with pdfplumber.open(path) as pdf:
            return [[Word(index, w['text'], w['x0'], w['x1'], w['top'], w['bottom'])
                     for w in page.extract_words()]
                    for index, page in enumerate(pdf.pages)]
    except Exception as error:
        layout(file, f'cannot read PDF ({type(error).__name__})')


def lines(words):
    """Group words into printed lines, each sorted left to right."""
    result = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if result and word.top - result[-1][0].top <= SAME_LINE:
            result[-1].append(word)
        else:
            result.append([word])
    return [sorted(line, key=lambda w: w.x0) for line in result]


def phrases(line):
    result = []
    for word in line:
        last = result[-1] if result else None
        if last and word.x0 - last.x1 <= PHRASE_GAP:
            result[-1] = Word(last.page, f'{last.text} {word.text}', last.x0, word.x1,
                              min(last.top, word.top), max(last.bottom, word.bottom))
        else:
            result.append(word)
    return result


def page_phrases(words):
    return [phrase for line in lines(words) for phrase in phrases(line)]


def text_of(line):
    return ' '.join(word.text for word in line)


def is_furniture(line):
    text = text_of(line)
    return (text in TITLES.values() or text.startswith('Printed:')
            or PAGE.fullmatch(text) is not None)


def number(text, file, integer=False):
    if text is None:
        return None
    if not NUMBER.fullmatch(text):
        layout(file, f'expected number, got {text!r}')
    value = float(text.replace(',', '').rstrip('%'))
    if integer:
        if value != int(value):
            layout(file, f'expected integer count, got {text!r}')
        return int(value)
    return value


def timestamp(text, file):
    if text is None:
        return None
    text = ' '.join(text.split())
    for fmt in ('%b %d, %Y %I:%M %p', '%B %d, %Y %I:%M:%S%p'):
        try:
            return datetime.strptime(text, fmt).strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
    layout(file, f'invalid timestamp {text!r}')


def header(pages, kind, file):
    first = lines(pages[0]) if pages else []
    titles = [text_of(line) for line in first if text_of(line).endswith(' Report')]
    if not titles or titles[0] != TITLES[kind]:
        layout(file, f'page 1 title must equal {TITLES[kind]!r}')
    required = ['Printed:']
    if kind != 'production_todate':
        required += ['Report Start:', 'Report End:', 'Recipe:']
    values = {}
    for label in required:
        found = None
        for line in first:
            for index, phrase in enumerate(line_phrases := phrases(line)):
                if phrase.text == label or phrase.text.startswith(label + ' '):
                    found = (phrase, line_phrases[index+1:])
                    break
            if found:
                break
        if not found:
            layout(file, f'missing header label {label}')
        phrase, rest = found
        value = phrase.text[len(label):].strip() or (rest[0].text if rest else None)
        # Do not mistake another header label for an empty value.
        if value is not None and any(value == other or value.startswith(other + ' ')
                                     for other in required):
            value = None
        values[label] = value if label == 'Recipe:' else timestamp(value, file)
    markers = [PAGE.fullmatch(text_of(line)) for page in pages for line in lines(page)]
    markers = [match for match in markers if match]
    if not markers or int(markers[-1][2]) < 1:
        layout(file, 'missing Page N of N marker')
    return Header(values['Printed:'], values.get('Report Start:'),
                  values.get('Report End:'), values.get('Recipe:')), int(markers[-1][2])


def section_titles(page_words):
    found = []
    for phrase in page_phrases(page_words):
        for section in SECTIONS:
            if phrase.text == section.title() + ' Summary':
                found.append((phrase, section))
    return found


def kpis(page_words, first_section_top, file):
    found = {}
    candidates = [p for p in page_phrases(page_words) if p.top < first_section_top]
    for label in (*KPI_LABELS, 'Trimmer Speed'):
        matches = [p for p in candidates if p.text == label]
        if not matches:
            layout(file, f'missing KPI label {label}')
        found[label] = matches[0]
    if any(found[label].top < found['Trimmer Speed'].top for label in ('Slow', 'Medium', 'Fast')):
        layout(file, 'Trimmer Speed label must precede speed KPI values')
    numeric = [p for p in candidates if NUMBER.fullmatch(p.text)]
    values = []
    for label in KPI_LABELS:
        anchor = found[label]
        below = [p for p in numeric if p.top > anchor.top
                 and p.x1 >= anchor.x0 - 4 and p.x0 <= anchor.x1 + 4]
        above = [p for p in numeric if p.top < anchor.top - SAME_LINE
                 and p.x1 >= anchor.x0 - 4 and p.x0 <= anchor.x1 + 4]
        if above:
            layout(file, f'KPI label {label} must precede KPI value')
        if not below:
            values.append(None)
            continue
        nearest = min(p.top for p in below)
        closest = [p for p in below if p.top - nearest <= SAME_LINE]
        if len(closest) != 1:
            layout(file, f'ambiguous KPI value for {label}')
        values.append(number(closest[0].text, file))
    return KPIs(*values)


def is_item_total(phrase, page_phrase_list):
    """An item label 'Total' has its own Pieces label to its right on the line."""
    return any(p.text == 'Pieces' and abs(p.mid - phrase.mid) <= NEAR
               and 0 <= p.x0 - phrase.x1 <= 120 for p in page_phrase_list)


def production(pages, file):
    titles = [(phrase, section) for page in pages for phrase, section in section_titles(page)]
    if not titles or titles[0][0].page != 0:
        layout(file, 'section titles must start on page 1')
    first_top = min(phrase.top for phrase, _ in titles if phrase.page == 0)
    kpi_values = kpis(pages[0], first_top, file)
    records = []   # (sort key, Breakdown)
    current = {}
    seen, completed, pending = set(), set(), []
    for page_index, page_words in enumerate(pages):
        all_lines = lines(page_words)
        body = [word for line in all_lines if not is_furniture(line) for word in line
                if page_index > 0 or word.top >= first_top - SAME_LINE]
        page_list = page_phrases(body)
        title_section = {id(p): s for p in page_list for s in SECTIONS
                         if p.text == s.title() + ' Summary'}
        events = sorted(page_list, key=lambda p: (p.mid, p.x0))
        pieces_rows = []
        for mid in sorted(p.mid for p in page_list if p.text == 'Pieces'):
            if pieces_rows and mid - pieces_rows[-1][-1] <= NEAR:
                pieces_rows[-1].append(mid)
            else:
                pieces_rows.append([mid])
        lanes = []   # (x1 of column header, section); furniture resets lanes per page
        handled = set()
        for phrase in events:
            if id(phrase) in title_section:
                section = title_section[id(phrase)]
                seen.add(section)
                pending.append((phrase.x0, section))
                continue
            if phrase.text == 'Total' and not is_item_total(phrase, page_list):
                if id(phrase) in handled:
                    continue
                group = sorted((p for p in page_list if p.text == 'Total'
                                and abs(p.mid - phrase.mid) <= SAME_LINE
                                and not is_item_total(p, page_list)), key=lambda p: p.x0)
                handled.update(id(p) for p in group)
                if pending:
                    sections = [section for _, section in sorted(pending)]
                else:
                    sections = [s for s in SECTIONS if s in seen and s not in completed]
                if len(group) != len(sections):
                    layout(file, 'section titles/continuation must label each Total column')
                for column, section in zip(group, sections):
                    lanes = [(x1, s) for x1, s in lanes if abs(x1 - column.x1) > 10]
                    lanes.append((column.x1, section))
                pending = []
                continue
            if phrase.text not in METRICS:
                continue
            if not lanes:
                layout(file, 'section title and Total column must precede section records')
            right_lanes = [(x1, s) for x1, s in lanes if x1 > phrase.x1]
            if not right_lanes:
                layout(file, 'metric has no labeled value column to its right')
            lane, section = min(right_lanes)
            values = [w for w in body if abs(w.x1 - lane) <= LANE_SLACK
                      and abs(w.mid - phrase.mid) <= NEAR and w.x0 > phrase.x1]
            if len(values) > 1:
                layout(file, f'ambiguous {phrase.text} value for {section}')
            value = values[0].text if values else None
            if phrase.text == 'Pieces':
                bound = max((x1 for x1, _ in lanes if x1 < phrase.x0), default=-1)
                # A long label wraps onto the item's Volume and % vol lines.
                pct = [p.mid for p in page_list if p.text == '% vol' and p.mid > phrase.mid
                       and abs(p.x0 - phrase.x0) <= LANE_SLACK]
                limit = min(pct, default=phrase.mid) + NEAR
                labels = [p for p in page_list if phrase.mid - NEAR <= p.mid <= limit
                          and p.x1 < phrase.x0 and p.x0 > bound
                          and id(p) not in title_section and p.text not in METRICS]
                if not labels:
                    layout(file, f'{section} record has no label')
                label = ' '.join(p.text for p in sorted(labels, key=lambda p: (p.top, p.x0)))
                row = next(i for i, mids in enumerate(pieces_rows) if phrase.mid in mids)
                record = Breakdown(0, section, label, label == 'Total',
                                   number(value, file, True), None, None)
                records.append(((page_index, row, phrase.x0), record))
                current[section] = len(records) - 1
                if label == 'Total':
                    completed.add(section)
            else:
                if section not in current:
                    layout(file, f'{section} metric before first Pieces record')
                key, record = records[current[section]]
                field = 'volume' if phrase.text == 'Volume' else 'pct_volume'
                records[current[section]] = (key, replace(record, **{field: number(value, file)}))
    if seen != set(SECTIONS):
        layout(file, f'missing section titles: {set(SECTIONS)-seen}')
    ordered = sorted(records, key=lambda item: item[0])
    return kpi_values, drop_placeholders(tuple(replace(record, row_order=index)
                                               for index, (_, record) in enumerate(ordered, 1)))


def todate(pages, file):
    anchors = {}
    days = []
    repeats = {}
    for page_words in pages:
        for line in lines(page_words):
            if is_furniture(line):
                continue
            texts = {phrase.text: phrase for phrase in phrases(line)}
            if any(label in texts for label in DAY_COLUMNS):
                if not all(label in texts for label in DAY_COLUMNS):
                    layout(file, 'all 10 ToDate column labels required at each header')
                anchors = {label: texts[label].x1 for label in DAY_COLUMNS}
                continue
            if not DATE.fullmatch(line[0].text):
                continue
            if not anchors:
                layout(file, 'all 10 ToDate column labels must precede data')
            cells = {label: [] for label in DAY_COLUMNS}
            for word in line:
                cells[min(anchors, key=lambda label: abs(word.x1 - anchors[label]))].append(word.text)
            if any(len(values) > 1 for values in cells.values()):
                layout(file, f'ToDate row {line[0].text} has values that share a column')
            cell = {label: values[0] if values else None for label, values in cells.items()}
            if cell['Date'] is None or not DATE.fullmatch(cell['Date']):
                layout(file, f'ToDate row {line[0].text} has no date in the Date column')
            try:
                date = datetime.strptime(cell['Date'], '%d-%b-%Y')
            except ValueError:
                layout(file, f'invalid date {cell["Date"]!r}')
            # The PDF shows the date only. The time is invented: 00:00:00, then
            # one more second for each repeat of the date (CONTRACT-004).
            offset = repeats.get(date, 0)
            repeats[date] = offset + 1
            if cell['Downtime'] is not None and not DURATION.fullmatch(cell['Downtime']):
                layout(file, f'invalid duration {cell["Downtime"]!r}')
            days.append(Day(len(days)+1, (date + timedelta(seconds=offset)).strftime('%Y-%m-%d %H:%M:%S'),
                            *(number(cell[label], file) for label in DAY_COLUMNS[1:7]),
                            number(cell['Total Stops'], file, True),
                            cell['Downtime'], number(cell['Volume'], file)))
    if not anchors:
        layout(file, 'missing all 10 ToDate column labels')
    return tuple(days)


def pdf_volume_tolerance(total_volume, item_count):
    """Each displayed volume is rounded by up to half a unit."""
    return 0.5 * (item_count + 1)


@ensure(lambda result: all(record.row_order == i for records in (result.breakdown, result.days)
                           for i, record in enumerate(records, 1)), enabled=True)
def parse_pdf_report(path: str | Path, report_type: str) -> ParsedReport:
    """Read a Production Summary or ToDate PDF, returning all records or raising."""
    path = Path(path)
    if report_type not in SUPPORTED:
        layout(path, f'unsupported PDF report type {report_type!r}')
    pages = read_pages(path, path)
    metadata, page_count = header(pages, report_type, path)
    kwargs = {}
    if report_type == 'production_summary':
        kwargs['kpis'], kwargs['breakdown'] = production(pages, path)
    else:
        kwargs['days'] = todate(pages, path)
    result = ParsedReport(report_type, metadata, page_count, **kwargs)
    validate(result, path, pdf_volume_tolerance, 'within PDF rounding')
    return result


def pdf_printed_at(path: str | Path, report_type: str) -> str | None:
    """Best-effort page-1 printed timestamp of a PDF that failed to parse."""
    try:
        path = Path(path)
        return header(read_pages(path, path), report_type, path)[0].printed_at
    except Exception:
        return None
