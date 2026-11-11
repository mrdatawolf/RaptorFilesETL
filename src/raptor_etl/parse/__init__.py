"""Pure, label-driven Raptor BIFF report parsing (CONTRACT-002)."""
from dataclasses import replace
from datetime import datetime, timedelta
import math
from pathlib import Path
import re

from icontract import ensure, require
import xlrd

from ..errors import LayoutError, ReconciliationError
from .grid import Cell, Grid, read_grid
from .models import Alarm, Breakdown, Day, GrandTotal, Header, KPIs, ParsedReport

TITLES = {
    'downtime_summary': 'Downtime Summary Report',
    'production_summary': 'Production Summary Report',
    'production_todate': 'Production ToDate Report',
}
SECTIONS = ('product', 'length', 'grade', 'width')
DAY_COLUMNS = ('Date', 'Fast %', 'Medium %', 'Slow %', 'Lug Fill', 'BF Per Piece',
               'Trimloss', 'Total Stops', 'Downtime', 'Volume')
DURATION = re.compile(r'\d+:[0-5]\d:[0-5]\d\Z')


def layout(file, check):
    raise LayoutError(f'{file}: {check}')


def reconcile(file, check, expected, actual):
    raise ReconciliationError(f'{file}: {check}: expected {expected!r}, actual {actual!r}')


def number(cell, file, integer=False):
    if cell.empty:
        return None
    if cell.ctype != xlrd.XL_CELL_NUMBER or not isinstance(cell.value, (int, float)) or not math.isfinite(cell.value):
        layout(file, f'expected numeric cell, got {cell.value!r}')
    if integer:
        if int(cell.value) != cell.value:
            layout(file, f'expected integer count, got {cell.value!r}')
        return int(cell.value)
    return float(cell.value)


def duration(cell, file):
    if cell.empty:
        return None
    if not isinstance(cell.value, str) or not DURATION.fullmatch(cell.value):
        layout(file, f'invalid duration {cell.value!r}')
    return cell.value


def seconds(value):
    if value is None:
        return None
    hours, minutes, secs = map(int, value.split(':'))
    return hours * 3600 + minutes * 60 + secs


def timestamp(cell, grid, file):
    if cell.empty:
        return None
    try:
        if cell.ctype == xlrd.XL_CELL_DATE:
            whole_days = math.floor(cell.value)
            nearest_second = math.floor((cell.value-whole_days)*86400 + 0.5)
            value = xlrd.xldate_as_datetime(whole_days, grid.datemode) + timedelta(seconds=nearest_second)
        else:
            text = ' '.join(str(cell.value).split())
            value = None
            for fmt in ('%b %d, %Y %I:%M %p', '%B %d, %Y %I:%M:%S%p'):
                try:
                    value = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if value is None:
                raise ValueError
        return value.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError, OverflowError, xlrd.XLDateError):
        layout(file, f'invalid timestamp {cell.value!r}')


def right(grid, row, col):
    """Next occupied cell on this row; labels delimit sparse header/value pairs."""
    return next((cell for c, cell in grid.populated(row) if c > col), Cell())


def locations(grid, label):
    return [(r, c) for r in range(len(grid.rows)) for c, cell in grid.populated(r)
            if cell.text == label]


def header(grid, kind, file):
    titles = [(r, cell.text) for r in range(len(grid.rows)) for _, cell in grid.populated(r)
              if cell.text in TITLES.values() or cell.text.endswith(' Report')]
    if not titles or titles[0][1] != TITLES[kind]:
        layout(file, f'page 1 title must equal {TITLES[kind]!r}')
    required = ['Printed:']
    if kind != 'production_todate':
        required += ['Report Start:', 'Report End:', 'Recipe:']
    values = {}
    for label in required:
        found = locations(grid, label)
        if not found:
            layout(file, f'missing header label {label}')
        r, c = found[0]
        cell = right(grid, r, c)
        # Do not mistake another header label for an empty value.
        if cell.text in required:
            cell = Cell()
        values[label] = cell.text if label == 'Recipe:' and not cell.empty else (
            timestamp(cell, grid, file) if label != 'Recipe:' else None)
    pages = [re.fullmatch(r'Page (\d+) of (\d+)', cell.text)
             for row in grid.rows for cell in row]
    pages = [match for match in pages if match]
    if not pages or int(pages[-1][2]) < 1:
        layout(file, 'missing Page N of N marker')
    return Header(values['Printed:'], values.get('Report Start:'),
                  values.get('Report End:'), values.get('Recipe:')), int(pages[-1][2])


