# CONTRACT-002: Parse Raptor `.xls` reports

Status: Approved
Approved by: Patrick
Approved date: 2026-11-11
Related tasks: TASK-001
Related ADRs: ADR-001

## Purpose

Turn one archived Raptor `.xls` report into structured records that faithfully
represent what the report contains, or reject it with a clear reason. Parsing
is a pure step: it reads a file and returns data, with no other side effects.

## Scope

### Included

- Three report types, read from `.xls` only: **Downtime Summary**,
  **Production Summary** and **Production ToDate**.
- Report header metadata.
- Checking the layout before extracting data, and checking the report's own
  totals after extracting.

### Excluded

- `.pdf` files and Thickness Breakdown. They are never parsed.
- Deduplicating, aggregating, renaming business terms, or converting units.
- Writing to the database (CONTRACT-003).

## Inputs and outputs

**Input:** an archived `.xls` file and its expected report type, taken from
the original filename (see CONTRACT-001).

**Output:** a `ParsedReport` holding the report type, the header, the page
count and the type-specific records below. Value rules that apply to every
type:

- **Numbers** are kept at the full precision stored in the cell, with no
  rounding. Counts are integers; measures are reals.
- **Timestamps** are plant-local text `YYYY-MM-DD HH:MM:SS`, with no time
  zone conversion and no offset. Excel serial dates are converted to the
  nearest second (for example `46335.208344907405` →
  `2026-11-09 05:00:01`).
- **Durations** are kept as the text the report shows, `H…H:MM:SS` (hours may
  be more than 2 digits).
- **Labels** (alarm descriptions, product, length, grade and width names) are
  kept exactly as shown, with only leading and trailing whitespace removed.
- **Empty value cells** become `null`. This is real: the 2026-09-23 row of
  Production ToDate in `Samples/` has a blank Slow %.
- **Record order** is kept, as a 1-based `row_order` in the order the records
  appear in the report (page by page, top to bottom).

### Header (all types)

| Field | Source | Notes |
|---|---|---|
| `printed_at` | "Printed:" on page 1 | Timestamp. Page 1 shows minutes only (`Nov 9, 2026 3:40 pm`), so seconds are `00`. |
| `report_start` | "Report Start:" | Timestamp. `null` for Production ToDate, which has no such field. |
| `report_end` | "Report End:" | Timestamp. `null` for Production ToDate. |
| `recipe` | "Recipe:" | Text as shown (e.g. `<ALL>`). `null` for Production ToDate. |
| `page_count` | "Page N of N" | Integer, as reported. The `.xls` export shows this marker only once, after the last data row. |

### Downtime Summary

`alarms`: one record per alarm block.

| Field | Type |
|---|---|
| `alarm_id` | integer |
| `description` | text |
| `occurrences` | integer |
| `total_duration` | duration |
| `min_duration` | duration |
| `max_duration` | duration |

`grand_total`: `occurrences` (integer), `total_duration` (duration).

### Production Summary

`kpis` (one record):

| Field | Source label |
|---|---|
| `avg_bf_per_piece` | Average BF Per Piece |
| `lug_fill` | Lug Fill |
| `trimloss` | Trimloss |
| `trimmer_speed_slow_pct` | Trimmer Speed – Slow |
| `trimmer_speed_medium_pct` | Trimmer Speed – Medium |
| `trimmer_speed_fast_pct` | Trimmer Speed – Fast |

`breakdown`: one record per item in each of the four sections, **including**
each section's Total row.

| Field | Type |
|---|---|
| `section` | `product`, `length`, `grade` or `width` |
| `label` | text, e.g. `2x4 .HQ Bronze`, `4'`, `Gold`, `4.00`, `Total` |
| `is_total` | boolean: true only for the section's Total row |
| `pieces` | integer |
| `volume` | real |
| `pct_volume` | real (the "% vol" value) |

### Production ToDate

`days`: one record per data row.

| Field | Source column | Type |
|---|---|---|
| `run_start` | Date | timestamp. Not unique per date: `Samples/` has two rows on 2026-09-16 (05:00:02 and 15:40:02). |
| `fast_pct` | Fast % | real |
| `medium_pct` | Medium % | real |
| `slow_pct` | Slow % | real |
| `lug_fill` | Lug Fill | real |
| `bf_per_piece` | BF Per Piece | real |
| `trimloss` | Trimloss | real |
| `total_stops` | Total Stops | integer |
| `downtime` | Downtime | duration |
| `volume` | Volume | real |

