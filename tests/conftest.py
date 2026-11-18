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
# Files the real share also holds that the nightly run must ignore (CONTRACT-001).
NON_DATA_FILES = ('Downtime Summary.pdf', 'Production Summary.pdf', 'Production Todate.pdf',
                  'Thickness Breakdown.pdf', 'Thickness Breakdown.xls')


@pytest.fixture
def make_share():
    """Return a builder that writes the 3 CONTRACT-001 share files into a folder.

    The .xls files come from Samples/XLS/<xls_day>. With non_data=True it also
    writes the share's PDF and Thickness Breakdown files as small stand-ins;
    collect must ignore them, so their content never matters.
    """
    from raptor_etl.collect import EXPECTED_FILES
    import shutil

    def build(target, xls_day='11_09_2026', non_data=False):
        target.mkdir(parents=True, exist_ok=True)
        for name in EXPECTED_FILES:
            source = SAMPLES / 'XLS' / xls_day / name
            if not source.is_file():
                pytest.skip(f'Sample file absent: {source}')
            shutil.copyfile(source, target / name)
        if non_data:
            for name in NON_DATA_FILES:
                (target / name).write_bytes(f'stand-in for {name}\n'.encode())
        return target
    return build
