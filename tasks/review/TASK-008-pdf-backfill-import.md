# TASK-008: PDF backfill import command

Owner role: implementer
Assigned agent: Claude (main session)
Proposed by: Claude (main session)
Proposed date: 2026-11-16
Approved by: Patrick
Approved date: 2026-11-16
Related contracts: CONTRACT-004 (new); CONTRACT-002, CONTRACT-003 (small amendments)
Related ADRs: ADR-001; ADR-002 (new, pdfplumber dependency, to be written)
Dependencies: TASK-005

## Desired outcome

Operators can load reports from older PDFs into the bronze database with
`raptor-etl import-pdf <folder>`. A PDF is loaded only when no `.xls` load
already exists for the same report type and day. This gives the database
real test data for days that have no `.xls`, and a manual second source if
the `.xls` files are ever unavailable. The nightly `run` and `schedule`
behavior does not change.

## Context

Decisions made by Patrick on 2026-11-16:

- Backfill command only. No PDF fallback in the nightly run.
- A PDF is skipped when an `.xls` load already exists for that report and day.
- PDF library: pdfplumber (pure Python, works on Windows and in the Docker
  image, and gives word positions so values can be found by label and column).

PROJECT.md currently excludes PDF parsing ("archived only, because each one
duplicates its `.xls`"), and CONTRACT-002/003 say PDFs are never parsed. This
task changes that scope, so PROJECT.md and the contracts must be amended first.

Samples (local only, gitignored):

| Day | PDF | XLS |
|---|---|---|
| 11/09 | Production Summary, Production Todate, Thickness | all 4 |
| 11/10 | Production Summary, Production Todate, Thickness | none |
| 11/11 | Production Summary, Production Todate, Thickness | all 4 |
| 11/13 | Production Summary, Production Todate, Thickness | none |

The sample PDFs are Crystal Reports output with a real text layer, so no OCR
is needed. There are no Downtime Summary PDFs in the samples. File names are
lowercase (`production summary.pdf`), unlike the share's names.

Findings from comparing 11/09 PDF and XLS:

- PDF numbers are rounded to the displayed precision. For example, volume is
  `149` in the PDF and `149.333…` in the XLS, BF per piece is `2.87` vs
  `2.8713…`, and % vol is `0.09%` vs `0.0897`.
- Report Start/End have minute precision in the PDF (`5:00 am`) and seconds
  in the XLS (`05:00:01`).
- ToDate rows show only the date (`9-Nov-2026`). The XLS `run_start` includes
  the time (`05:00:01`).
- ToDate row counts match (81 rows on 11/09).

## Scope

### Included

- ADR-002: add pdfplumber as a runtime dependency.
- Contract amendment (CONTRACT-002/003 or a new CONTRACT-004) defining PDF
  parsing, the import command, skip rules and exit codes. PROJECT.md scope
  updated to match.
- PDF parsers for Production Summary and Production ToDate. They produce the
  existing `ParsedReport` models and find values by label and column, never by
  fixed position. The same reconciliation checks as the XLS parser run, with
  tolerances suited to rounded values.
- `raptor-etl import-pdf <folder>`: scans the folder recursively and matches
  report names case-insensitively. For each PDF: archive it with a hash, as
  collect does (reusing an existing `archived_file` row when the same name and
  hash is already archived). Skip it if an `.xls` load exists for the same
  report type and day. Otherwise parse and load it with the existing load
  transaction and `load_failure` recording. Takes the run lock.
- Thickness Breakdown PDFs are ignored, as with `.xls`.
- Format is identified by the archived file name (`.pdf`), so no schema
  migration is needed.
- DEVELOPMENT.md: command, exit codes, how to run the backfill on the test box.

### Excluded

- Any change to `run`, `schedule`, `check` or collect.
- Automatic PDF fallback when an `.xls` fails.
- Downtime Summary PDFs. There are no samples, so a parser cannot be built
  or validated. This can be added later when a sample exists.
- Removing or replacing PDF loads when an `.xls` for that day arrives later.
  Bronze stays append-only, and the silver layer chooses between them.

## Decisions (answered by Patrick, 2026-11-16)

1. **ToDate `run_start` from a PDF is date-only.** Options: store
   `YYYY-MM-DD 00:00:00` (consistent format but an invented time), or store
   `YYYY-MM-DD` (honest, but a different format in the same column).
   Recommendation: `YYYY-MM-DD`, and record the difference in the contract.
  - `YYYY-MM-DD 00:00:00` the other programmers will understand that its invented.
  - Repeated dates (Patrick, 2026-11-16): every sample ToDate PDF has two
    16-Sep-2026 rows. A later row with the same date gets the next second
    (`00:00:01`, …), so the unique (load, `run_start`) rule still holds.
    No schema change.
2. **Archive `copy_date` for backfilled PDFs.** Options: the report's printed
   date, or the folder name (`11_09_2026`). Recommendation: the printed date,
   so the importer does not depend on how folders are named.
  - printed date
3. **What counts as "the same day" for the skip rule.** Recommendation: same
   `report_type` and same date of `printed_at`.
  - as you suggested report_type and printed_at
4. **An `.xls` load arriving after its PDF was already loaded.** Recommendation:
   the nightly run is unchanged and loads it anyway, so both exist. Bronze stays
   append-only. The alternative is changing the nightly run, which is out of
   scope.
  - Not a concern (Patrick, 2026-11-16). PDFs are last-resort files and are
    never imported for a day before that day's `.xls` has been run, so no
    handling is needed.


## Plan

1. Write ADR-002 and the contract amendment. Patrick approves both.
2. Add the pdfplumber dependency and PDF parsers, with tests against `Samples/PDF`.
3. Add the `import-pdf` command, with archiving, skip rule, load and logging.
4. Update documentation.

## Acceptance criteria

- [ ] ADR-002 and the contract amendment are approved before code changes.
- [ ] On 11/09 and 11/11, PDF-parsed values equal the XLS-parsed values
      rounded to the PDF's displayed precision, for every Production Summary
      KPI and breakdown row and every ToDate row.
- [ ] Importing `Samples/PDF` into a database that has the 11/09 and 11/11
      `.xls` loads loads only 11/10 and 11/13, and logs the other days as
      skipped with the reason.
- [ ] Re-running the import loads nothing new and exits 0.
- [ ] A malformed PDF records a `load_failure` row, other files still load,
      and the exit code is 1.
- [ ] `run`, `schedule` and `check` behavior and tests are unchanged.
- [ ] Works on Windows (paths, lock) and in the Docker image.

## Validation requirements

- Parser tests for both report types against all four sample days. They skip
  with a clear message when `Samples/` is absent.
- XLS/PDF cross-check tests for 11/09 and 11/11.
- End-to-end import tests: the skip rule, idempotence, failure recording.
- Full existing test suite passes.

## Risks and assumptions

- Crystal Reports layout may vary, for example with long product labels or
  page breaks inside a section. Label- and column-based parsing with
  reconciliation checks limits the risk, but only four sample days exist.
- PDF values are lower-precision than XLS. Anyone using PDF-sourced rows
  must know this. The contract states it.
- pdfplumber pulls in pdfminer.six and Pillow (larger Docker image).

## Blocker

**Existing tests broken by the new `Samples/` layout (not caused by this
task).** 28 tests in `test_collect.py`, `test_load.py`, `test_load_e2e.py`
and `test_check.py` expect the old flat `Samples/` (the 8 share files at the
top level, including `Downtime Summary.pdf`). Needs Patrick: restore the
original flat set alongside `PDF/` and `XLS/`, or approve a task to repoint
those tests. Until then the full suite cannot pass.

## Implementation handoff

Task: TASK-008
Implementer: Claude (main session)
Date: 2026-11-16

### Changes made

- `src/raptor_etl/parse/pdf.py` (new): `parse_pdf_report(path, report_type)`
  for Production Summary and ToDate, using pdfplumber word positions.
  Summary values are matched to their section's Total column, item labels
  to the area left of the Pieces label (including labels that wrap onto the
  next lines, e.g. `No Data`), and KPIs to the value below each label. ToDate
  values go to the nearest column label by right edge. Repeated dates get
  the next second. `pdf_printed_at()` reads the printed date of a PDF that
  failed to parse, for its archive name.
- `src/raptor_etl/importpdf.py` (new): `import_pdfs()`, covering candidate
  discovery, the already-loaded and `.xls` skip rules, verified archive copy,
  `archived_file`, load through the existing `_insert_report`, and
  `load_failure`.
- `src/raptor_etl/cli.py`: `import-pdf <folder>` command. No source
  precheck. The folder is checked before the lock.
- `src/raptor_etl/parse/__init__.py`: `validate()` takes the volume
  tolerance as a parameter. The `.xls` default and its message are unchanged.
- `pyproject.toml`: `pdfplumber>=0.11,<0.12`. The Dockerfile needs no change.
- `tests/test_import_pdf.py` (new): 20 tests.

### Validation performed

- `pytest tests/test_import_pdf.py`: 20 passed.
- Full suite: 319 passed, 28 failed, 7 skipped. The 28 failures are
  identical with and without this change (compared by stashing it). They are
  caused by the reorganised `Samples/` folder (see Blocker below), not by
  this task.
- Manual end-to-end run against a scratch database, with `.xls` loaded for
  11/09 and 11/13 (log output matched the test).

### Acceptance criteria evidence

- ADR-002 and CONTRACT-004 were approved and committed (2e1990a) before code.
- Cross-check: `test_summary_cross_check` and `test_todate_cross_check`
  found zero mismatches, with identical record order (see deviation 1 for
  which days).
- Skip rule: `test_import_skips_xls_days_and_is_idempotent`.
- Re-run loads nothing and exits 0: same test. Table contents are compared
  before and after.
- Malformed PDF → `load_failure`, others load, exit 1:
  `test_corrupt_pdf_is_archived_with_failure_and_others_load`.
- `run`/`schedule`/`check` unchanged: no code changes there. The same
  failure set before and after. The nightly `load_stage` selects no PDF rows
  (asserted).
- Windows: uses `pathlib` only and the existing lock. Not run on Windows yet.

### Assumptions and deviations

1. **Sample days differ from CONTRACT-004's validation wording.**
   `Samples/XLS/11_11_2026` holds reports printed **2026-11-13**, not 11/11.
   The true same-day pairs are PDF 11/09 ↔ XLS 11/09 and PDF 11/13 ↔ XLS
   folder `11_11_2026`. The tests use those pairs. The end-to-end import
   therefore loads 11/10 and 11/11 and skips 11/09 and 11/13. The contract's
   behavior is unchanged, but its "Validation requirements" names the wrong
   days and needs Patrick's correction.
2. Any other `.pdf` in the folder is logged as `ignored: not supported`.
   Non-PDF files are ignored silently.
3. An unreadable PDF (e.g. a corrupt file) is a `LayoutError`
   ("cannot read PDF"), so it is archived and recorded as a parse failure.

### Unresolved risks

- Only four sample days exist. Untested layouts (page breaks inside the
  Length/Grade/Width sections, very long labels) would fail with a
  `LayoutError` rather than load wrong data.
- Found but out of scope: `Samples/XLS/11_11_2026/Downtime Summary.xls` (the
  2026-11-13 empty day) fails the existing `.xls` parser with "at least one
  data record". The nightly run would record a `load_failure` for such days
  and retry it every night.

### Documentation updated

DEVELOPMENT.md (stack, commands, PDF backfill section), PROJECT.md scope,
CONTRACT-002 and CONTRACT-003 (the amendments listed in CONTRACT-004).

## Review

Not reviewed.
