"""CONTRACT-002 samples, altered grids, and independent failure-path checks."""
from dataclasses import replace
import builtins
import hashlib
from pathlib import Path
import socket
import sqlite3

import pytest
import xlrd

from raptor_etl.errors import LayoutError, ReconciliationError
from raptor_etl.parse import parse_grid, parse_report, DAY_COLUMNS, TITLES
from raptor_etl.parse.grid import Cell, Grid, read_grid

SAMPLES = Path(__file__).resolve().parents[1] / 'Samples'
FILES = {'downtime_summary': 'Downtime Summary.xls',
         'production_summary': 'Production Summary.xls',
         'production_todate': 'Production Todate.xls'}


def cell(value):
    if value is None:
        return Cell()
    return Cell(value, xlrd.XL_CELL_NUMBER if isinstance(value, (int, float)) else xlrd.XL_CELL_TEXT)


def row(*pairs):
    cells = [Cell()] * (max((c for c, _ in pairs), default=-1)+1)
    for c, value in pairs:
        cells[c] = value if isinstance(value, Cell) else cell(value)
    return tuple(cells)


def date(value=46335.208344907405):
    return Cell(value, xlrd.XL_CELL_DATE)


def common(kind):
    rows = [row((2, TITLES[kind])), row((2, 'Printed:'), (5, 'Nov 9, 2026 3:40 pm'))]
    if kind != 'production_todate':
        rows += [row((12, 'Report Start:'), (18, date())),
                 row((12, 'Report End:'), (18, date(46335.65277777778))),
                 row((12, 'Recipe:'), (18, ' <ALL> '))]
    return rows


def fixture(kind):
    rows = common(kind)
    if kind == 'downtime_summary':
        rows += [row((2, 'Alarm ID'), (7, 'Alarm Description:'), (18, 'Details (hh:mm:ss)')),
                 row((2, '7'), (5, '  Alarm text  '), (18, 'Total:'), (24, '100:00:10')),
                 row((5, 'Occurrences:')),
                 row((9, 2), (18, 'Min. Duration:'), (24, '00:00:02')),
                 row((18, 'Max. Duration:'), (24, '100:00:08')),
                 row((5, 'Grand Total:'), (9, 2), (18, 'Grand Total:'), (24, '100:00:10'))]
    elif kind == 'production_summary':
        rows += [row((1, 'Average BF Per Piece:'), (14, 'Lug Fill'), (20, 'Trimloss'), (28, 'Trimmer Speed')),
                 row((6, 2.8713249629155975), (14, 96), (20, 14), (24, 'Slow'), (29, 'Medium'), (36, 'Fast')),
                 row((24, 9), (29, 17), (36, 73))]
        for section in ('Product', 'Length', 'Grade', 'Width'):
            rows += [row((1, section+' Summary')), row((10, 'Total')),
                     row((2, '  Item  '), (6, 'Pieces'), (10, 2)),
                     row((6, 'Volume'), (10, 20.123456789)),
                     row((6, '% vol'), (10, 100)),
                     row((2, 'Total'), (6, 'Pieces'), (10, 2)),
                     row((6, 'Volume'), (10, 20.123456789)),
                     row((6, '% vol'), (10, 100))]
    else:
        rows += [row(*[(i*4, name) for i, name in enumerate(DAY_COLUMNS)]),
                 row(*[(i*4, value) for i, value in enumerate(
                     [date(), 10.123456789, 20, None, 96, 2.8713249629155975, 14, 2, '100:00:10', 123.456789])])]
    rows += [row((25, 'Page 2 of 2'))]
    return Grid(tuple(rows))


def edit(grid, row_index, col, value):
    rows = list(grid.rows)
    cells = list(rows[row_index])
    cells[col] = value if isinstance(value, Cell) else cell(value)
    rows[row_index] = tuple(cells)
    return replace(grid, rows=tuple(rows))


def find(grid, text):
    return [(r, c) for r, cells in enumerate(grid.rows) for c, value in enumerate(cells) if value.text == text]


def remove(grid, text):
    for r, c in find(grid, text):
        grid = edit(grid, r, c, None)
    return grid


@pytest.fixture
def sample_path():
    def get(kind):
        path = SAMPLES / FILES[kind]
        if not path.is_file():
            pytest.skip(f'Samples/ reference file absent: {path.name}')
        return path
    return get


