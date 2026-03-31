# Backup Verification Pipeline

## What This Project Does

This is an automated backup verification system for DevOps/SRE teams. It regularly tests that
backup data can actually be restored, validates data integrity, measures restore times against
SLA targets, and generates compliance evidence for SOC2 Type II and ISO 27001 audits.

The system verifies four types of backups:
- **PostgreSQL** databases (via `pg_restore`, row count and schema validation)
- **Filesystem** snapshots (via `rsync --checksum`, file count and SHA256 verification)
- **SQLite** databases (via `sqlite3`, row count validation)

## Key Files

- `config/backup-sources.yaml` — Register backup sources here. Each entry needs: `id`, `type`,
  `backup_path`, `verify_frequency` (daily/weekly/monthly), and `sla_rto_seconds`.
- `config/sla-policy.yaml` — RTO thresholds and compliance framework mappings.
- `config/verification-rules.yaml` — Integrity check rules per backup type.
- `data/snapshots/last-verified.json` — Tracks last successful verification per source.
  Updated automatically after each successful run.

## How Agents Should Work

### backup-scheduler
Read `config/backup-sources.yaml` + `data/snapshots/last-verified.json`, determine which
sources are due, write `data/manifests/YYYY-MM-DD-manifest.json`. The manifest must be a JSON
object with keys: `date`, `generated_at`, `sources` (array of source objects).

### restore-operator
After the bash script runs, read restore logs from `data/restore-logs/YYYY-MM-DD/`.
Write `restore-operator-summary.json` in that same directory summarizing what succeeded
and what failed, so integrity-validator can use it.

### integrity-validator
Read the restore-operator-summary.json and individual restore logs. For each source,
determine `overall_status`: "verified", "degraded", or "failed". Write results to
`data/integrity-results/YYYY-MM-DD/<source_id>.json`.

### compliance-packager
Work month-by-month. Evidence files go in `data/compliance-evidence/YYYY-MM/`.
Attestation documents go in `output/monthly-attestation/YYYY-MM/`.
Use sequential-thinking to map evidence to controls before writing the attestation.

### alert-reporter
Reports go in `output/`. Alerts go in `output/alerts/`. Use concrete numbers and
source IDs in all reports. If there are no failures, say so explicitly rather than
omitting the alerts section.

## Data Conventions

- All dates are ISO 8601 (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)
- All JSON files use 2-space indent
- Restore logs: `data/restore-logs/YYYY-MM-DD/<source_id>.json`
- Integrity results: `data/integrity-results/YYYY-MM-DD/<source_id>.json`
- RTO history: `data/rto-measurements/history.jsonl` (one JSON object per line)
- Compliance evidence: `data/compliance-evidence/YYYY-MM/`

## Running Locally

```bash
# Install python deps
pip install pyyaml

# Run a verification cycle
ao workflow run verify-backups

# Check report
cat output/daily-health-report.md

# Check for alerts
ls output/alerts/
```
