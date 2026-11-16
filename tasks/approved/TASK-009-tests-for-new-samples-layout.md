# TASK-009: Repoint tests to the new `Samples/` layout

Owner role: implementer
Assigned agent:
Proposed by: Claude (main session)
Proposed date: 2026-11-16
Approved by: Patrick
Approved date: 2026-11-16
Related contracts: CONTRACT-001, CONTRACT-002, CONTRACT-003 (validation sections only)
Related ADRs: ADR-001
Dependencies: none (TASK-008 is in review and recorded this as its blocker)

## Desired outcome

The full test suite passes against the reorganised `Samples/` folder, which
is now the permanent layout. Test expectations and coverage do not change:
only where the tests find their sample files.

## Context

Patrick reorganised `Samples/` on 2026-11-16 and is keeping the new layout:

```text
Samples/PDF/<MM_DD_YYYY>/production summary.pdf, production todate.pdf, thickness breakdown.pdf
Samples/XLS/<MM_DD_YYYY>/Downtime Summary.xls, Production Summary.xls, Production Todate.xls, Thickness Breakdown.xls
```

28 tests fail because they expect the old flat layout, with the 8 share files
at the top of `Samples/`:

| File | Failing | How it uses `Samples/` |
|---|---|---|
| `tests/test_collect.py` | 13 | Copies all of `Samples/` as the source share and expects 8 files. |
| `tests/test_load.py` | 8 | Reads `Samples/<name>.xls`. |
| `tests/test_check.py` | 5 | Copies all of `Samples/` as the source share. |
| `tests/test_load_e2e.py` | 2 | Copies all of `Samples/` as the source share. |

`tests/test_parse_reports.py` uses `Samples/<name>.xls` too. It does not fail
today only because its tests skip, so it must be repointed as well.

Facts checked:

- `Samples/XLS/11_09_2026` is the original fixture set. Its values match the
  existing expectations (20 alarms, 380 occurrences, `01:49:49`; 34 breakdown
  rows; 81 ToDate rows).
- The folder names are not the report dates. `Samples/XLS/11_11_2026` holds
  reports printed 2026-11-13.
- No `Downtime Summary.pdf` exists anywhere in `Samples/`.
- The sample PDFs are lowercase (`production summary.pdf`). Collect matches
  the share's names exactly and case-sensitively (CONTRACT-001), e.g.
  `Production Summary.pdf`.

## Scope

### Included

- One shared test helper (in `tests/conftest.py`) that builds a temporary
  "share" folder with the 8 expected files under their CONTRACT-001 names:
  - the 4 `.xls` from `Samples/XLS/11_09_2026`;
  - `Production Summary.pdf`, `Production Todate.pdf` and
    `Thickness Breakdown.pdf` from `Samples/PDF/11_09_2026`, renamed to the
    share's spelling;
  - `Downtime Summary.pdf` as a small placeholder file. Collect copies and
    hashes PDFs but never reads their content, so its bytes don't matter.
- `test_collect.py`, `test_check.py` and `test_load_e2e.py` use that helper
  instead of copying `Samples/`.
- `test_load.py` and `test_parse_reports.py` read `.xls` files from
  `Samples/XLS/11_09_2026`.
- Skip messages name the folders they need.
- DEVELOPMENT.md "Testing philosophy": describe the new layout and which
  folder is the reference set.

### Excluded

- Any change to application code or to test expectations.
- New tests for the other sample days (TASK-008 already covers the PDFs, and
  TASK-010 the empty day).

## Open decisions (need Patrick before approval)

1. **Placeholder `Downtime Summary.pdf`.** Recommendation: generate it in the
   helper. Alternative: you add a real one to `Samples/PDF/11_09_2026`, and
   the helper uses it when present.
  - When we use PDFs to restore data we will not have a Downtime Summary we can use.  So this test doesn't make sense, based on the files we will have access to.
2. **PDF name case on the real share.** The sample PDFs are lowercase. If the
   share really writes `production summary.pdf`, the nightly collect would
   report the PDFs as **missing** every night, because CONTRACT-001 expects
   `Production Summary.pdf`. Were the samples renamed when copied, or is the
   share lowercase? If it is lowercase, that needs its own task (not this one).
  - those were the real files so we need to account for lowercase issue.

## Plan

1. Add the helper and repoint the five test modules.
2. Run the full suite. It should pass with no skips caused by the layout.
3. Update DEVELOPMENT.md.

## Acceptance criteria

- [ ] Full suite passes: 0 failures. No test skips because of the layout.
- [ ] No test expectation or assertion values changed. The diff touches only
      how sample paths are found and copied.
- [ ] With `Samples/` absent, the same tests skip with a clear message.
- [ ] No application code changed.

## Validation requirements

- `pytest` full run before and after. List the tests that changed status.

## Risks and assumptions

- Assumes `Samples/XLS/11_09_2026` and `Samples/PDF/11_09_2026` stay as the
  reference set. Renaming or removing them breaks the tests again.

## Blocker

None.

## Implementation handoff

Not started.

## Review

Not reviewed.