def furniture(row):
    return any(cell.text in TITLES.values() or cell.text.startswith(('Printed:', 'Page '))
               for _, cell in row)


@require(lambda anchors: bool(anchors), enabled=True)
def aligned(grid, row, anchors):
    """Assign occupied cells to their nearest header, preserving absent columns."""
    groups = {key: [] for key in anchors}
    for col, cell in grid.populated(row):
        key = min(anchors, key=lambda key: abs(col - anchors[key]))
        groups[key].append(cell)
    return {key: cells[0] if len(cells) == 1 else Cell() for key, cells in groups.items()}


def downtime(grid, file):
    required = ('Alarm ID', 'Alarm Description:', 'Details (hh:mm:ss)')
    anchors = {}
    alarms = []
    current = None
    total = GrandTotal(None, None)
    seen = set()
    occurrence_label = None
    for r in range(len(grid.rows)):
        row = grid.populated(r)
        if furniture(row):
            continue
        labels = {cell.text: c for c, cell in row}
        for label in required:
            if label in labels:
                anchors[label] = labels[label]
                seen.add(label)
        if any(label in labels for label in required):
            continue
        # Alarm IDs are text in the BIFF export. Anchor them to the ID header.
        candidates = [(c, cell) for c, cell in row
                      if re.fullmatch(r'\d+', cell.text) or cell.ctype == xlrd.XL_CELL_NUMBER]
        id_col = anchors.get('Alarm ID')
        first = next(((c, cell) for c, cell in candidates
                      if id_col is not None and c == id_col), None)
        if any(cell.text.isdigit() for _, cell in row) and seen != set(required):
            layout(file, 'downtime headers must precede first alarm')
        if first:
            if seen != set(required):
                layout(file, 'downtime headers must precede first alarm')
            if current is not None:
                alarms.append(Alarm(len(alarms)+1, **current))
            c, cell = first
            description = next((candidate for col, candidate in row
                                if c < col < anchors['Details (hh:mm:ss)']), Cell())
            current = dict(alarm_id=int(cell.value), description=description.text or None,
                           occurrences=None, total_duration=None, min_duration=None, max_duration=None)
        elif not anchors and any(cell.text.isdigit() for _, cell in row):
            layout(file, 'downtime headers must precede first alarm')
        if 'Grand Total:' in labels:
            cells = [right(grid, r, c) for c, cell in row if cell.text == 'Grand Total:']
            numeric = next((cell for cell in cells if cell.ctype == xlrd.XL_CELL_NUMBER), Cell())
            text = next((cell for cell in cells if DURATION.fullmatch(cell.text)), Cell())
            total = GrandTotal(number(numeric, file, True), duration(text, file))
            continue
        if current is not None:
            for label, field in (('Total:', 'total_duration'), ('Min. Duration:', 'min_duration'),
                                 ('Max. Duration:', 'max_duration')):
                if label in labels:
                    current[field] = duration(right(grid, r, labels[label]), file)
            if 'Occurrences:' in labels:
                occurrence_label = (r, labels['Occurrences:'])
                cell = right(grid, r, labels['Occurrences:'])
                if not cell.empty and cell.text not in ('Total:', 'Min. Duration:', 'Max. Duration:'):
                    current['occurrences'] = number(cell, file, True)
                    occurrence_label = None
            elif occurrence_label is not None:
                # Occurrences is printed below its label; select the first numeric
                # value before the details column, rather than an absolute column.
                candidates = [cell for c, cell in row if c >= occurrence_label[1]
                              and c < anchors['Details (hh:mm:ss)']]
                if candidates:
                    current['occurrences'] = number(candidates[0], file, True)
                    occurrence_label = None
    if seen != set(required):
        layout(file, f'missing downtime headers: {set(required)-seen}')
    if current is not None:
        alarms.append(Alarm(len(alarms)+1, **current))
    return tuple(alarms), total