@pytest.mark.parametrize('kind', TITLES)
def test_samples(kind, sample_path):
    report = parse_report(sample_path(kind), kind)
    assert report.report_type == kind
    assert report.header.printed_at == '2026-11-09 15:40:00'
    if kind != 'production_todate':
        assert report.header.report_start == '2026-11-09 05:00:01'
        assert report.header.report_end == '2026-11-09 15:40:00'
        assert report.header.recipe == '<ALL>'
        assert report.page_count == 2
    if kind == 'downtime_summary':
        assert len(report.alarms) == 20
        assert report.grand_total.occurrences == 380
        assert report.grand_total.total_duration == '01:49:49'
        first, last = report.alarms[0], report.alarms[-1]
        assert (first.alarm_id, first.description, first.occurrences, first.total_duration,
                first.min_duration, first.max_duration) == (7, 'Ready to Run', 162, '00:05:58', '00:00:00', '00:00:10')
        assert (last.alarm_id, last.description, last.occurrences, last.total_duration,
                last.min_duration, last.max_duration) == (237, 'Green Chain Landing Table V Pocket Full', 60, '00:10:42', '00:00:00', '00:01:05')
    elif kind == 'production_summary':
        assert len(report.breakdown) == 34
        assert {r.section: r.pieces for r in report.breakdown if r.is_total} == dict.fromkeys(('product', 'length', 'grade', 'width'), 58004)
        assert tuple(vars(report.kpis).values()) == (2.8713249629155975, 96, 14, 9, 17, 73)
        first, last = report.breakdown[0], report.breakdown[-1]
        assert (first.section, first.label, first.pieces, first.volume, first.pct_volume) == ('product', '2x4 .HQ Bronze', 28, 149.33333492279053, 0.0896636622530655)
        assert (last.section, last.label, last.pieces, last.volume, last.pct_volume) == ('product', 'Total', 58004, 166548.3331489563, 100)
    else:
        assert report.page_count == 3
        assert report.header.report_start is report.header.report_end is report.header.recipe is None
        assert len(report.days) == 81
        assert [r.slow_pct for r in report.days if r.run_start.startswith('2026-09-23')] == [None]
        assert [r.run_start for r in report.days if r.run_start.startswith('2026-09-16')] == ['2026-09-16 15:40:02', '2026-09-16 05:00:02']
        first, last = report.days[0], report.days[-1]
        assert tuple(vars(first).values()) == (1, '2026-11-09 05:00:01', 73, 17, 9, 96, 2.871264, 14, 380, '01:49:49', 166544.8)
        assert tuple(vars(last).values()) == (81, '2026-06-16 05:00:00', 36, 44, 20, 64, 3.1615090000000006, 18, 461, '01:50:41', 133539.0)
    records = report.alarms or report.breakdown or report.days
    assert [r.row_order for r in records] == list(range(1, len(records)+1))


@pytest.mark.parametrize('kind', TITLES)
def test_handbuilt_and_global_column_shift(kind):
    grid = fixture(kind)
    result = parse_grid(grid, kind)
    moved = replace(grid, rows=tuple((Cell(),)*13 + cells for cells in grid.rows))
    assert parse_grid(moved, kind) == result
    if result.alarms:
        assert result.alarms[0].description == 'Alarm text'
        assert result.alarms[0].total_duration == '100:00:10'
    if result.breakdown:
        assert result.breakdown[0].label == 'Item'
        assert result.breakdown[0].volume == 20.123456789
    if result.days:
        assert result.days[0].slow_pct is None
        assert result.days[0].fast_pct == 10.123456789
        assert result.days[0].downtime == '100:00:10'


LABEL_CASES = [(kind, label) for kind in TITLES for label in (
    ['Printed:', 'Page 2 of 2'] + ([] if kind == 'production_todate' else ['Report Start:', 'Report End:', 'Recipe:'])
    + (['Alarm ID', 'Alarm Description:', 'Details (hh:mm:ss)'] if kind == 'downtime_summary' else
       list(DAY_COLUMNS) if kind == 'production_todate' else
       ['Average BF Per Piece:', 'Lug Fill', 'Trimloss', 'Trimmer Speed', 'Slow', 'Medium', 'Fast',
        'Product Summary', 'Length Summary', 'Grade Summary', 'Width Summary']))]


@pytest.mark.parametrize('kind,label', LABEL_CASES)
def test_missing_precondition_labels(kind, label):
    with pytest.raises(LayoutError) as error:
        parse_grid(remove(fixture(kind), label), kind, 'broken.xls')
    assert type(error.value) is LayoutError
    assert 'broken.xls' in str(error.value)


