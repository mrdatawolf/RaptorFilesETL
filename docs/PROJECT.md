# Project Definition

> Status: **Draft**, pending human review. Items under "Open questions" are not
> yet decided.

## Purpose

The Raptor sorter/trimmer system at Sequoia Forest Products (Arcata, CA) writes
daily production reports to an SMB share. The files are overwritten every day,
so the history is lost unless someone saves it. This project keeps a dated copy
of each day's reports and loads their contents into a SQLite "bronze" database
for later analysis.

## Users and stakeholders

- Owner and operator: the human project lead.
- Data source: Raptor Integration Inc. reporting (Crystal Reports exports).
- Consumers of the bronze data: to be defined.

## Desired outcomes

- Every daily report file is copied to an archive with the copy date in its
  filename, and the copy is byte-identical to the source.
- The data in each supported report is loaded into bronze with as little
  transformation as possible, and each row can be traced to its source file.
- Running the job again on the same file never creates duplicate data.

## Scope

### Included

- A copy at **23:00, Monday to Friday**, of the `.pdf` and `.xls` report files
  from the SMB share. Files are **copied**; the share is never modified. There
  is no production on weekends, so no weekend runs are scheduled.
- Weekdays with no production: the share still holds the previous run's files.
  The hash check finds them unchanged and skips them, so they are neither
  archived nor loaded again.
- An archive whose filenames carry the **copy date**. That date is used only
  for storage, never as a data value.
- Parsing the `.xls` version of each report into the bronze SQLite database.
- Tracking file hashes so that the same file is never loaded twice.

### Excluded

- Any change to files on the SMB share.
- Other file types on the share.
- Silver/gold layers: deduplicating across days, business modelling, reporting.
- Parsing the `.pdf` files. They are archived only, because each one duplicates
  its `.xls`.
- Thickness Breakdown data. The report is only a chart and has no useful data
  for this project. Its files are archived but not parsed.

## Source reports

Each report is exported in both formats with the same content. The `.xls` has
full precision and exact timestamps, so it is the parse source.

| Report | Contents | Bronze source |
|---|---|---|
| Downtime Summary | Per-alarm ID, description, occurrences, total/min/max duration | `.xls` |
| Production Summary | Header KPIs; volume by product, length and grade | `.xls` |
| Production ToDate | One row per production day (rolling multi-week history) | `.xls` |
| Thickness Breakdown | Chart only; the `.xls` contains no data cells | Not parsed (archive only) |

Each report header has Printed, Report Start, Report End and Recipe fields.
The report's own dates come from Report Start/End, not from the copy date.

## Constraints

- The source is an SMB share on a different machine and is read-only for this
  project. Working assumption for the path: `//test/files` (it must be
  configurable). The share holds only the current day's files, named exactly
  as in `Samples/`.
- The job must run on either Linux or Windows and is expected to run in a
  Docker container, deployed as a TrueNAS custom app.
- All configuration and secrets are read from **environment variables**:
  share location, SMB username and password, archive path, database path, and
  similar settings. Locally these come from a `.env` file, which is never
  committed. In Docker they are set in the TrueNAS custom app's environment
  settings. No settings or secrets are hard-coded or stored in the repository.
- The archive is written to a configurable folder, chosen at deployment.
  Archived files are kept **forever**.
- The copy runs at 23:00 **plant local time** (Pacific), hours after the last
  production run, so each file is a complete day. Containers default to UTC,
  so the time zone must be set explicitly.
- Source filenames are the same every day.
- If a run is delayed past midnight, the copy date shifts by a day. This is
  acceptable as long as the system is consistent: the copy date is always the
  date the copy actually ran.
- Production ToDate repeats weeks of history in every file. Bronze keeps these
  overlapping rows as they are; a later layer handles them.
- The project is built with Design by Contract: each stage has explicit
  preconditions, postconditions and invariants (see `docs/contracts/`).

## Domain language

- **Bronze**: stored data with minimal transformation. It keeps source
  values and adds only load metadata (source file, hash, load time).
- **Archive**: the dated copies of the original files.
- **Copy date**: the date the archive copy was made. Used in filenames only.
- **Report window**: the Report Start to Report End period inside a report.
- **BF**: board feet. **Lug fill**: % of lugs carrying a board.
  **Trimloss**: % of volume lost to trimming.

## Open questions

1. Archive filename format: proposed as `YYYY-MM-DD_<original name>`, for
   example `2026-11-10_Production Summary.xls`. To be fixed in CONTRACT-001.