def todate(grid, file):
    anchors = {}
    days = []
    for r in range(len(grid.rows)):
        row = grid.populated(r)
        if furniture(row):
            continue
        labels = {cell.text: c for c, cell in row}
        if any(label in labels for label in DAY_COLUMNS):
            if not all(label in labels for label in DAY_COLUMNS):
                layout(file, 'all 10 ToDate column labels required at each header')
            anchors = {label: labels[label] for label in DAY_COLUMNS}
            continue
        if any(cell.ctype in (xlrd.XL_CELL_DATE, xlrd.XL_CELL_NUMBER) or DURATION.fullmatch(cell.text)
               for _, cell in row):
            if not anchors:
                layout(file, 'all 10 ToDate column labels must precede data')
            cells = aligned(grid, r, anchors)
            days.append(Day(len(days)+1, timestamp(cells['Date'], grid, file),
                            *(number(cells[label], file) for label in DAY_COLUMNS[1:7]),
                            number(cells['Total Stops'], file, True),
                            duration(cells['Downtime'], file), number(cells['Volume'], file)))
    if not anchors:
        layout(file, 'missing all 10 ToDate column labels')
    return tuple(days)


def production(grid, file):
    kpi_labels = ('Average BF Per Piece:', 'Lug Fill', 'Trimloss', 'Slow', 'Medium', 'Fast')
    kpi_values = []
    for label in (*kpi_labels, 'Trimmer Speed'):
        if not locations(grid, label):
            layout(file, f'missing KPI label {label}')
    first_section = min((r for section in SECTIONS for r, _ in locations(grid, section.title()+' Summary')),
                        default=len(grid.rows))
    for label in kpi_labels:
        r, c = locations(grid, label)[0]
        if r >= first_section:
            layout(file, f'KPI label {label} must precede KPI value')
        next_labels = [col for col, cell in grid.populated(r) if col > c and cell.text in kpi_labels]
        boundary = min(next_labels, default=math.inf)
        if any(candidate.ctype == xlrd.XL_CELL_NUMBER
               for rr in range(r) for col, candidate in grid.populated(rr)
               if c <= col < boundary):
            layout(file, f'KPI label {label} must precede KPI value')
        cell = Cell()
        for rr in range(r+1, first_section):
            numeric = [(col, candidate) for col, candidate in grid.populated(rr)
                       if c <= col < boundary and candidate.ctype == xlrd.XL_CELL_NUMBER]
            if numeric:
                cell = min(numeric, key=lambda pair: abs(pair[0]-c))[1]
                break
        kpi_values.append(number(cell, file))
    speed_row = locations(grid, 'Trimmer Speed')[0][0]
    if any(locations(grid, label)[0][0] < speed_row for label in ('Slow', 'Medium', 'Fast')):
        layout(file, 'Trimmer Speed label must precede speed KPI values')
    pending = []
    seen = set()
    lanes = {}
    current = {}
    records = []
    completed = set()
    for r in range(first_section, len(grid.rows)):
        row = grid.populated(r)
        if furniture(row):
            lanes = {}
            continue
        titles = [(c, section) for c, cell in row for section in SECTIONS
                  if cell.text == section.title()+' Summary']
        for _, section in titles:
            seen.add(section)
            pending.append(section)
        if titles:
            continue
        pieces = [(c, cell) for c, cell in row if cell.text == 'Pieces']
        totals = [c for c, cell in row if cell.text == 'Total']
        if totals and not pieces:
            sections = pending or [section for section in SECTIONS if section in seen and section not in completed]
            if len(totals) != len(sections):
                layout(file, 'section titles/continuation must label each Total column')
            lanes.update(zip(totals, sections))
            pending = []
            continue
        for c, cell in row:
            if cell.text not in ('Pieces', 'Volume', '% vol'):
                continue
            if not lanes:
                layout(file, 'section title and Total column must precede section records')
            right_lanes = [col for col in lanes if col > c]
            if not right_lanes:
                layout(file, 'metric has no labeled value column to its right')
            lane = min(right_lanes)
            value = grid.cell(r, lane)
            section = lanes[lane]
            if cell.text == 'Pieces':
                preceding = [candidate for col, candidate in row if col < c]
                label = preceding[-1].text if preceding else None
                index = len(records)
                records.append(Breakdown(index+1, section, label, label == 'Total',
                                         number(value, file, True), None, None))
                current[section] = index
                if label == 'Total':
                    completed.add(section)
            else:
                if section not in current:
                    layout(file, f'{section} metric before first Pieces record')
                index = current[section]
                field = 'volume' if cell.text == 'Volume' else 'pct_volume'
                records[index] = replace(records[index], **{field: number(value, file)})
    if seen != set(SECTIONS):
        layout(file, f'missing section titles: {set(SECTIONS)-seen}')
    return KPIs(*kpi_values), tuple(records)


