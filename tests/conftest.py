import os
import pytest


@pytest.fixture
def configured(tmp_path, monkeypatch):
    for key in os.environ:
        if key.startswith('RAPTOR_'):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    for key, value in {
        'SOURCE_PATH': str(tmp_path / 'source'),
        'ARCHIVE_DIR': str(tmp_path),
        'DB_PATH': str(tmp_path / 'bronze.db'),
    }.items():
        monkeypatch.setenv('RAPTOR_' + key, value)
    return tmp_path


# Real sample reports (gitignored, local only). The default day, 11_09_2026, is
# the original fixture set; its values are what the tests assert.
SAMPLES = __import__('pathlib').Path(__file__).resolve().parents[1] / 'Samples'
# No Downtime Summary PDF sample exists. Collect copies and hashes PDFs but never
# reads them, so a stand-in is enough for share-shaped tests.
DOWNTIME_PDF_STAND_IN = b'%PDF-1.4\n% test stand-in for Downtime Summary.pdf\n'


@pytest.fixture
def make_share():
    """Return a builder that writes the 8 CONTRACT-001 share files into a folder.

    The .xls files come from REFERENCE_XLS. PDFs come from REFERENCE_PDF, whose
    hand-downloaded names are lowercase, renamed to the share's spelling.
    """
    from raptor_etl.collect import EXPECTED_FILES
    import shutil

    def build(target, xls_day='11_09_2026', pdf_day='11_09_2026'):
        target.mkdir(parents=True, exist_ok=True)
        for name in EXPECTED_FILES:
            if name.endswith('.xls'):
                source = SAMPLES / 'XLS' / xls_day / name
            else:
                source = SAMPLES / 'PDF' / pdf_day / name.lower()
            if source.is_file():
                shutil.copyfile(source, target / name)
            elif name == 'Downtime Summary.pdf':
                (target / name).write_bytes(DOWNTIME_PDF_STAND_IN)
            else:
                pytest.skip(f'Sample file absent: {source}')
        return target
    return build
