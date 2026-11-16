# TASK-010: Reports with no data are valid

Owner role: implementer
Assigned agent:
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

Not started.

## Review

Not reviewed.