## Preconditions

Each of these is checked before any record is returned. If one fails, the
parser raises `LayoutError`, naming the file and the check that failed.

- The file opens as an `.xls` (BIFF) workbook.
- The report title on page 1 matches the expected type exactly:
  `Downtime Summary Report`, `Production Summary Report` or
  `Production ToDate Report`.
- Every header label the type needs is present: "Printed:", plus
  "Report Start:", "Report End:" and "Recipe:" for the two summary reports.
- The column or section headers the type needs are present before the data
  they label:
  - Downtime: `Alarm ID`, `Alarm Description:` and `Details (hh:mm:ss)`
    appear before the first alarm record.
  - Production Summary: the KPI labels appear before the KPI values, and each
    of the four section titles (`Product Summary`, `Length Summary`,
    `Grade Summary`, `Width Summary`) appears before **that section's** first
    record. The titles do not all have to come before the first record. In
    `Samples/`, `Width Summary` first appears on row 49, after the other
    sections' records start on row 28.
  - ToDate: all 10 column labels appear before the first data row.
- A "Page N of N" marker is present.

## Required behavior

- **Find values by label, not by position.** Values are matched to the
  nearest header label or column. Whenever the headers repeat, the parser
  realigns to them. Column positions differ between pages; in `Samples/`,
  ToDate's Volume moves from column 29 to 28 after the repeated header.
  Fixed cell coordinates must not be used.
- **Repeated page furniture is skipped.** Company and address blocks,
  repeated titles, "Printed:" lines on later pages and the "Page N of N"
  line never become records.
- **The whole sheet is read**, through the last data row.
- **Nothing is invented.** Every record and field value comes from a cell in
  the file. Missing values are `null`, never defaults.

## Postconditions and invariants

If a check fails, the parser raises `ReconciliationError` (a kind of
`LayoutError`), naming the check and the expected and actual values. No
partial result is returned.

- **All types:** the result has at least one data record.
- **Downtime Summary:**
  - Sum of `alarms.occurrences` = `grand_total.occurrences`.
  - Sum of `alarms.total_duration` = `grand_total.total_duration`, to the
    second.
  - For each alarm: `min_duration` ≤ `max_duration` ≤ `total_duration`.
- **Production Summary:**
  - Each section has exactly one Total row.
  - In each section, the non-Total `pieces` add up to the Total `pieces`
    exactly.
  - All four Total `pieces` values are equal.
  - The non-Total `volume` values add up to the Total `volume` within 0.01 %.
- **Production ToDate:** every record has a non-null `run_start`. No two
  records share the same `run_start`.

These hold for every file in `Samples/` (for example, Downtime is 380
occurrences, 01:49:49; Production Summary is 58,004 pieces in all four
sections).

## Failure behavior

- `LayoutError` / `ReconciliationError`: the file is rejected whole. The
  caller (CONTRACT-003) records the failure, loads nothing from that file and
  keeps processing other files.
- If the expected type isn't one of the three, the parser is never called.
  The load stage excludes PDFs and Thickness Breakdown before parsing.

## Interfaces

`parse_report(path, report_type) -> ParsedReport`. Pure: no database, network
or file writes.

## Validation requirements

- Each of the three `Samples/` `.xls` files parses, and the result matches
  hand-checked values: the first and last records, the counts (Downtime: 20
  alarms; ToDate: 81 rows), the 2026-09-23 null `slow_pct`, both 2026-09-16
  rows, and the header timestamps.
- Every invariant holds for `Samples/`, and each one has a test with a
  deliberately altered fixture that triggers it.
- Passing the wrong type (for example a Downtime file declared as Production
  Summary) raises `LayoutError`.
- A non-`.xls` file raises `LayoutError`.

## Amendments

- 2026-11-11 (approved by Patrick): the Production Summary header
  precondition changed from "all section titles before the first data
  record" to "each section title before that section's first record". The
  original wording rejected the sample file. Found during TASK-003.

## Open questions

None.