def checked_sum(values, file, check):
    if any(value is None for value in values):
        reconcile(file, check, 'non-null values to reconcile', values)
    return sum(values)


def validate(report, file):
    records = report.alarms or report.breakdown or report.days
    if not records:
        reconcile(file, 'at least one data record', '>= 1', 0)
    if report.report_type == 'downtime_summary':
        total = report.grand_total
        for field in ('occurrences', 'total_duration'):
            values = [getattr(alarm, field) for alarm in report.alarms]
            expected = getattr(total, field)
            if field == 'total_duration':
                values = [seconds(value) for value in values]
                expected = seconds(expected)
            actual = checked_sum(values, file, f'alarm {field} sum')
            if expected != actual:
                reconcile(file, f'alarm {field} sum', expected, actual)
        for alarm in report.alarms:
            low, high, total_seconds = map(seconds, (alarm.min_duration, alarm.max_duration, alarm.total_duration))
            if None in (low, high, total_seconds) or not low <= high <= total_seconds:
                reconcile(file, f'alarm {alarm.alarm_id} duration bounds', 'min <= max <= total',
                          (low, high, total_seconds))
    elif report.report_type == 'production_summary':
        totals = []
        for section in SECTIONS:
            rows = [row for row in report.breakdown if row.section == section]
            total_rows = [row for row in rows if row.is_total]
            if len(total_rows) != 1:
                reconcile(file, f'{section} Total row count', 1, len(total_rows))
            total = total_rows[0]
            totals.append(total.pieces)
            items = [row for row in rows if not row.is_total]
            actual = checked_sum([row.pieces for row in items], file, f'{section} pieces sum')
            if actual != total.pieces:
                reconcile(file, f'{section} pieces sum', total.pieces, actual)
            volume = checked_sum([row.volume for row in items], file, f'{section} volume sum')
            if total.volume is None or abs(volume-total.volume) > abs(total.volume)*0.0001:
                reconcile(file, f'{section} volume sum (within 0.01%)', total.volume, volume)
        if len(set(totals)) != 1:
            reconcile(file, 'four Total pieces equal', totals[0], totals)
    else:
        starts = [day.run_start for day in report.days]
        if None in starts:
            reconcile(file, 'non-null run_start', 'non-null for every row', starts)
        if len(starts) != len(set(starts)):
            reconcile(file, 'unique run_start', len(starts), len(set(starts)))


@ensure(lambda result: all(record.row_order == i for records in
        (result.alarms, result.breakdown, result.days)
        for i, record in enumerate(records, 1)), enabled=True)
def parse_grid(grid: Grid, report_type: str, filename='<grid>') -> ParsedReport:
    """Parse an immutable grid; public seam for offline altered-layout tests."""
    if report_type not in TITLES:
        layout(filename, f'unsupported report type {report_type!r}')
    metadata, page_count = header(grid, report_type, filename)
    kwargs = {}
    if report_type == 'downtime_summary':
        kwargs['alarms'], kwargs['grand_total'] = downtime(grid, filename)
    elif report_type == 'production_summary':
        kwargs['kpis'], kwargs['breakdown'] = production(grid, filename)
    else:
        kwargs['days'] = todate(grid, filename)
    result = ParsedReport(report_type, metadata, page_count, **kwargs)
    validate(result, filename)
    return result


def parse_report(path: str | Path, report_type: str) -> ParsedReport:
    """Read a BIFF .xls report, returning all records or raising a typed error."""
    path = Path(path)
    if report_type not in TITLES:
        layout(path, f'unsupported report type {report_type!r}')
    return parse_grid(read_grid(path), report_type, str(path))
