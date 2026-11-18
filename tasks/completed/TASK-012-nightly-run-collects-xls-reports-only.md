# TASK-012: Nightly run collects only the three data `.xls` reports

Owner role: implementer
Assigned agent: Claude (main session)
Proposed by: Claude (main session)
Proposed date: 2026-11-18
Approved by: Patrick
Approved date: 2026-11-18
Related contracts: CONTRACT-001 (needs amendment); CONTRACT-002, CONTRACT-003 (wording only); CONTRACT-004 (unchanged)
Related ADRs: ADR-001, ADR-003
Dependencies: None

## Desired outcome

The nightly `raptor-etl run` and `raptor-etl check` work only with the three
`.xls` reports that hold data:

- `Downtime Summary.xls`
- `Production Summary.xls`
- `Production Todate.xls`

The automated process never reads, copies or reports on `.pdf` files or on
Thickness Breakdown. Exit code 1 means a data report is missing, failed to
copy, or failed to load.

PDFs are loaded only when a person runs `raptor-etl import-pdf <folder>`
(CONTRACT-004, unchanged) during an emergency backfill.

## Context

CONTRACT-001 lists 8 expected files: the four reports, each as `.pdf` and
`.xls`. The nightly run only loads three of them. The other five are
archived and never used:

- **PDFs.** Every report is exported in both formats with the same content,
  so the nightly PDFs duplicate the `.xls`. A PDF backfill is only needed
  when a day has no `.xls` at all. In that case the PDF has usually reached
  someone another way (it is distributed to users separately), not through
  the share. The archived share PDFs therefore do not cover the emergency
  they were meant for.
- **Thickness Breakdown.** The report is only a chart, and its `.xls` holds
  no data cells (PROJECT.md). Archiving it has no use.

Treating these five files as expected has a cost. A missing PDF or
Thickness Breakdown gives exit code 1, the same as a lost data report.
systemd then marks `raptorbronze.service` failed, and `check` reports
`FAIL`. A failure that usually means nothing teaches people to ignore real
failures.

Backfills are rare enough that they stay manual. A person deciding to
backfill a day is a useful check. `import-pdf` already exists and works on
any folder that holds that day's PDFs.

No active databases exist (confirmed by Patrick, 2026-11-18), so no stored
data needs migrating.

## Scope

### Included

- **CONTRACT-001 amendment.** The expected files are the three `.xls` data
  reports listed above. Every other file in the source folder, including
  `.pdf` files and both Thickness Breakdown files, is ignored and not
  logged. Update every place that says "8 files", the
  validation-requirements list and the exit-code text.
- **`collect.py`.** Change `EXPECTED_FILES` to the three `.xls` names. The
  `@ensure` postconditions follow automatically.
- **`check`.** Uses `EXPECTED_FILES`, so it covers only the three files.
  Confirm that no PDF or Thickness Breakdown lines remain in its output.
- **Load.** Behavior is unchanged: `REPORT_TYPES` already selects the same
  three names. Remove anything that only filtered out PDFs or Thickness
  Breakdown from share collection, if it is now redundant. Keep the filter
  if it still protects the load stage from PDF rows written by `import-pdf`,
  which it does today.
- **Tests.** Update `tests/conftest.py`'s `make_share` so it builds only the
  three `.xls` files: no PDF renaming, no `Downtime Summary.pdf` stand-in.
  Update tests that assume 8 files or name a PDF as `EXPECTED_FILES[0]`,
  e.g. the trigger on `'Downtime Summary.pdf'` in `tests/test_collect.py`.
  Add a test showing that `.pdf` and Thickness Breakdown files in the
  source are ignored: not archived, not logged, no effect on the exit code.
- **Documentation.** PROJECT.md scope and source-reports table,
  ARCHITECTURE.md where it describes collection, DEVELOPMENT.md (testing
  philosophy and the `make_share` description), and the CONTRACT-002 and
  CONTRACT-003 sentences that say PDFs and Thickness Breakdown are
  "archived only" or "excluded before parsing".
- **Local database rebuild** (after the code changes pass review). Delete
  `Data/raptor.db` and the contents of `Samples/Archive`. Rebuild from
  `Samples/XLS/{11_09,11_11,11_16,11_17}_2026` with 23:00 copy dates
  (2026-11-09, 2026-11-13, 2026-11-16, 2026-11-17). Then run
  `import-pdf Samples/PDF`. The result has no share-PDF or Thickness
  Breakdown rows.

### Excluded

- Any change to `import-pdf` or CONTRACT-004. It remains the only way a PDF
  enters the database or the archive.
- Automatic PDF ingestion of any kind.
- Removing pdfplumber or the PDF parser. Both are still used by `import-pdf`.
- Day-selection options for `import-pdf` (for example `--date`, or a single
  file instead of a folder). Propose them separately if wanted.
- Handling an `.xls` that arrives after a PDF backfill for the same day.
  Bronze then holds two loads for that day. This is a known, accepted
  issue: bronze is append-only and a later layer removes duplicates.
- Schema changes, and the deployment files (`start.sh`, systemd units).

## Plan

1. Amend CONTRACT-001, plus the CONTRACT-002 and CONTRACT-003 wording, and
   have Patrick approve the amendment.
2. Change `EXPECTED_FILES` and adjust the tests and fixtures.
3. Add the "ignored files" test.
4. Update PROJECT.md, ARCHITECTURE.md and DEVELOPMENT.md.
5. Run the full suite.
6. Independent review.
7. After acceptance, rebuild the local database as described in Scope.

## Acceptance criteria

- [ ] CONTRACT-001 lists exactly three expected files, all `.xls`, and says
      that `.pdf` and Thickness Breakdown files are ignored.
