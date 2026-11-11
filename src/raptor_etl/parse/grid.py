"""A cell grid retaining BIFF cell types, also constructible without files."""
from dataclasses import dataclass
from pathlib import Path

import xlrd
from icontract import ensure

from ..errors import LayoutError


@dataclass(frozen=True)
class Cell:
    value: str | float | None = None
    ctype: int = xlrd.XL_CELL_EMPTY

    @property
    def text(self) -> str:
        return self.value.strip() if isinstance(self.value, str) else ''

    @property
    def empty(self) -> bool:
        return self.value is None or self.value == ''


@dataclass(frozen=True)
class Grid:
    rows: tuple[tuple[Cell, ...], ...]
    datemode: int = 0

    def cell(self, row: int, col: int) -> Cell:
        if 0 <= row < len(self.rows) and 0 <= col < len(self.rows[row]):
            return self.rows[row][col]
        return Cell()

    def populated(self, row: int):
        return [(col, cell) for col, cell in enumerate(self.rows[row]) if not cell.empty]


@ensure(lambda result: isinstance(result, Grid), enabled=True)
def read_grid(path: Path) -> Grid:
    if path.suffix.lower() != '.xls':
        raise LayoutError(f'{path}: expected a BIFF .xls workbook')
    try:
        with path.open('rb') as handle:
            contents = handle.read()
        book = xlrd.open_workbook(file_contents=contents, on_demand=True)
        try:
            if not book.biff_version:
                raise ValueError('not BIFF')
            sheet = book.sheet_by_index(0)
            return Grid(tuple(tuple(Cell(cell.value, cell.ctype) for cell in sheet.row(row))
                              for row in range(sheet.nrows)), book.datemode)
        finally:
            book.release_resources()
    except Exception as error:
        # Corrupt BIFF/OLE inputs may also raise struct/compound-document errors.
        raise LayoutError(f'{path}: cannot open BIFF .xls workbook ({type(error).__name__})') from None
