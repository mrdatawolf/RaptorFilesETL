# ADR-002: PDF parsing library

Status: Approved
Date: 2026-11-16
Decision owners: Patrick
Related tasks and contracts: TASK-008, CONTRACT-004

## Context

TASK-008 adds `raptor-etl import-pdf`, a last-resort command that loads
Production Summary and Production ToDate reports from their PDF exports when
the `.xls` for that day is not available. ADR-001 lists the approved runtime
dependencies, and none of them reads PDFs.

Facts from `Samples/PDF` that affect the choice:

- The PDFs are produced by Crystal Reports ("Powered By Crystal") and have a
  real text layer. No OCR is needed.
- Layouts are multi-column. Production Summary prints the Product, Length,
  Grade and Width sections side by side, each item as a three-line block
  (Pieces, Volume, % vol). Matching a value to its label and column needs the
  position of each word, not just the text in reading order.
- Later pages repeat a short header ("Production Summary Report",
  "Printed: November 09, 2026 3:40:06PM") and end with "Page N of N".

The library must run on the Windows test box and in the Python 3.12 slim
Docker image without system packages.

## Decision

Use **pdfplumber** to read PDFs.

- Pure Python, built on pdfminer.six. Installs from wheels on Windows and
  Linux. No system libraries are needed.
- `page.extract_words()` returns each word with its x/y coordinates. The
  parser groups words into lines and matches values to the nearest label
  and column header, which keeps the "find by label, never by fixed
  position" rule from CONTRACT-002.
- It is used read-only. Only the import command imports it, so `run`,
  `schedule` and `check` do not load it.

Pin a compatible range in `pyproject.toml` (`pdfplumber>=0.11,<0.12`), as
for xlrd.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| pypdf | Extracts plain text only. Matching columns would depend on spacing, which is fragile in multi-column layouts. |
| pdfminer.six directly | Works, but its layout API is low-level. pdfplumber gives the same data in a simpler form. |
| PyMuPDF (fitz) | Fast and gives positions, but AGPL licensed and ships a large native library. |
| poppler `pdftotext` | Not available on Windows by default. Would need a system package in the image and calling a subprocess. |
| OCR | Not needed, because the PDFs have a text layer. |

## Consequences

### Benefits

- A second source for Production Summary and ToDate data when the `.xls`
  files are unavailable.
- Same parsing approach as the `.xls` parser (find by label, reconcile
  totals), so the two parsers can be cross-checked on days that have both.

### Costs and risks

- Adds pdfplumber, pdfminer.six, Pillow, pypdfium2 and charset-normalizer to
  the image, about 15–20 MB.
- PDF values are rounded to the displayed precision, and ToDate dates have no
  time. CONTRACT-004 defines how this is stored.
- Crystal Reports layout changes would need parser changes, as with `.xls`.

## Follow-up work

- CONTRACT-004 defines the import command's behavior.
- Update DEVELOPMENT.md's stack table after approval.