@pytest.mark.parametrize('kind', TITLES)
def test_wrong_title(kind):
    grid = fixture(kind)
    r, c = find(grid, TITLES[kind])[0]
    with pytest.raises(LayoutError, match='page 1 title'):
        parse_grid(edit(grid, r, c, 'Unrecognized Report'), kind, 'wrong.xls')


@pytest.mark.parametrize('kind', TITLES)
def test_empty_records(kind):
    grid = fixture(kind)
    if kind == 'downtime_summary':
        start = find(grid, 'Alarm ID')[0][0] + 1
        end = find(grid, 'Grand Total:')[0][0]
        grid = replace(grid, rows=grid.rows[:start]+grid.rows[end:])
    elif kind == 'production_todate':
        start = find(grid, 'Date')[0][0] + 1
        grid = replace(grid, rows=grid.rows[:start]+grid.rows[-1:])
    else:
        grid = replace(grid, rows=tuple(cells for cells in grid.rows
                                       if not any(c.text in ('Pieces', 'Volume', '% vol') for c in cells)))
    with pytest.raises(ReconciliationError, match='at least one data record.*expected.*actual'):
        parse_grid(grid, kind, 'empty.xls')


@pytest.mark.parametrize('field,value,check', [
    ('Grand Total:', 3, 'occurrences sum'),
    ('Total:', '100:00:11', 'total_duration sum'),
    ('Min. Duration:', '100:00:09', 'duration bounds'),
    ('Max. Duration:', '100:00:11', 'duration bounds'),
])
def test_downtime_invariants(field, value, check):
    grid = fixture('downtime_summary')
    r, c = find(grid, field)[0]
    col = 9 if field == 'Grand Total:' else 24
    if field == 'Total:':
        # Alter grand total duration, leaving alarm duration bounds valid.
        r = find(grid, 'Grand Total:')[-1][0]
    grid = edit(grid, r, col, value)
    with pytest.raises(ReconciliationError, match=check+'.*expected.*actual') as error:
        parse_grid(grid, 'downtime_summary', 'bad.xls')
    assert 'bad.xls' in str(error.value)


@pytest.mark.parametrize('mode,check', [('missing_total', 'Total row count'),
                                      ('two_totals', 'Total row count'),
                                      ('pieces', 'pieces sum'),
                                      ('unequal', 'four Total pieces equal'),
                                      ('volume', 'volume sum')])
def test_production_invariants(mode, check):
    grid = fixture('production_summary')
    pieces = find(grid, 'Pieces')
    if mode == 'missing_total':
        grid = edit(grid, pieces[1][0], 2, 'Other')
    elif mode == 'two_totals':
        grid = edit(grid, pieces[0][0], 2, 'Total')
    elif mode == 'pieces':
        grid = edit(grid, pieces[0][0], 10, 3)
    elif mode == 'unequal':
        for r, c in pieces[:2]:
            grid = edit(grid, r, 10, 3)
    else:
        grid = edit(grid, find(grid, 'Volume')[0][0], 10, 21)
    with pytest.raises(ReconciliationError, match=check+'.*expected.*actual'):
        parse_grid(grid, 'production_summary', 'bad.xls')


@pytest.mark.parametrize('null', [True, False])
def test_todate_invariants(null):
    grid = fixture('production_todate')
    r = find(grid, 'Date')[0][0]+1
    if null:
        grid = edit(grid, r, 0, None)
    else:
        grid = replace(grid, rows=grid.rows[:r]+(grid.rows[r],)+grid.rows[r:])
    with pytest.raises(ReconciliationError, match=('non-null' if null else 'unique')+' run_start.*expected.*actual'):
        parse_grid(grid, 'production_todate', 'bad.xls')


@pytest.mark.parametrize('kind', TITLES)
def test_headers_after_data_rejected(kind):
    grid = fixture(kind)
    if kind == 'production_summary':
        r = find(grid, 'Width Summary')[0][0]
        rows = list(grid.rows)
        title = rows.pop(r)
        rows.insert(r+4, title)
    else:
        label = 'Alarm ID' if kind == 'downtime_summary' else 'Date'
        r = find(grid, label)[0][0]
        rows = list(grid.rows)
        title = rows.pop(r)
        rows.insert(r+1, title)
    with pytest.raises(LayoutError) as error:
        parse_grid(replace(grid, rows=tuple(rows)), kind, 'late.xls')
    assert type(error.value) is LayoutError


def test_kpi_label_after_value_rejected():
    grid = fixture('production_summary')
    r, c = find(grid, 'Average BF Per Piece:')[0]
    label = grid.cell(r, c)
    grid = edit(grid, r, c, None)
    grid = edit(grid, r+2, c, label)
    with pytest.raises(LayoutError, match='must precede'):
        parse_grid(grid, 'production_summary')


