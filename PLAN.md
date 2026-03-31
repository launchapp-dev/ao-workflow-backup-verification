# Backup Verification Pipeline — Workflow Plan

## Overview

Automated backup verification for DevOps/SRE teams. Schedules backup snapshots of databases, filesystems, and object stores, executes restore-to-test procedures, validates data integrity via checksums and row counts, measures restore time against SLA targets, flags failures, and generates compliance evidence for SOC2/ISO audits. Built entirely on real CLI tools (`pg_dump`, `pg_restore`, `sha256sum`, `rsync`, `jq`, `gh`, `python3`, `date`) and filesystem/sequential-thinking MCP servers.

---

## Agents (5)

| Agent | Model | Role |
|---|---|---|
| **backup-scheduler** | claude-haiku-4-5 | Reads backup config, determines which backups are due, generates execution manifest |
| **restore-operator** | claude-sonnet-4-6 | Orchestrates restore-to-test procedures, interprets restore output, handles failures |
| **integrity-validator** | claude-haiku-4-5 | Compares checksums, row counts, and file hashes between source and restored data |
| **compliance-packager** | claude-sonnet-4-6 | Generates SOC2/ISO evidence, compliance attestation packages, audit-ready reports |
| **alert-reporter** | claude-sonnet-4-6 | Produces daily health reports, weekly RTO trend analysis, escalation alerts for failures |

### MCP Servers Used by Agents

- **filesystem** — all agents read/write JSON/YAML config and report files
- **sequential-thinking** — restore-operator uses for multi-step restore decision logic; compliance-packager uses for evidence mapping across frameworks

---

## Data Architecture

### Key Config Files

- `config/backup-sources.yaml` — defines all backup sources (databases, filesystems, object stores) with connection info, backup method, schedule, and SLA targets
- `config/sla-policy.yaml` — RTO/RPO targets per backup source, escalation thresholds, compliance framework mappings
- `config/verification-rules.yaml` — integrity check rules: checksum algorithms, row count tolerance, file count validation, schema comparison rules

### Key Data Files

- `data/manifests/` — per-run execution manifests listing which backups to verify
- `data/snapshots/` — metadata about backup snapshots (paths, sizes, timestamps — never the data itself)
- `data/restore-logs/` — restore procedure output, timing, success/failure status
- `data/integrity-results/` — checksum comparisons, row count diffs, schema diffs
- `data/rto-measurements/` — restore timing records with SLA comparison
- `data/compliance-evidence/` — structured evidence records for audit

### Key Output Files

- `output/daily-health-report.md` — daily backup health dashboard
- `output/weekly-rto-trends.md` — weekly RTO trend analysis and SLA adherence
- `output/monthly-attestation/` — monthly compliance attestation package
- `output/alerts/` — escalation alerts for failed or degraded backups

---

## Workflows (3)

### 1. `verify-backups` (primary — daily scheduled)

Full verification cycle: identify due backups → execute restores → validate integrity → measure RTO → report.

**Phases:**

1. **identify-due-backups** (agent: backup-scheduler)
   - Reads `config/backup-sources.yaml` for all registered backup sources
   - Reads `data/snapshots/last-verified.json` for last verification timestamps
   - Compares against each source's `verify_frequency` to determine what's due
   - Generates `data/manifests/YYYY-MM-DD-manifest.json` listing backups to verify
   - Each manifest entry: source_id, backup_type, backup_path, expected_checksum, sla_rto_seconds
   - Decision contract: `{ verdict: "backups-found" | "none-due", count: N, sources: [...] }`
   - On `none-due`: workflow ends gracefully (advance to report phase with empty results)

2. **execute-restores** (command phase)
   - Command: `bash scripts/execute-restores.sh`
   - Reads today's manifest, iterates over each backup source:
     - **PostgreSQL**: `pg_restore --dbname=test_restore --clean --if-exists <dump_path>` then `psql -c "SELECT count(*) FROM <table>"` for row counts
     - **Filesystem**: `rsync --checksum --dry-run <backup_path> <test_restore_path>` for diff, then actual rsync
     - **SQLite**: `sqlite3 <backup.db> ".tables"` and `sqlite3 <backup.db> "SELECT count(*) FROM <table>"`
   - Captures wall-clock time for each restore via `date +%s` before/after
   - Writes per-source results to `data/restore-logs/YYYY-MM-DD/<source_id>.json`:
     ```json
     {
       "source_id": "prod-db-main",
       "restore_start": "ISO8601",
       "restore_end": "ISO8601",
       "restore_duration_seconds": 47,
       "exit_code": 0,
       "stdout_tail": "...",
       "stderr_tail": "..."
     }
     ```

