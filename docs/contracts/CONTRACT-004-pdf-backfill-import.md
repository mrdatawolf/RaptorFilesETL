# CONTRACT-004: PDF backfill import

Status: Approved
Approved by: Patrick
Approved date: 2026-11-16
Related tasks: TASK-008
Related ADRs: ADR-001, ADR-002

## Purpose

Load Production Summary and Production ToDate reports from their PDF exports
into the bronze database, for days that have no `.xls` load. PDFs are a
last-resort source. An operator runs the import by hand. The nightly `run`
never parses PDFs.

## Scope

### Included

- The `raptor-etl import-pdf <folder>` command.
- Finding, archiving, parsing and loading Production Summary and Production
  ToDate PDFs.
- The rule that skips a PDF when an `.xls` load exists for the same report
  and day.
- How PDF values (rounded numbers, dates without times) are stored.

### Excluded

- Any change to `run`, `schedule`, `check`, collect (CONTRACT-001) or the
  nightly load (CONTRACT-003).
- Downtime Summary PDFs. There is no sample to build or test a parser with.
- Thickness Breakdown, as with `.xls`.
- Removing or replacing PDF loads. PDFs are imported only for days whose
  `.xls` has already been run (TASK-008, decision 4), so an `.xls` arriving
  after its PDF is not handled.
- Schema changes. The bronze schema of CONTRACT-003 is used as is.

## Actors

- An operator, running the command by hand on the test box or with
  `docker exec`.

## Inputs and outputs

**Input:** a folder, given on the command line. It is searched recursively.
A file is a candidate when its name, ignoring case, is
`Production Summary.pdf` or `Production Todate.pdf`. All other files are
ignored. That includes Thickness Breakdown and Downtime Summary PDFs, which
are logged as `ignored: not supported`.

**Output:** for each candidate, at most one `archived_file` row, at most one
`file_load` with its report rows, or a `load_failure` row (CONTRACT-003
schema). A log line for each candidate, and an exit code.

### PDF value rules

These replace the CONTRACT-002 value rules for PDF input. Everything else in
CONTRACT-002 (the `ParsedReport` model, fields, labels, section and column
names, record order, nulls, "nothing invented") applies unchanged.

| Value | Rule | Example |
|---|---|---|
| Numbers | As shown, with thousands separators and `%` removed. They are rounded to the displayed precision, not the `.xls` precision. Percentages keep percent units, as in the `.xls`. | `1,845` → 1845; `0.09%` → 0.09; `2.87` → 2.87 |
| `printed_at` | Page-1 "Printed:" value, seconds `00` (as for `.xls`). | `Nov 9, 2026 3:40 pm` → `2026-11-09 15:40:00` |
| `report_start`, `report_end` | Shown to the minute, so seconds are `00`. | `Nov 9, 2026 5:00 am` → `2026-11-09 05:00:00` |
| ToDate `run_start` | The PDF shows the date only. Stored as `YYYY-MM-DD 00:00:00`. If a date repeats in one file, each later row with that date gets the next second, in the order the rows appear. **The time is invented and has no meaning.** | `16-Sep-2026`, `16-Sep-2026` → `2026-09-16 00:00:00`, `2026-09-16 00:00:01` |
| Durations | Text as shown. | `01:49:49` |
| Blank values | `null`. | |
| `page_count` | From "Page N of N". | |

A PDF-sourced load is identified by its `archived_file.original_name`
ending in `.pdf`. Anyone reading bronze data must treat those rows as
rounded, with `run_start` times that are not real.

## Preconditions

- Configuration is valid (same validation as `run`), including a writable
  archive. Otherwise: exit 2.
- The folder exists and is readable. Otherwise: exit 2, nothing written.
- The run lock is free. Otherwise: exit 3, nothing written.
- The database opens and its schema version is known or upgradable
  (CONTRACT-003). Otherwise: exit 2.
- No source precheck. The import never contacts the SMB share.

## Required behavior

Candidates are processed in path order. Each is independent: a failure in
one never stops the others. For each candidate:

