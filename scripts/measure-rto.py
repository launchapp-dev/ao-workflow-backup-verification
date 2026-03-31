#!/usr/bin/env python3
"""
measure-rto.py — Compute RTO metrics for today's restore runs and compare against SLA targets.

Reads:
  - data/restore-logs/YYYY-MM-DD/<source_id>.json  (restore timing)
  - config/sla-policy.yaml                          (RTO thresholds)
  - config/backup-sources.yaml                      (SLA targets per source)

Writes:
  - data/rto-measurements/YYYY-MM-DD-summary.json  (daily summary)
  - data/rto-measurements/history.jsonl            (appended — one line per source per day)
"""

import json
import os
import yaml
import glob
from datetime import date

TODAY = date.today().isoformat()  # e.g. "2026-03-31"
LOG_DIR = f"data/restore-logs/{TODAY}"
MEASUREMENTS_DIR = "data/rto-measurements"
SUMMARY_FILE = f"{MEASUREMENTS_DIR}/{TODAY}-summary.json"
HISTORY_FILE = f"{MEASUREMENTS_DIR}/history.jsonl"

os.makedirs(MEASUREMENTS_DIR, exist_ok=True)


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_sla_targets():
    """Build a dict of source_id -> sla_rto_seconds from backup-sources.yaml."""
    config = load_yaml("config/backup-sources.yaml")
    return {s["id"]: s.get("sla_rto_seconds", 300) for s in config["backup_sources"]}


def load_thresholds():
    policy = load_yaml("config/sla-policy.yaml")
    t = policy["rto_thresholds"]
    return t["within_sla_pct"], t["approaching_limit_pct"]


def compute_status(actual_s, sla_s, within_pct, approaching_pct):
    if sla_s <= 0:
        return "within-sla", 0.0
    pct = (actual_s / sla_s) * 100
    if pct < within_pct:
        return "within-sla", round(pct, 1)
    elif pct <= approaching_pct:
        return "approaching-limit", round(pct, 1)
    else:
        return "exceeds-sla", round(pct, 1)


def main():
    sla_targets = load_sla_targets()
    within_pct, approaching_pct = load_thresholds()

    log_files = glob.glob(f"{LOG_DIR}/*.json")
    if not log_files:
        print(f"No restore logs found in {LOG_DIR} — nothing to measure")
        return

    source_measurements = []
    overall_worst = "within-sla"

    for log_file in sorted(log_files):
        source_id = os.path.basename(log_file).replace(".json", "")
        if source_id == "restore-operator-summary":
            continue

        with open(log_file) as f:
            log = json.load(f)

        actual_s = log.get("restore_duration_seconds", 0)
        sla_s = sla_targets.get(source_id, 300)
        status, pct = compute_status(actual_s, sla_s, within_pct, approaching_pct)

        measurement = {
            "date": TODAY,
            "source_id": source_id,
            "rto_seconds": actual_s,
            "sla_seconds": sla_s,
            "sla_pct_consumed": pct,
            "status": status,
            "restore_exit_code": log.get("exit_code", -1),
        }
        source_measurements.append(measurement)

        # Track overall worst status
        status_rank = {"within-sla": 0, "approaching-limit": 1, "exceeds-sla": 2}
        if status_rank.get(status, 0) > status_rank.get(overall_worst, 0):
            overall_worst = status

        # Append to history JSONL
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(measurement) + "\n")

        print(f"  {source_id}: {actual_s}s / {sla_s}s SLA ({pct}%) → {status}")

    # Write daily summary
    summary = {
        "date": TODAY,
        "sources": source_measurements,
        "overall_status": overall_worst,
        "total_sources": len(source_measurements),
        "within_sla": sum(1 for m in source_measurements if m["status"] == "within-sla"),
        "approaching_limit": sum(1 for m in source_measurements if m["status"] == "approaching-limit"),
        "exceeds_sla": sum(1 for m in source_measurements if m["status"] == "exceeds-sla"),
    }

    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nRTO summary written to {SUMMARY_FILE}")
    print(f"Overall status: {overall_worst}")
    print(f"History appended to {HISTORY_FILE}")


if __name__ == "__main__":
    main()