3. **validate-integrity** (agent: integrity-validator)
   - Reads restore logs from step 2
   - For each restored backup, runs validation checks:
     - **Checksum comparison**: reads `data/snapshots/<source_id>-checksums.txt` (pre-computed sha256 of source), computes sha256 of restored data, compares
     - **Row count comparison**: reads expected row counts from manifest, compares against actual restored counts
     - **Schema validation**: for databases, compares table list and column definitions
     - **File count validation**: for filesystem backups, compares file counts and directory structure
   - Writes `data/integrity-results/YYYY-MM-DD/<source_id>.json`:
     ```json
     {
       "source_id": "prod-db-main",
       "checksum_match": true,
       "row_count_match": true,
       "row_count_diff": { "users": { "expected": 50000, "actual": 50000 } },
       "schema_match": true,
       "overall_status": "verified"
     }
     ```
   - Decision contract: `{ verdict: "verified" | "degraded" | "failed", failed_sources: [...], degraded_sources: [...] }`
   - On `failed`: rework to execute-restores (max 2 attempts — backup may be corrupt)
   - On `degraded`: advance but flag for attention in report

4. **measure-rto** (command phase)
   - Command: `python3 scripts/measure-rto.py`
   - Reads restore logs for timing, reads `config/sla-policy.yaml` for RTO targets
   - Computes for each source:
     - `restore_duration_seconds` vs `sla_rto_seconds`
     - Percentage of SLA consumed: `(actual / target) * 100`
     - Status: `within-sla` (<80%), `approaching-limit` (80-100%), `exceeds-sla` (>100%)
   - Appends to `data/rto-measurements/history.jsonl` (one JSON line per measurement per source)
   - Writes `data/rto-measurements/YYYY-MM-DD-summary.json`:
     ```json
     {
       "date": "2026-03-31",
       "sources": [
         { "source_id": "prod-db-main", "rto_seconds": 47, "sla_seconds": 300, "pct": 15.7, "status": "within-sla" }
       ],
       "overall_status": "within-sla"
     }
     ```

5. **generate-daily-report** (agent: alert-reporter)
   - Reads integrity results, RTO measurements, and manifest
   - Produces `output/daily-health-report.md` with:
     - Summary: total verified, passed, degraded, failed
     - Per-source table: source, backup type, integrity status, RTO, SLA status
     - Alerts section: any failures or SLA breaches highlighted
     - Trend sparkline: last 7 days pass/fail ratio (reads from history)
   - If any `failed` or `exceeds-sla`: writes alert to `output/alerts/YYYY-MM-DD-alert.md`
   - Creates GitHub issue via filesystem for critical failures (writes issue template to `output/alerts/`)

### 2. `weekly-rto-analysis` (weekly — scheduled)

Trend analysis of RTO performance over the past week.

**Phases:**

1. **aggregate-rto-data** (command phase)
   - Command: `python3 scripts/aggregate-rto.py`
   - Reads `data/rto-measurements/history.jsonl` for last 7 days
   - Computes per-source: min/max/avg/p95 restore times, SLA adherence rate
   - Computes overall: number of SLA breaches, trending direction (improving/stable/degrading)
   - Writes `data/rto-measurements/weekly-YYYY-WW.json`

2. **analyze-trends** (agent: alert-reporter)
   - Reads weekly aggregate data and previous weeks for comparison
   - Identifies:
     - Sources with degrading RTO trends (>20% increase week-over-week)
     - Sources consistently near SLA limits (avg >70% of SLA)
     - Sources with intermittent failures (pass rate <100% but >80%)
   - Produces `output/weekly-rto-trends.md` with:
     - Executive summary
     - Per-source trend table with week-over-week comparison
     - Recommendations for sources at risk
     - Charts expressed as markdown tables showing 4-week trend

### 3. `monthly-compliance` (monthly — scheduled)

SOC2/ISO compliance evidence packaging.

**Phases:**

1. **collect-evidence** (agent: compliance-packager)
   - Reads all daily integrity results and RTO measurements for the month
   - Reads `config/sla-policy.yaml` for compliance framework mappings
   - Maps evidence to compliance controls:
     - SOC2 A1.2 (Recovery) → RTO measurements + restore success records
     - SOC2 A1.1 (Availability) → daily backup verification pass rates
     - ISO 27001 A.12.3 (Backup) → integrity validation records
   - Writes structured evidence to `data/compliance-evidence/YYYY-MM/`:
     - `backup-verification-evidence.json` — all verification records
     - `rto-compliance-evidence.json` — all RTO measurements with SLA mapping
     - `integrity-evidence.json` — all integrity check results

2. **generate-attestation** (agent: compliance-packager)
   - Reads collected evidence from step 1
   - Uses sequential-thinking MCP for complex compliance mapping decisions
   - Produces `output/monthly-attestation/YYYY-MM/`:
     - `attestation-summary.md` — formal compliance attestation document
     - `control-matrix.md` — control-by-control evidence coverage matrix
     - `exceptions-log.md` — any failures, SLA breaches, or gaps with remediation notes
     - `evidence-index.md` — index of all evidence files with references
   - Decision contract: `{ verdict: "compliant" | "exceptions-noted" | "non-compliant", compliance_rate: N, exception_count: N }`
   - On `non-compliant`: creates escalation alert

---

## Phase Routing Summary

### verify-backups
```
identify-due-backups → execute-restores → validate-integrity → measure-rto → generate-daily-report
                                              ↑         |
                                              └─ rework ─┘ (on "failed", max 2)
```

