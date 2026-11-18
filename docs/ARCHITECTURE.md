# Architecture

1. **Share → archive.** Raptor writes daily Crystal Reports exports to a
   read-only SMB share. `raptor-etl run` reads the share directly through
   smbprotocol and archives date-stamped, byte-identical copies (CONTRACT-001).
2. **Archive → bronze.** The ETL parses supported archived `.xls` reports
   (CONTRACT-002) and writes each report and its lineage in one SQLite
   transaction (CONTRACT-003). An operator can backfill eligible days from
   PDFs (CONTRACT-004).
3. **Bronze → push.** The Linux systemd timer launches the oneshot service
   at 23:00 Pacific on weekdays. With push enabled, `start.sh` takes a
   SQLite backup snapshot after a successful or partial run and rsyncs it
   to the bronze server as `trimmer.db` (ADR-003). Windows runs build the
   local database.
4. **Push → SFPDataAPI.** SFPDataAPI discovers the SQLite tables at
   `TRIMMER_DB` and scans them into `bronze.trimmer__*`. The source row
   hash includes `rowid`, so append-only rows with explicit integer primary
   keys stay deduplicated across repeated scans and `VACUUM`.
