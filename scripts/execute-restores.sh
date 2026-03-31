#!/usr/bin/env bash
# execute-restores.sh — Run restore-to-test for each backup source in today's manifest
# Reads: data/manifests/YYYY-MM-DD-manifest.json
# Writes: data/restore-logs/YYYY-MM-DD/<source_id>.json

set -euo pipefail

TODAY=$(date +%Y-%m-%d)
MANIFEST="data/manifests/${TODAY}-manifest.json"
LOG_DIR="data/restore-logs/${TODAY}"

if [[ ! -f "$MANIFEST" ]]; then
  echo "ERROR: No manifest found at $MANIFEST — run identify-due-backups first" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

# Parse source IDs from manifest
SOURCE_IDS=$(python3 -c "
import json, sys
with open('$MANIFEST') as f:
    m = json.load(f)
for s in m.get('sources', []):
    print(s['source_id'] + '|' + s['backup_type'] + '|' + s['backup_path'] + '|' + str(s['sla_rto_seconds']))
")

EXIT_SUMMARY=0

while IFS='|' read -r SOURCE_ID BACKUP_TYPE BACKUP_PATH SLA_RTO; do
  echo "→ Restoring $SOURCE_ID ($BACKUP_TYPE) from $BACKUP_PATH"

  RESTORE_START=$(date +%s)
  RESTORE_START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  STDOUT_FILE=$(mktemp)
  STDERR_FILE=$(mktemp)
  EXIT_CODE=0

  case "$BACKUP_TYPE" in
    postgresql)
      TEST_DB=$(python3 -c "
import json
with open('$MANIFEST') as f:
    m = json.load(f)
for s in m['sources']:
    if s['source_id'] == '$SOURCE_ID':
        print(s.get('test_restore_db', 'test_restore_default'))
")
      # Restore the dump into the test database
      pg_restore \
        --dbname="$TEST_DB" \
        --clean \
        --if-exists \
        "$BACKUP_PATH" \
        >"$STDOUT_FILE" 2>"$STDERR_FILE" || EXIT_CODE=$?

      # Get row counts for each table to verify
      TABLES=$(python3 -c "
import json
with open('$MANIFEST') as f:
    m = json.load(f)
for s in m['sources']:
    if s['source_id'] == '$SOURCE_ID':
        print(' '.join(s.get('tables_to_verify', [])))
")
      ROW_COUNTS="{}"
      if [[ $EXIT_CODE -eq 0 ]] && [[ -n "$TABLES" ]]; then
        ROW_COUNTS=$(python3 -c "
import subprocess, json
tables = '$TABLES'.split()
counts = {}
for t in tables:
    result = subprocess.run(
        ['psql', '--dbname=$TEST_DB', '-t', '-c', f'SELECT count(*) FROM {t}'],
        capture_output=True, text=True
    )
    counts[t] = int(result.stdout.strip()) if result.returncode == 0 else -1
print(json.dumps(counts))
" 2>/dev/null || echo "{}")
      fi
      ;;

    filesystem)
      TEST_RESTORE_PATH=$(python3 -c "
import json
with open('$MANIFEST') as f:
    m = json.load(f)
for s in m['sources']:
    if s['source_id'] == '$SOURCE_ID':
        print(s.get('test_restore_path', '/tmp/test-restore/$SOURCE_ID/'))
")
      mkdir -p "$TEST_RESTORE_PATH"
      rsync \
        --checksum \
        --archive \
        --delete \
        "$BACKUP_PATH" \
        "$TEST_RESTORE_PATH" \
        >"$STDOUT_FILE" 2>"$STDERR_FILE" || EXIT_CODE=$?

      ROW_COUNTS="{}"
      ;;

    sqlite)
      TEST_PATH=$(python3 -c "
import json
with open('$MANIFEST') as f:
    m = json.load(f)
for s in m['sources']:
    if s['source_id'] == '$SOURCE_ID':
        print(s.get('test_restore_path', '/tmp/test-restore/$SOURCE_ID.db'))
")
      cp "$BACKUP_PATH" "$TEST_PATH" >"$STDOUT_FILE" 2>"$STDERR_FILE" || EXIT_CODE=$?

      TABLES=$(python3 -c "
import json
with open('$MANIFEST') as f:
    m = json.load(f)
for s in m['sources']:
    if s['source_id'] == '$SOURCE_ID':
        print(' '.join(s.get('tables_to_verify', [])))
")
      ROW_COUNTS="{}"
      if [[ $EXIT_CODE -eq 0 ]] && [[ -n "$TABLES" ]]; then
        ROW_COUNTS=$(python3 -c "
import subprocess, json
tables = '$TABLES'.split()
counts = {}
for t in tables:
    result = subprocess.run(
        ['sqlite3', '$TEST_PATH', f'SELECT count(*) FROM {t};'],
        capture_output=True, text=True
    )
    counts[t] = int(result.stdout.strip()) if result.returncode == 0 else -1
print(json.dumps(counts))
" 2>/dev/null || echo "{}")
      fi
      ;;

    *)
      echo "WARN: Unknown backup type '$BACKUP_TYPE' for $SOURCE_ID — skipping" >&2
      EXIT_CODE=1
      ;;
  esac

  RESTORE_END=$(date +%s)
  RESTORE_END_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  RESTORE_DURATION=$((RESTORE_END - RESTORE_START))

  STDOUT_TAIL=$(tail -20 "$STDOUT_FILE" 2>/dev/null | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" || echo '""')
  STDERR_TAIL=$(tail -20 "$STDERR_FILE" 2>/dev/null | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" || echo '""')

  python3 -c "
import json
data = {
    'source_id': '$SOURCE_ID',
    'backup_type': '$BACKUP_TYPE',
    'restore_start': '$RESTORE_START_ISO',
    'restore_end': '$RESTORE_END_ISO',
    'restore_duration_seconds': $RESTORE_DURATION,
    'exit_code': $EXIT_CODE,
    'row_counts': $ROW_COUNTS,
    'stdout_tail': $STDOUT_TAIL,
    'stderr_tail': $STDERR_TAIL
}
with open('$LOG_DIR/$SOURCE_ID.json', 'w') as f:
    json.dump(data, f, indent=2)
print('  Wrote $LOG_DIR/$SOURCE_ID.json')
"

  if [[ $EXIT_CODE -ne 0 ]]; then
    echo "  FAILED: $SOURCE_ID (exit $EXIT_CODE)"
    EXIT_SUMMARY=1
  else
    echo "  OK: $SOURCE_ID in ${RESTORE_DURATION}s (SLA: ${SLA_RTO}s)"
  fi

  rm -f "$STDOUT_FILE" "$STDERR_FILE"

done <<< "$SOURCE_IDS"

echo "Restores complete. Results in $LOG_DIR/"
exit $EXIT_SUMMARY
