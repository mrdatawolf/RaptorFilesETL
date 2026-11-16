# TASK-008: PDF backfill import command

Owner role: implementer
Assigned agent:
Proposed by: Claude (main session)
Proposed date: 2026-11-16
Approved by: Patrick
Approved date: 2026-11-16
Related contracts: CONTRACT-002, CONTRACT-003 (both need amendment, or a new CONTRACT-004)
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

None.

## Implementation handoff

Not started.

## Review

Not reviewed.
