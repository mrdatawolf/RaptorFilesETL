# TASK-010: Reports with no data are valid

Owner role: implementer
Assigned agent: Claude (main session)
Proposed by: Claude (main session)
Proposed date: 2026-11-16
Approved by: Patrick
Approved date: 2026-11-16
Related contracts: CONTRACT-002, CONTRACT-003, CONTRACT-004 (all need amendment)
Related ADRs: ADR-001
Dependencies: TASK-009 (a passing suite to build on)

## Desired outcome

A report from a day with no production loads successfully as an empty
report. It is not rejected as a layout or reconciliation failure. Bronze
then shows, for that day, that the report was produced and had nothing in
it, which is a true fact about the plant.

## Context

CONTRACT-002 requires "at least one data record" for every report type, and
CONTRACT-004 repeats the rule for PDFs. This assumption is wrong: Raptor
produces real reports for days with no production. The samples include one,
printed 2026-11-13 (`Samples/XLS/11_11_2026` and `Samples/PDF/11_13_2026`).

What an empty day looks like in the samples:

| Report | Empty-day content | Today |
|---|---|---|
| Downtime Summary (`.xls`) | Headers, then one placeholder line: `No Downtimes`, no Alarm ID, `Occurrences: 0`, no durations. Grand Total: 0 occurrences, total duration **blank**. | **Fails** with "at least one data record". Would fail nightly and be retried every night. |
| Production Summary (`.xls` and PDF) | Each section has a placeholder item (`No Data` for Product, Length and Grade; `0.00` for Width) with 0 pieces, plus a Total of 0. KPIs 0.00 / 0 / 0.1, with blank trimmer speeds. | Loads, with the placeholders stored as if they were real items. |
| Production ToDate | Still lists the earlier days (80 rows). | Loads. A ToDate with no rows at all hasn't been seen, but the same rule should cover it. |

The production database has not been deployed yet, so no stored data needs
correcting.

## Scope

### Included

- Contract amendments: remove "at least one data record" from CONTRACT-002
  and CONTRACT-004, and define what an empty report is for each type and how
  it is stored (CONTRACT-003 `record_count` 0 and header-level rows).
- Downtime Summary: recognise the `No Downtimes` placeholder, then return
  zero alarms and a grand total with 0 occurrences and a null total
  duration. Reconciliation: with zero alarms, the grand total must be 0
  occurrences and a null or `00:00:00` duration.
- Production Summary: handling of placeholder items, per decision 1.
- Production ToDate: zero rows is valid when the column headers are present.
- The same rules in the PDF parser (TASK-008) for Production Summary and
  ToDate.
- Tests using the real empty-day samples.

### Excluded

- Downtime Summary PDFs (still unsupported, CONTRACT-004).
- Any change to collect, the schedule or the "unchanged file is skipped" rule.

## Open decisions (need Patrick before approval)

1. **Production Summary placeholder items.** On an empty day, each section
   shows a fake item (`No Data`, or `0.00` for Width) with 0 pieces.
   - **A. Keep them as shown** (current behavior). Bronze stays "as printed",
     but `No Data` will look like a product name to anyone querying bronze.
   - **B. Drop them** and keep only the Total rows (0 pieces). A section's
     items are then empty, like Downtime's alarms. The parser needs a precise
     rule, e.g. "the section's only item, with 0 pieces, 0 volume and
     0.00 %".
   Recommendation: **B**, so that "no data" means the same thing in every
   report.
  - B I agree that is the better way.
2. **Blank Grand Total duration on an empty Downtime day.** Store it as
   **null** (as printed, recommended), or as `00:00:00`?
  - null is fine
3. **Must the placeholder be present?** Recommendation: yes. A Downtime
   report with zero alarms is valid only if it shows `No Downtimes` and the
   Grand Total is 0. Any other report with no records is still a
   `LayoutError`, so a broken export can't pass as an empty day.
  - I am fine with your suggestion.
## Plan

1. Contract amendments (CONTRACT-002, -003, -004). Patrick approves them.
2. `.xls` parser changes and tests.
3. PDF parser changes and tests.
4. Update documentation.