### weekly-rto-analysis
```
aggregate-rto-data → analyze-trends
```

### monthly-compliance
```
collect-evidence → generate-attestation
```

---

## Schedules

| Schedule | Cron | Workflow |
|---|---|---|
| Daily verification | `0 6 * * *` | verify-backups |
| Weekly RTO analysis | `0 8 * * 1` | weekly-rto-analysis |
| Monthly compliance | `0 9 1 * *` | monthly-compliance |

---

## Scripts

### scripts/execute-restores.sh
- Reads `data/manifests/YYYY-MM-DD-manifest.json` (today's date)
- Iterates backup sources, runs type-specific restore commands
- Captures timing via `date +%s`
- Writes per-source JSON to `data/restore-logs/`
- Handles errors gracefully — captures stderr, sets non-zero status per source but continues

### scripts/measure-rto.py
- Reads restore logs + SLA config
- Computes RTO metrics and SLA comparison
- Appends to JSONL history file
- Writes daily summary JSON

### scripts/aggregate-rto.py
- Reads JSONL history for date range
- Computes statistical aggregates (min/max/avg/p95)
- Computes trend direction via simple linear regression on last 4 data points
- Writes weekly summary JSON

---

## Sample Config: backup-sources.yaml

```yaml
backup_sources:
  - id: prod-db-main
    type: postgresql
    backup_method: pg_dump
    backup_path: "/backups/prod-db-main/latest.dump"
    test_restore_db: "test_restore_prod_main"
    tables_to_verify: ["users", "orders", "products", "transactions"]
    verify_frequency: daily
    sla_rto_seconds: 300
    checksum_file: "data/snapshots/prod-db-main-checksums.txt"

  - id: prod-db-analytics
    type: postgresql
    backup_method: pg_dump
    backup_path: "/backups/prod-db-analytics/latest.dump"
    test_restore_db: "test_restore_analytics"
    tables_to_verify: ["events", "metrics", "aggregates"]
    verify_frequency: daily
    sla_rto_seconds: 600

  - id: app-uploads
    type: filesystem
    backup_method: rsync
    backup_path: "/backups/app-uploads/latest/"
    test_restore_path: "/tmp/test-restore/app-uploads/"
    verify_frequency: daily
    sla_rto_seconds: 120

  - id: config-store
    type: sqlite
    backup_method: sqlite_dump
    backup_path: "/backups/config-store/latest.db"
    test_restore_path: "/tmp/test-restore/config-store.db"
    tables_to_verify: ["settings", "feature_flags", "tenants"]
    verify_frequency: daily
    sla_rto_seconds: 30
```

## Sample Config: sla-policy.yaml

```yaml
rto_thresholds:
  within_sla_pct: 80        # <80% of SLA = green
  approaching_limit_pct: 100 # 80-100% = yellow
  exceeds_sla_pct: 100       # >100% = red

escalation:
  on_failed_integrity: immediate    # alert immediately
  on_exceeds_sla: immediate         # alert immediately
  on_approaching_limit: daily_report # include in daily report
  on_degraded: daily_report          # include in daily report

compliance_mappings:
  soc2:
    - criterion: "A1.1"
      control: "Backup verification pass rate"
      evidence_source: "daily-health-report"
    - criterion: "A1.2"
      control: "Restore time within SLA"
      evidence_source: "rto-measurements"
  iso27001:
    - control: "A.12.3.1"
      description: "Information backup"
      evidence_source: "integrity-results"

retention:
  daily_reports_days: 90
  rto_history_days: 365
  compliance_evidence_months: 24
```

## Sample Config: verification-rules.yaml

```yaml
integrity_checks:
  postgresql:
    - type: row_count
      tolerance_pct: 0          # exact match required
    - type: table_list
      tolerance: exact           # all tables must exist
    - type: schema_check
      compare: column_names_and_types

  filesystem:
    - type: file_count
      tolerance_pct: 0
    - type: checksum
      algorithm: sha256
      sample_rate: 100           # check 100% of files

  sqlite:
    - type: row_count
      tolerance_pct: 0
    - type: table_list
      tolerance: exact
```

---

## Directory Structure

```
backup-verification/
├── .ao/workflows/
│   ├── agents.yaml
│   ├── phases.yaml
│   ├── workflows.yaml
│   ├── mcp-servers.yaml
│   └── schedules.yaml
├── config/
│   ├── backup-sources.yaml
│   ├── sla-policy.yaml
│   └── verification-rules.yaml
├── scripts/
│   ├── execute-restores.sh
│   ├── measure-rto.py
│   └── aggregate-rto.py
├── templates/
│   ├── daily-health-report.md
│   ├── weekly-rto-trends.md
│   └── attestation-summary.md
├── data/                        # Generated at runtime
│   ├── manifests/
│   ├── snapshots/
│   ├── restore-logs/
│   ├── integrity-results/
│   ├── rto-measurements/
│   └── compliance-evidence/
├── output/                      # Generated reports
│   ├── alerts/
│   └── monthly-attestation/
├── CLAUDE.md
└── README.md
```