1. **Identify.** Canonical name `Production Summary.pdf` or
   `Production Todate.pdf` (the share's spelling), and its report type.
   Calculate the file's SHA-256.
2. **Already handled?** If an `archived_file` exists with this canonical
   name and hash and it has a `file_load` → `skipped: already loaded`.
3. **Parse** the PDF (rules above and below).
4. **Skip rule.** If parsing succeeded and a `file_load` exists for the same
   `report_type` whose `archived_file.original_name` ends in `.xls` and
   whose `printed_at` date equals this PDF's `printed_at` date →
   `skipped: xls already loaded for YYYY-MM-DD`. Nothing is archived.
5. **Archive.** Reuse the existing `archived_file` row if this name and hash
   is already archived. Otherwise copy the file into the archive as
   `{copy_date}_{canonical name}`, where `copy_date` is the `printed_at`
   date. If the parse failed before `printed_at` could be read, use the
   plant-local import date instead. Copy to a partial file, verify the hash,
   then rename, as in CONTRACT-001. Never replace an existing archive file:
   if the name exists with different content, the candidate fails with
   `ArchiveIntegrityError`. Insert `archived_file` with `archived_at` set to
   the import time.
6. **Load.** If the parse succeeded: in one transaction insert `file_load`,
   the header-level row, and all report rows (CONTRACT-003 step 2.4).
   If the parse or the transaction failed: record a `load_failure` with the
   error type and message.
7. **Log** one line per candidate: its path relative to the folder, then
   `loaded record_count=N archive=<archive_name>`, `skipped: <reason>`,
   `ignored: not supported` or `failed <ErrorType>: <message>`.

A file that failed is retried by running the import again on the same
folder. Step 2 sees no `file_load`, so it is parsed and loaded again.

### Parsing

- **Find values by label, not position.** Words are grouped into lines by
  their vertical position. Values are matched to labels and column headers
  by horizontal position. Fixed coordinates must not be used.
- **Preconditions** as in CONTRACT-002: the page-1 title matches the type
  exactly, the header labels are present, column and section headers come
  before their data, and "Page N of N" is present. Otherwise: `LayoutError`.
- **Page furniture is skipped**: company and address blocks, repeated
  titles, later-page "Printed:" lines, and "Page N of N".
- **Production Summary:** each item is a block of Pieces, Volume and % vol
  lines under its section. Sections continue across pages. In the samples,
  Product Summary continues on page 2 with only a "Total" column header.
- **Record order:** page by page, top to bottom, then left to right, as in
  CONTRACT-002.

### Reconciliation (PDF)

Failures raise `ReconciliationError`. No partial result is returned.

- Empty reports follow CONTRACT-002 "Empty reports": Production Summary
  placeholder items are not returned, and a ToDate with zero rows is valid.
  Any other result with no records fails.
- **Production Summary:** each section has exactly one Total row. In each
  section, non-Total `pieces` add up to the Total exactly. All four Total
  `pieces` are equal. Non-Total `volume` values add up to the Total
  `volume` within 0.5 × (number of non-Total rows + 1), which allows for
  rounding.
- **Production ToDate:** every record has a non-null `run_start`, and no two
  records share a `run_start` after the repeated-date rule.

## Postconditions and invariants

- CONTRACT-003's invariants hold: loaded once, all or nothing, count
  matches, lineage, append-only.
- No PDF is loaded for a report type and day that already had an `.xls`
  load when the import ran.
- Running the import again on the same folder loads nothing new.
- The import never writes to the source folder.

## Failure behavior

| Situation | Behavior |
|---|---|
| Parse error | Archived, `load_failure` recorded, other files continue, exit 1. |
| Archive name exists with different content | `failed ArchiveIntegrityError`, nothing written for that file, exit 1. |
| File unreadable | `failed`, nothing written for that file, exit 1. |
| Database write error | Rolled back, `load_failure` recorded if possible, exit 1. |
| Configuration, folder or database invalid | Exit 2 before any file. |
| Lock held | Exit 3. |

## Interfaces

- `raptor-etl import-pdf <folder>`.
- Exit codes: `0` every candidate loaded, skipped or ignored; `1` at least
  one candidate failed; `2` invalid configuration, folder or database;
  `3` another run in progress.
- Parser: `parse_pdf_report(path, report_type) -> ParsedReport`. Pure: no
  database, network or file writes.
- Reads `RAPTOR_ARCHIVE_DIR` and `RAPTOR_DB_PATH`. The source settings are
  validated but not used.

## Related amendments (applied once this contract is approved)

- PROJECT.md: PDF parsing moves from Excluded to Included, as a manual,
  last-resort backfill (CONTRACT-004).
- CONTRACT-002: "`.pdf` files are never parsed" becomes "never parsed by
  this contract; see CONTRACT-004".
- CONTRACT-003: "PDFs are never loaded" becomes "never loaded by `run`;
  see CONTRACT-004".

## Validation requirements

Automated, using `Samples/PDF` and `Samples/XLS`. They skip with a clear
message when `Samples/` is absent.

- Both PDF report types parse for all four sample days (11/09, 11/10, 11/11,
  11/13).
- **Cross-check** on 11/09 and 11/11 against the `.xls` parse:
  - `printed_at`, `recipe` and `page_count` are equal. `report_start` and
    `report_end` equal the `.xls` values with seconds set to `00`.
  - Production Summary: the same (`section`, `label`, `is_total`) records
    in the same order. `pieces` are equal. Every other number is within half
    a unit of the PDF's last displayed digit of the `.xls` value.
  - ToDate: the same number of rows. Each `run_start` date equals the
    `.xls` date, row by row. Numbers match within half a unit of the
    displayed digit. Durations and `total_stops` are equal. Blank cells
    are `null` in both.
- Repeated date: the two 16-Sep-2026 rows are stored as `00:00:00` and
  `00:00:01`.
- End to end: with 11/09 and 11/11 `.xls` loaded first, importing
  `Samples/PDF` loads 11/10 and 11/13 (Summary and ToDate), skips 11/09 and
  11/11 with the `.xls` reason, ignores Thickness Breakdown, and exits 0.
- Running again loads nothing new and exits 0.
- A corrupt PDF: archived, `load_failure` recorded, other files load,
  exit 1.
- `run`, `schedule` and `check` tests pass unchanged. The nightly load never
  selects PDF archive rows.

## Amendments

- 2026-11-16 (proposed, TASK-010, awaiting approval): "At least one data
  record" is replaced by the CONTRACT-002 "Empty reports" rules. The
  2026-11-13 Production Summary PDF gives the four Total rows only, the same
  as its `.xls`.

## Open questions

None.