## Acceptance criteria

- [ ] Contract amendments are approved before code changes.
- [ ] `Samples/XLS/11_11_2026/Downtime Summary.xls` parses to zero alarms
      and a grand total of 0 occurrences and loads, with `record_count` 0
      and one `downtime_total` row.
- [ ] Empty-day Production Summary (`.xls` and PDF) loads per decision 1.
      Totals are 0, and both formats give the same records.
- [ ] A Downtime report with no alarms and **no** placeholder, or with a
      nonzero Grand Total, still fails with a typed error.
- [ ] `run` with the 11/13 `.xls` set as the source exits 0.
- [ ] All existing tests pass.

## Validation requirements

- Parser tests for the empty-day `.xls` files (all three types) and PDFs
  (Summary and ToDate).
- Altered-grid tests: placeholder missing, Grand Total nonzero with no
  alarms.
- An end-to-end run on the empty day: exit 0, rows as specified.

## Risks and assumptions

- Only one empty-day sample exists. Other empty-day placeholders (other
  wording, other recipes) would still be rejected, which is the safe failure.

## Blocker

None.

## Implementation handoff

Task: TASK-010
Implementer: Claude (main session)
Date: 2026-11-16

### Changes made

- `src/raptor_etl/parse/__init__.py`:
  - `downtime()` recognises the `No Downtimes` placeholder (after the
    headers) and reports it to `validate()`.
  - New `drop_placeholders()` applies the CONTRACT-002 value rule (a
    section's only item, with 0/0/0, and a Total of 0 pieces). It renumbers
    `row_order`.
  - `validate()` covers the empty-Downtime checks (no alarms, Grand Total
    0, duration null or `00:00:00`). A ToDate with zero rows is allowed.
    Downtime without the placeholder, and Summary with no records, still
    fail with "at least one data record".
- `src/raptor_etl/parse/pdf.py`: Production Summary uses `drop_placeholders()`.
- No changes to the loader, schema or CLI. `record_count` 0 and 4 already
  work.

### Validation performed

- Full suite: **366 passed**, 0 failed, 0 skipped (from 354 at TASK-009 hand-off).
- Real empty-day samples:
  - `.xls` Downtime gives `()`, and `GrandTotal(0, None)`.
  - `.xls` and PDF Production Summary each give exactly the 4 Total rows,
    and the two are identical.
  - ToDate has 80 rows.
- `run` on the 11/13 set exits 0 and stores `record_count` 0 / 4 / 80, one
  `downtime_total` (0, NULL), and the four Total rows
  (`test_empty_day_run_loads_empty_reports`).

### Acceptance criteria evidence

- Amendments approved and committed (246bc80) before code.
- Empty Downtime `.xls` loads with `record_count` 0 and one `downtime_total`:
  the e2e test.
- Empty Summary, `.xls` and PDF the same: `test_empty_day_samples` and
  `test_empty_day_matches_xls`.
- Still rejected: no placeholder (`test_empty_records[downtime_summary]`),
  nonzero Grand Total, nonzero duration, placeholder plus an alarm
  (`test_empty_downtime_rejections`).
- `run` on 11/13 exits 0: e2e test.

### Assumptions and deviations

- Three existing tests encoded the old rule, and their expectations changed
  as the amendments require:
  - `test_empty_records[production_todate]` now expects zero rows to be valid.
  - The 11/13 PDF Summary count went from 8 to 4.
  - The wrapped-label test now reads the 11/13 Length label with placeholder
    removal switched off, because that placeholder is the only wrapped label
    in the samples.
- `make_share` takes optional `xls_day`/`pdf_day` (default 11/09).

### Unresolved risks

- Only one empty-day sample. Other placeholder wording is rejected, which
  is the safe failure.
- The wrapped-label PDF logic is covered only by a placeholder label that
  is now dropped in normal parsing.

### Documentation updated

The contracts were amended before code (approved). No other docs needed
changes.

## Review

Not reviewed.
