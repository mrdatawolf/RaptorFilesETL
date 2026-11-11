# CONTRACT-001: Collect report files into the dated archive

Status: Proposed
Approved by: Patrick
Approved date: 2026-11-11
Related tasks: TASK-001
Related ADRs: ADR-001

## Purpose

Keep an unaltered, dated copy of each day's Raptor report files before the
source share overwrites them, and never archive the same content twice.

## Scope

### Included

- Copying the expected report files from the source folder to the archive.
- Checking each copy byte for byte with SHA-256.
- Skipping files whose content has already been archived.
- Recording each archived file in the database (`archived_file`).

### Excluded

- Parsing or loading (CONTRACT-002, CONTRACT-003).
- Changing, moving or deleting anything in the source folder.
- Deleting anything from the archive. Archived files are kept forever.

## Actors

- **Scheduler**: starts a run at the configured time (ADR-001).
- **Operator**: may start `raptor-etl run` by hand.
- **Source share**: read-only SMB share (`RAPTOR_SOURCE_PATH`).

## Inputs and outputs

**Input: the expected files.** Exactly these 8 names, in the source folder
root, matched case-sensitively:

| Original name | Report type |
|---|---|
| `Downtime Summary.pdf` / `.xls` | Downtime Summary |
| `Production Summary.pdf` / `.xls` | Production Summary |
| `Production Todate.pdf` / `.xls` | Production ToDate |
| `Thickness Breakdown.pdf` / `.xls` | Thickness Breakdown (archived only) |

Any other file in the source folder is ignored and not logged. Changing this
list requires changing this contract.

**Outputs:**

- An archive file named `<copy date>_<original name>`, where the copy date is
  `YYYY-MM-DD` in `RAPTOR_TIMEZONE` at the moment the run starts. Example:
  `2026-11-10_Production Summary.xls`. All files in a run share one copy
  date, even if the run crosses midnight.
- One `archived_file` record per archived file (schema in CONTRACT-003).
- One outcome per expected file: `archived`, `unchanged`, `missing` or
  `failed`.

## Preconditions

Checked at the start of the run. If any fails, the run exits before
collecting.

- Configuration is valid (ADR-001). Otherwise: exit code 2.
- `RAPTOR_ARCHIVE_DIR` exists and is writable. Otherwise: exit code 2.
- No other run holds the run lock. Otherwise: exit code 3, nothing done.

The share being unreachable is **not** a precondition failure. See Failure
behavior.

## Required behavior

For each expected file, independently and in the order listed above:

1. If the file is absent from the source → outcome `missing`.
2. Copy it to a temporary name in the archive folder (`.<archive name>.partial`),
   calculating SHA-256 of the bytes read from the source.
3. If an `archived_file` record already has the same original name and the
   same SHA-256 → delete the temporary file. Outcome `unchanged`. (This is
   the weekday no-production case.)
4. If a file with the final archive name already exists:
   - with the **same** SHA-256 (left behind by an interrupted earlier run) →
     delete the temporary file, insert the missing `archived_file` record.
     Outcome `archived`.
   - with a **different** SHA-256 → delete the temporary file, never
     overwrite. Outcome `failed`.
5. Otherwise, calculate SHA-256 of the temporary file and compare it with the
   source hash. If they match, rename it to the final archive name and insert
   the `archived_file` record. Outcome `archived`. If they differ, delete it.
   Outcome `failed`.

Each outcome is logged with the file name, outcome, archive name (if any)
and a short hash.

## Postconditions and invariants

- **Read-only source:** nothing in the source folder is created, changed or
  deleted.
- **Exact copy:** every file referenced by an `archived_file` record has a
  SHA-256 equal to the recorded hash, which equals the source bytes read.
- **No duplicates:** at most one `archived_file` record exists for each
  (original name, SHA-256) pair.
- **No overwrite:** an existing archive file is never replaced or changed.
- **No partial files left:** when a run ends, no `.partial` file from that
  run remains, and no record points at a file that doesn't exist.
- **Consistent copy date:** every archive name created in a run uses the
  same copy date.
- After an `archived` outcome, the file is available to the load stage
  (CONTRACT-003).

## Failure behavior

| Situation | Behavior |
|---|---|
| Share unreachable or login fails | All 8 files are `failed` with the reason logged. The run continues to the load stage. Exit code 1. |
| Expected file missing | That file is `missing`. Others continue. Exit code 1. |
| Read or write error on one file | That file is `failed` and its temporary file is removed. Others continue. Exit code 1. |
| Archive name exists with different content | `failed`, nothing overwritten. Others continue. Exit code 1. Needs a person to resolve it. |
| Process killed mid-copy | A `.partial` file may remain. The next run overwrites or removes it. Step 4 recovers any record that is missing. |

The SMB password never appears in logs or error messages.

## Interfaces

- `raptor-etl run`: collect, then load (CONTRACT-003). Exit codes:
  `0` = every file `archived` or `unchanged` and every load succeeded;
  `1` = at least one file `missing` or `failed`, or a load failed;
  `2` = invalid configuration or unusable archive folder;
  `3` = another run in progress.
- Collect writes only to `RAPTOR_ARCHIVE_DIR` and the `archived_file` table.

## Validation requirements

Automated tests against a local source folder holding copies of `Samples/`:

- A first run archives all 8 files with correct names and matching hashes.
- A second run with identical source files → all 8 `unchanged`, no new
  archive files or records.
- One changed source file → only that file is `archived`.
- A missing source file → `missing` and exit code 1, while the others are
  archived.
- Archive name exists with different content → `failed`, existing file
  byte-identical afterwards.
- Archive name exists with the same content but no record → the record is
  recovered.
- The source folder is unchanged after every test (compare hash and
  modification time before and after).
- Copy date follows `RAPTOR_TIMEZONE`, not the host's time zone (test with
  an injected clock at 23:30 Pacific = 07:30 UTC the next day).
- A second concurrent run exits with 3.

Manual: one run against the real SMB share before deployment.

## Open questions

1. **Does the report system leave files untouched on no-production days?**
   This contract assumes the share keeps the previous run's files
   byte-identical. If Raptor regenerates them, for example with a new Printed
   time, their hashes will differ and they will be archived and loaded again.
   To check: compare two days' files around a no-production weekday.
 - Yes