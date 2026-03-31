# backup-verification

Automated backup verification pipeline — schedule restore tests, validate data integrity via checksums and row counts, measure RTO against SLA targets, and generate SOC2/ISO 27001 compliance evidence.

## Workflow Diagram

```
                        DAILY (06:00)
                              │
                    ┌─────────▼──────────┐
                    │  identify-due-     │  backup-scheduler
                    │  backups           │  (haiku)
                    └──────┬─────────────┘
                           │ backups-found
                    ┌──────▼─────────────┐
                    │  execute-restores  │  pg_restore / rsync
                    │  (command phase)   │  sqlite3 / date +%s
                    └──────┬─────────────┘
                           │
                    ┌──────▼─────────────┐
                    │  validate-         │  integrity-validator
                    │  integrity         │  (haiku)
                    └──────┬─────────────┘
                           │ verified / degraded
                    ┌──────▼─────────────┐    ┌──────────────────┐
                    │  measure-rto       │    │  execute-restores │
                    │  (python3 script)  │◄───│  (rework on fail, │
                    └──────┬─────────────┘    │   max 2 attempts) │
                           │                  └──────────────────┘
                    ┌──────▼─────────────┐
                    │  generate-daily-   │  alert-reporter
                    │  report            │  (sonnet)
                    └────────────────────┘

        WEEKLY (Mon 08:00)              MONTHLY (1st 09:00)
               │                                │
    ┌──────────▼──────────┐        ┌────────────▼──────────┐
    │  aggregate-rto-data │        │  collect-evidence      │
    │  (python3 script)   │        │  (compliance-packager) │
    └──────────┬──────────┘        └────────────┬──────────┘
               │                                │
    ┌──────────▼──────────┐        ┌────────────▼──────────┐
    │  analyze-trends     │        │  generate-attestation  │
    │  (alert-reporter)   │        │  (compliance-packager) │
    └─────────────────────┘        └────────────┬──────────┘
                                                │
                                   ┌────────────▼──────────┐
                                   │  compliance-review-    │
                                   │  gate (manual)         │
                                   └───────────────────────┘
```

## Quick Start

```bash
cd examples/backup-verification

# Configure your backup sources
vi config/backup-sources.yaml

# Start the daemon — runs daily at 06:00, weekly on Monday, monthly on the 1st
ao daemon start

# Or run a single verification cycle now
ao workflow run verify-backups

# Watch live
ao daemon stream --pretty
```

## Agents

| Agent | Model | Role |
|---|---|---|
| **backup-scheduler** | claude-haiku-4-5 | Reads backup config, checks last-verified timestamps, generates execution manifest for due sources |
| **restore-operator** | claude-sonnet-4-6 | Analyzes restore logs, diagnoses failures, writes restore-operator-summary before integrity check |
| **integrity-validator** | claude-haiku-4-5 | Compares checksums, row counts, and schemas between source and restored backup |
| **compliance-packager** | claude-sonnet-4-6 | Maps verification evidence to SOC2/ISO controls, generates attestation packages |
| **alert-reporter** | claude-sonnet-4-6 | Produces daily health reports, weekly RTO trend analysis, escalation alerts |

## AO Features Demonstrated

- **Scheduled workflows** — daily verification at 06:00, weekly RTO analysis on Mondays, monthly compliance on the 1st
- **Decision contracts** — `backup-health: verified/degraded/failed`, `rto-status: within-sla/approaching-limit/exceeds-sla`
- **Phase routing** — rework loop on `failed` integrity (max 2 retries), manual gate before compliance finalization
- **Multi-model pipeline** — haiku for fast data tasks, sonnet for complex analysis and report writing
- **Command phases** — `execute-restores.sh` (bash), `measure-rto.py` (python3), `aggregate-rto.py` (python3)
- **Output contracts** — structured JSON at every phase handoff, markdown reports for human consumption
- **Manual gate** — compliance officer reviews attestation before finalization

## Requirements

### Tools (must be in PATH)
- `python3` with `pyyaml` (`pip install pyyaml`)
- `pg_restore` / `psql` — for PostgreSQL backup verification
- `rsync` — for filesystem backup verification
- `sqlite3` — for SQLite backup verification
- `sha256sum` — for checksum validation

### MCP Servers (auto-installed via npx)
- `@modelcontextprotocol/server-filesystem` — read/write config, logs, reports
- `@modelcontextprotocol/server-sequential-thinking` — structured reasoning for restore diagnosis and compliance mapping

### No API Keys Required
This pipeline uses only local CLI tools — no external API credentials needed.

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
│   ├── backup-sources.yaml     ← edit this to register your backups
│   ├── sla-policy.yaml         ← RTO thresholds and compliance mappings
│   └── verification-rules.yaml ← integrity check rules per backup type
├── scripts/
│   ├── execute-restores.sh     ← runs pg_restore / rsync / sqlite3 with timing
│   ├── measure-rto.py          ← computes RTO vs SLA, writes history.jsonl
│   └── aggregate-rto.py        ← weekly statistical aggregation
├── templates/                  ← report templates for agents
├── data/                       ← generated at runtime
│   ├── manifests/              ← daily execution manifests
│   ├── snapshots/              ← last-verified timestamps + checksum files
│   ├── restore-logs/           ← per-source restore timing and output
│   ├── integrity-results/      ← checksum and row count comparisons
│   ├── rto-measurements/       ← daily summaries + history.jsonl + weekly aggs
│   └── compliance-evidence/    ← monthly evidence packages
└── output/                     ← generated reports
    ├── daily-health-report.md
    ├── weekly-rto-trends.md
    ├── alerts/                 ← escalation alerts and GitHub issue templates
    └── monthly-attestation/    ← formal compliance packages
```
