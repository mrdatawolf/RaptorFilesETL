"""CONTRACT-004: PDF parsing, cross-check against .xls, and the import-pdf command."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3

import pytest

from raptor_etl import cli
from raptor_etl.clock import Clock
from raptor_etl.collect import file_hash
from raptor_etl.config import load_config
from raptor_etl.database import open_database
from raptor_etl.errors import LayoutError
from raptor_etl.load import load_stage
from raptor_etl.lock import run_lock
from raptor_etl.parse import parse_report
from raptor_etl.parse.pdf import parse_pdf_report

SAMPLES = Path(__file__).resolve().parents[1] / 'Samples'
PDF = SAMPLES / 'PDF'
XLS = SAMPLES / 'XLS'
pytestmark = pytest.mark.skipif(not PDF.is_dir() or not XLS.is_dir(),
                                reason='Samples/PDF or Samples/XLS is absent; PDF import tests need sample reports')
NAMES = {'production_summary': 'Production Summary', 'production_todate': 'Production Todate'}
# PDF folder -> .xls folder holding the report printed on the same day.
# Samples/XLS/11_11_2026 holds reports printed 2026-11-13.
PAIRS = (('11_09_2026', '11_09_2026'), ('11_13_2026', '11_11_2026'))
NOW = datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc)   # 10:00 plant time


def pdf(day, kind):
    return PDF / day / f'{NAMES[kind].lower()}.pdf'


@pytest.mark.parametrize('kind', NAMES)
@pytest.mark.parametrize('day,count', [('11_09_2026', (34, 81)), ('11_10_2026', (30, 81)),
                                       ('11_11_2026', (35, 81)), ('11_13_2026', (8, 80))])
def test_all_sample_days_parse(day, count, kind):
    report = parse_pdf_report(pdf(day, kind), kind)
    records = report.breakdown or report.days
    assert len(records) == count[kind == 'production_todate']
    assert [record.row_order for record in records] == list(range(1, len(records) + 1))
    assert report.header.printed_at.endswith(' 15:40:00')


def within(pdf_value, xls_value, decimals):
    if pdf_value is None or xls_value is None:
        return pdf_value is None and xls_value is None
    return abs(pdf_value - xls_value) <= 0.5 * 10 ** -decimals + 1e-9


@pytest.mark.parametrize('pdf_day,xls_day', PAIRS)
def test_summary_cross_check(pdf_day, xls_day):
    kind = 'production_summary'
    p = parse_pdf_report(pdf(pdf_day, kind), kind)
    x = parse_report(XLS / xls_day / f'{NAMES[kind]}.xls', kind)
    assert (p.header.printed_at, p.header.recipe, p.page_count) == (
        x.header.printed_at, x.header.recipe, x.page_count)
    assert p.header.report_start == x.header.report_start[:-2] + '00'
    assert p.header.report_end == x.header.report_end[:-2] + '00'
    assert [(r.section, r.label, r.is_total) for r in p.breakdown] == [
        (r.section, r.label, r.is_total) for r in x.breakdown]
    for a, b in zip(p.breakdown, x.breakdown):
        assert a.pieces == b.pieces
        assert within(a.volume, b.volume, 0) and within(a.pct_volume, b.pct_volume, 2)
    for field, decimals in (('avg_bf_per_piece', 2), ('lug_fill', 0), ('trimloss', 1),
                            ('trimmer_speed_slow_pct', 0), ('trimmer_speed_medium_pct', 0),
                            ('trimmer_speed_fast_pct', 0)):
        assert within(getattr(p.kpis, field), getattr(x.kpis, field), decimals), field


@pytest.mark.parametrize('pdf_day,xls_day', PAIRS)
def test_todate_cross_check(pdf_day, xls_day):
    kind = 'production_todate'
    p = parse_pdf_report(pdf(pdf_day, kind), kind)
    x = parse_report(XLS / xls_day / f'{NAMES[kind]}.xls', kind)
    assert (p.header, p.page_count) == (x.header, x.page_count)
    assert len(p.days) == len(x.days)
    for a, b in zip(p.days, x.days):
        assert a.run_start[:10] == b.run_start[:10]
        assert (a.total_stops, a.downtime) == (b.total_stops, b.downtime)
        for field, decimals in (('fast_pct', 0), ('medium_pct', 0), ('slow_pct', 0), ('lug_fill', 0),
                                ('bf_per_piece', 2), ('trimloss', 2), ('volume', 0)):
            assert within(getattr(a, field), getattr(b, field), decimals), (a.run_start, field)


def test_repeated_date_gets_next_second_and_blank_is_null():
    days = parse_pdf_report(pdf('11_09_2026', 'production_todate'), 'production_todate').days
    assert [d.run_start for d in days if d.run_start.startswith('2026-09-16')] == [
        '2026-09-16 00:00:00', '2026-09-16 00:00:01']
    assert all(d.run_start.endswith(' 00:00:00') for d in days if not d.run_start.startswith('2026-09-16'))
    blank, = (d for d in days if d.run_start.startswith('2026-09-23'))
    assert blank.slow_pct is None and blank.fast_pct == 100.0


def test_wrapped_label_and_empty_day():
    report = parse_pdf_report(pdf('11_13_2026', 'production_summary'), 'production_summary')
    assert [r.label for r in report.breakdown if r.section == 'length'] == ['No Data', 'Total']
    assert report.kpis.trimmer_speed_slow_pct is None


def test_wrong_title_and_unsupported_type():
    with pytest.raises(LayoutError, match='title'):
        parse_pdf_report(pdf('11_09_2026', 'production_todate'), 'production_summary')
    with pytest.raises(LayoutError, match='unsupported'):
        parse_pdf_report(pdf('11_09_2026', 'production_todate'), 'downtime_summary')


@pytest.fixture
def importer(configured, monkeypatch):
    archive = configured / 'archive'
    archive.mkdir()
    monkeypatch.setenv('RAPTOR_ARCHIVE_DIR', str(archive))
    monkeypatch.setattr(cli, 'Clock', lambda zone: Clock(zone, lambda: NOW))
    return configured


def seed_xls(root):
    """Archive and load the .xls Production reports for 2026-11-09 and 2026-11-13."""
    config = load_config()
    database = open_database(config.db_path)
    try:
        for folder, day in (('11_09_2026', '2026-11-09'), ('11_11_2026', '2026-11-13')):
            for kind in NAMES.values():
                source = XLS / folder / f'{kind}.xls'
                archive_name = f'{day}_{kind}.xls'
                shutil.copy(source, config.archive_dir / archive_name)
                with database:
                    database.execute(
                        'INSERT INTO archived_file (original_name, archive_name, copy_date, sha256, '
                        'size_bytes, archived_at) VALUES (?, ?, ?, ?, ?, ?)',
                        (f'{kind}.xls', archive_name, day, file_hash(source),
                         source.stat().st_size, f'{day} 23:00:00'))
        assert load_stage(config, database, Clock(config.timezone, lambda: NOW))
    finally:
        database.close()


def loads(root):
    with sqlite3.connect(root / 'bronze.db') as db:
        return sorted(db.execute(
            'SELECT a.archive_name, a.copy_date, f.record_count FROM file_load f '
            'JOIN archived_file a ON a.id=f.archived_file_id'))


def test_import_skips_xls_days_and_is_idempotent(importer, capsys):
    seed_xls(importer)
    assert cli.main(['import-pdf', str(PDF)]) == 0
    out = capsys.readouterr().out
    assert out.count('skipped: xls already loaded for 2026-11-09') == 2
    assert out.count('skipped: xls already loaded for 2026-11-13') == 2
    assert out.count('ignored: not supported') == 4
    pdf_loads = [row for row in loads(importer) if row[0].endswith('.pdf')]
    assert pdf_loads == [
        ('2026-11-10_Production Summary.pdf', '2026-11-10', 30),
        ('2026-11-10_Production Todate.pdf', '2026-11-10', 81),
        ('2026-11-11_Production Summary.pdf', '2026-11-11', 35),
        ('2026-11-11_Production Todate.pdf', '2026-11-11', 81)]
    with sqlite3.connect(importer / 'bronze.db') as db:
        before = {t: db.execute(f'SELECT * FROM {t}').fetchall()
                  for t in ('archived_file', 'file_load', 'load_failure', 'production_todate_day')}
    assert cli.main(['import-pdf', str(PDF)]) == 0
    assert capsys.readouterr().out.count('skipped: already loaded') == 4
    with sqlite3.connect(importer / 'bronze.db') as db:
        assert {t: db.execute(f'SELECT * FROM {t}').fetchall() for t in before} == before
    # The nightly load never selects PDF archive rows.
    config = load_config()
    database = open_database(config.db_path)
    try:
        assert load_stage(config, database, Clock(config.timezone, lambda: NOW))
    finally:
        database.close()
    assert len(loads(importer)) == 8


def test_corrupt_pdf_is_archived_with_failure_and_others_load(importer, capsys):
    folder = importer / 'pdfs'
    shutil.copytree(PDF / '11_10_2026', folder / 'good')
    (folder / 'bad').mkdir()
    (folder / 'bad' / 'PRODUCTION SUMMARY.PDF').write_bytes(b'%PDF-1.4 not really a pdf')
    assert cli.main(['import-pdf', str(folder)]) == 1
    out = capsys.readouterr().out
    assert 'bad/PRODUCTION SUMMARY.PDF: failed LayoutError' in out
    with sqlite3.connect(importer / 'bronze.db') as db:
        # Printed date unreadable -> plant-local import date.
        assert db.execute("SELECT archive_name FROM archived_file a JOIN load_failure l "
                          "ON l.archived_file_id=a.id").fetchall() == [
                              ('2026-11-16_Production Summary.pdf',)]
    assert [row[0] for row in loads(importer)] == [
        '2026-11-10_Production Summary.pdf', '2026-11-10_Production Todate.pdf']
    assert (importer / 'archive' / '2026-11-16_Production Summary.pdf').read_bytes().startswith(b'%PDF')
    assert not list((importer / 'archive').glob('.*.partial'))


def test_archive_name_with_other_content_fails_without_rows(importer, capsys):
    folder = importer / 'pdfs'
    shutil.copytree(PDF / '11_10_2026', folder)
    (importer / 'archive' / '2026-11-10_Production Todate.pdf').write_bytes(b'different')
    assert cli.main(['import-pdf', str(folder)]) == 1
    assert 'production todate.pdf: failed ArchiveIntegrityError' in capsys.readouterr().out
    with sqlite3.connect(importer / 'bronze.db') as db:
        assert db.execute("SELECT COUNT(*) FROM archived_file WHERE original_name='Production Todate.pdf'"
                          ).fetchone() == (0,)
    assert (importer / 'archive' / '2026-11-10_Production Todate.pdf').read_bytes() == b'different'


def test_missing_folder_and_argument_rules(importer, capsys):
    assert cli.main(['import-pdf', str(importer / 'nowhere')]) == 2
    assert 'import-pdf: folder must exist and be readable' in capsys.readouterr().out
    assert not (importer / 'bronze.db').exists()
    with pytest.raises(SystemExit):
        cli.main(['import-pdf'])
    with pytest.raises(SystemExit):
        cli.main(['run', str(PDF)])


def test_lock_held_exits_3(importer):
    with run_lock(importer / 'bronze.db'):
        assert cli.main(['import-pdf', str(PDF)]) == 3