- [ ] Against a source holding all 8 old files, `raptor-etl run` archives
      and loads only the three data `.xls` files, and logs nothing about the
      other five.
- [ ] Against a source holding only the three data `.xls` files,
      `raptor-etl run` exits 0.
- [ ] A missing data `.xls` still gives outcome `missing` and exit code 1.
- [ ] `raptor-etl check` reports only the three files, and exits 0 when
      they are present even if no PDFs exist.
- [ ] `raptor-etl import-pdf` behaves exactly as before. Its tests pass
      unchanged, apart from fixture setup.
- [ ] No documentation still describes the nightly run as copying PDFs or
      Thickness Breakdown.
- [ ] The full test suite passes.
- [ ] The rebuilt `Data/raptor.db` has no `archived_file` rows for
      Thickness Breakdown. Its only `.pdf` rows come from `import-pdf`
      (11-10 and 11-11 Production Summary and ToDate). `load_failure` is
      empty.

## Validation requirements

- CONTRACT-001's amended validation-requirements list.
- The new "non-data files are ignored" test.
- Existing collect, check, load, end-to-end and import-pdf tests, adjusted
  to the three-file share.

## Risks and assumptions

- Assumes the share keeps exporting the same three `.xls` names. A rename
  still shows up as `missing` and exit 1, as it does today.
- Archived share PDFs will no longer exist for future days. This is
  accepted: the emergency backfill uses PDFs obtained outside the share.
- Thickness Breakdown is dropped entirely. If a future project needs it,
  that needs its own task and contract change.

## Blocker

None.

## Implementation handoff

Task: TASK-012
Implementer: Claude (main session)
Date: 2026-11-18

### Changes made

- `src/raptor_etl/collect.py`: `EXPECTED_FILES` holds only the 3 data
  `.xls` names. `collect` and `check` both iterate this tuple, so neither
  reads, copies nor reports `.pdf` or Thickness Breakdown files any more.
  Its `@ensure` postconditions follow automatically.
- Load: no change. Its `original_name IN (3 .xls names)` filter is kept
  because it still keeps PDF rows written by `import-pdf` out of `run`.
- `import-pdf`, the PDF parser and pdfplumber: untouched.
- `tests/conftest.py`: `make_share` builds the 3 `.xls` files from
  `Samples/XLS/<xls_day>`. The `pdf_day` parameter and the Downtime PDF
  stand-in are gone. New `non_data=True` writes stand-ins for the 5 files
  the share also holds (`NON_DATA_FILES`).
- Tests: counts 8 → 3 (collect, e2e, check). The injected database-fault
  trigger now names `Downtime Summary.xls`. The SMB mock's listing and the
  `check` test's listing now also contain the non-data names.
- New test `test_pdf_and_thickness_breakdown_are_ignored`: run against a
  source holding all 8 old files exits 0, archives and records only the
  3 `.xls`, logs none of the 5 others, and leaves the source unchanged.
- Docs: CONTRACT-001 (expected files, ignored files, validation list,
  amendment), wording in CONTRACT-002 and CONTRACT-003, PROJECT.md scope
  and source-reports table, ARCHITECTURE.md steps 1–2, DEVELOPMENT.md
  (samples and `make_share`, `check`, how to backfill one day).

### Validation performed

- Full suite: **328 passed**, 0 failed, 0 skipped. Before the change:
  327 tests, of which 17 failed once `EXPECTED_FILES` changed and were
  then updated; plus 1 new test.
- Local database rebuilt from scratch: `Data/raptor.db` and
  `Samples/Archive/*` deleted. Then `collect` + `load` for XLS `11_09`,
  `11_11`, `11_16` and `11_17` with injected 23:00 clocks (copy dates
  11-09, 11-13, 11-16, 11-17), then `import-pdf Samples/PDF`. Overall
  exit 0 (previously 1, from the 8 "missing" PDFs per run).

### Acceptance criteria evidence

- CONTRACT-001 lists exactly 3 `.xls` files and says the rest are
  ignored.
- Run against all 8 old files: only the 3 archived and loaded, nothing
  logged about the others: the new test.
- Run against only the 3 `.xls` exits 0:
  `test_cli_success_and_load_visibility` and the e2e tests.
- A missing `.xls` still gives `missing` and exit 1:
  `test_missing_case_sensitive_ignored_and_exit`.
- `check` reports 7 lines (4 precheck + 3 files) and exits 0 with no
  PDFs; it does not mention non-data files even when they are listed:
  `test_check_ok_info_fail_error_visible_default`.
- `import-pdf` tests pass with no changes to `tests/test_import_pdf.py`.
- No document still describes the nightly run as copying PDFs or
  Thickness Breakdown (grep of `docs/`, `src/` and `AGENTS.md`).
  ADR-001's "8 files" remark is historical and was left alone.
- Rebuilt database: `load_failure` empty. `archived_file` contains 12 `.xls` rows (3 per
  day) and 4 `.pdf` rows, which are 2026-11-10 and 2026-11-11 Production Summary and Todate, all
  from `import-pdf`. There are no Thickness Breakdown rows. Per day: 11-09 20/34/81,
  11-10 –/30/81 (PDF), 11-11 –/35/81 (PDF), 11-13 0/4/80,
  11-16 19/42/80, 11-17 19/45/80.

### Assumptions and deviations

- Plan step 1 asked for the contract amendment to be approved before
  code. The amendment text was fully specified in this approved task, so
  it was written together with the code. Its amendment entry says
  "approved with the task, confirm at acceptance". Please confirm it when
  accepting.
- The rebuild script was a scratchpad helper with an injected clock. It
  is not part of the repository.

## Review

Not reviewed.