def test_repeated_headers_realign_and_furniture():
    grid = fixture('production_todate')
    r = find(grid, 'Date')[0][0]
    furniture = (row((1, TITLES['production_todate'])),
                 row((1, 'Printed: November 09, 2026 3:40:12PM')),
                 row((1, 'Company/address block')))
    header = (Cell(),)*9 + grid.rows[r]
    data = (Cell(),)*9 + grid.rows[r+1]
    data = tuple(date(46334.208333333336) if i == 9 else c for i, c in enumerate(data))
    altered = replace(grid, rows=grid.rows[:-1]+furniture+(header, data)+grid.rows[-1:])
    result = parse_grid(altered, 'production_todate')
    assert len(result.days) == 2
    assert result.days[1].run_start == '2026-11-08 05:00:00'
    assert result.days[1].volume == result.days[0].volume


def test_sample_shift_and_continuation(sample_path):
    for kind in TITLES:
        grid = read_grid(sample_path(kind))
        # Shift every row by a different whole-page offset at the repeated title.
        titles = find(grid, TITLES[kind])
        rows = []
        for r, cells in enumerate(grid.rows):
            offset = 11 * sum(index <= r for index, _ in titles)
            rows.append((Cell(),)*offset+cells)
        assert parse_grid(replace(grid, rows=tuple(rows)), kind) == parse_grid(grid, kind)


@pytest.mark.parametrize('suffix', ['.pdf', '.xlsx', '.txt'])
def test_non_xls(suffix, tmp_path):
    with pytest.raises(LayoutError, match='BIFF .xls'):
        parse_report(tmp_path / ('report'+suffix), 'downtime_summary')


def test_unreadable_and_non_biff(tmp_path):
    with pytest.raises(LayoutError, match='cannot open BIFF'):
        parse_report(tmp_path / 'missing.xls', 'downtime_summary')
    file = tmp_path / 'bad.xls'
    file.write_bytes(b'not a workbook')
    with pytest.raises(LayoutError, match='cannot open BIFF'):
        parse_report(file, 'downtime_summary')


def test_wrong_declared_type(sample_path):
    with pytest.raises(LayoutError, match='page 1 title'):
        parse_report(sample_path('downtime_summary'), 'production_summary')
    with pytest.raises(LayoutError, match='unsupported report type'):
        parse_report('not-needed.xls', 'thickness_breakdown')


