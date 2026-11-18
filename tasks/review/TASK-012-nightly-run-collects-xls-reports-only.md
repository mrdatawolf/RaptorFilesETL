# TASK-012: Nightly run collects only the three data `.xls` reports

Owner role: implementer
Assigned agent:
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

Not started.

## Review

Not reviewed.