def test_pure_read_only(sample_path, monkeypatch, capsys):
    paths = [sample_path(kind) for kind in TITLES]
    def snapshot():
        return [(hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths]
    before = snapshot()
    original = builtins.open
    def readonly(file, mode='r', *args, **kwargs):
        assert not any(flag in mode for flag in 'wax+')
        return original(file, mode, *args, **kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail('Parser attempted DB/network/file write side effect')
    monkeypatch.setattr(builtins, 'open', readonly)
    original_path_open = Path.open
    def path_readonly(path, mode='r', *args, **kwargs):
        assert not any(flag in mode for flag in 'wax+')
        return original_path_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', path_readonly)
    monkeypatch.setattr(Path, 'write_bytes', forbidden)
    monkeypatch.setattr(Path, 'write_text', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    for kind, path in zip(TITLES, paths):
        parse_report(path, kind)
    assert snapshot() == before
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('kind', TITLES)
def test_blank_value_cells_remain_null(kind):
    grid = fixture(kind)
    if kind == 'production_todate':
        r = find(grid, 'Date')[0][0]+1
        for col in (4, 8, 12, 16, 20, 24, 28, 32, 36):
            grid = edit(grid, r, col, None)
        record = parse_grid(grid, kind).days[0]
        assert all(value is None for key, value in vars(record).items() if key not in ('row_order', 'run_start'))
    elif kind == 'production_summary':
        for r, c in find(grid, '% vol'):
            grid = edit(grid, r, 10, None)
        r = find(grid, 'Average BF Per Piece:')[0][0]+1
        grid = edit(grid, r, 6, None)
        result = parse_grid(grid, kind)
        assert result.kpis.avg_bf_per_piece is None
        assert all(record.pct_volume is None for record in result.breakdown)
    else:
        r = find(grid, 'Alarm ID')[0][0]+1
        grid = edit(grid, r, 5, None)
        assert parse_grid(grid, kind).alarms[0].description is None


@pytest.mark.parametrize('field,value,check', [('Total:', 'broken', 'invalid duration'),
                                             ('Occurrences:', 1.5, 'integer count'),
                                             ('Occurrences:', 'many', 'numeric cell')])
def test_invalid_cell_types(field, value, check):
    grid = fixture('downtime_summary')
    if field == 'Occurrences:':
        r = find(grid, field)[0][0]+1
        col = 9
        if isinstance(value, str):
            # Put an explicit invalid value alongside its label.
            r -= 1
            cells = list(grid.rows)
            cells[r] = row((5, field), (9, value))
            grid = replace(grid, rows=tuple(cells))
            with pytest.raises(LayoutError):
                parse_grid(grid, 'downtime_summary')
            return
    else:
        r = find(grid, field)[0][0]
        col = 24
    with pytest.raises(LayoutError, match=check):
        parse_grid(edit(grid, r, col, value), 'downtime_summary')


@pytest.mark.parametrize('fraction,expected', [(0.4996, '2026-11-09 00:00:00'),
                                             (0.5004, '2026-11-09 00:00:01'),
                                             (86399.8, '2026-11-10 00:00:00')])
def test_excel_nearest_second(fraction, expected):
    grid = fixture('production_todate')
    r = find(grid, 'Date')[0][0]+1
    result = parse_grid(edit(grid, r, 0, date(46335+fraction/86400)), 'production_todate')
    assert result.days[0].run_start == expected


def test_excel_1904_datemode():
    from raptor_etl.parse import timestamp
    assert timestamp(date(0), Grid((), datemode=1), 'date.xls') == '1904-01-01 00:00:00'


def test_malformed_header_timestamp():
    grid = fixture('production_todate')
    r, c = find(grid, 'Printed:')[0]
    with pytest.raises(LayoutError, match='invalid timestamp'):
        parse_grid(edit(grid, r, 5, 'not a date'), 'production_todate', 'date.xls')


def test_repeated_downtime_headers_realign():
    grid = fixture('downtime_summary')
    r = find(grid, 'Alarm ID')[0][0]
    end = find(grid, 'Grand Total:')[0][0]
    offset = 17
    continued = tuple((Cell(),)*offset+cells for cells in grid.rows[r:end])
    rows = grid.rows[:end] + (row((1, 'Downtime Summary Report')),
                             row((1, 'Printed: ignored later page')))+continued+grid.rows[end:]
    grid = replace(grid, rows=rows)
    total_row = find(grid, 'Grand Total:')[0][0]
    grid = edit(grid, total_row, 9, 4)
    grid = edit(grid, total_row, 24, '200:00:20')
    result = parse_grid(grid, 'downtime_summary')
    assert len(result.alarms) == 2
    assert replace(result.alarms[1], row_order=1) == result.alarms[0]


def test_partial_repeated_todate_header_rejected():
    grid = fixture('production_todate')
    rows = grid.rows[:-1] + (row((2, 'Date'), (5, 'Fast %')),) + grid.rows[-1:]
    with pytest.raises(LayoutError, match='all 10'):
        parse_grid(replace(grid, rows=rows), 'production_todate')


@pytest.mark.parametrize('difference,valid', [(0.001, True), (0.01, False)])
def test_volume_relative_tolerance(difference, valid):
    grid = fixture('production_summary')
    r = find(grid, 'Volume')[0][0]
    grid = edit(grid, r, 10, 20.123456789+difference)
    if valid:
        assert parse_grid(grid, 'production_summary').breakdown[0].volume == 20.123456789+difference
    else:
        with pytest.raises(ReconciliationError, match='within 0.01%'):
            parse_grid(grid, 'production_summary')


@pytest.mark.parametrize('kind,field', [('downtime_summary', 'Occurrences:'),
                                       ('downtime_summary', 'Total:'),
                                       ('production_summary', 'Pieces'),
                                       ('production_summary', 'Volume')])
def test_null_reconciliation_inputs_are_rejected(kind, field):
    grid = fixture(kind)
    r, _ = find(grid, field)[0]
    if kind == 'downtime_summary':
        if field == 'Occurrences:':
            r += 1
        col = 9 if field == 'Occurrences:' else 24
    else:
        col = 10
    with pytest.raises(ReconciliationError, match='expected.*actual'):
        parse_grid(edit(grid, r, col, None), kind, 'null.xls')


def test_sample_parallel_missing_value_not_borrowed(sample_path):
    grid = read_grid(sample_path('production_summary'))
    r, c = find(grid, 'Pieces')[0]
    numeric_col = next(col for col, candidate in grid.populated(r) if col > c)
    with pytest.raises(ReconciliationError, match='pieces sum'):
        parse_grid(edit(grid, r, numeric_col, None), 'production_summary')
