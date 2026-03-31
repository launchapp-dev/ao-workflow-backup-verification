#!/usr/bin/env python3
"""
aggregate-rto.py — Aggregate RTO measurements from the past 7 days for weekly trend analysis.

Reads:
  - data/rto-measurements/history.jsonl  (all historical measurements)

Writes:
  - data/rto-measurements/weekly-YYYY-WW.json  (weekly aggregate by ISO week)
"""

import json
import os
import statistics
from datetime import date, timedelta

TODAY = date.today()
# ISO year and week number (e.g. "2026-13")
ISO_YEAR, ISO_WEEK, _ = TODAY.isocalendar()
WEEK_KEY = f"{ISO_YEAR}-{ISO_WEEK:02d}"

MEASUREMENTS_DIR = "data/rto-measurements"
HISTORY_FILE = f"{MEASUREMENTS_DIR}/history.jsonl"
WEEKLY_FILE = f"{MEASUREMENTS_DIR}/weekly-{WEEK_KEY}.json"

os.makedirs(MEASUREMENTS_DIR, exist_ok=True)


def load_history(days_back=7):
    cutoff = TODAY - timedelta(days=days_back)
    records = []
    if not os.path.exists(HISTORY_FILE):
        return records
    with open(HISTORY_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                rec_date = date.fromisoformat(rec["date"])
                if rec_date >= cutoff:
                    records.append(rec)
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
    return records


def compute_p95(values):
    if not values:
        return 0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * 0.95)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


def trend_direction(values):
    """Simple trend based on last 4 points via linear regression slope."""
    if len(values) < 2:
        return "stable"
    n = min(len(values), 4)
    pts = values[-n:]
    x_mean = (n - 1) / 2
    y_mean = statistics.mean(pts)
    numerator = sum((i - x_mean) * (pts[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return "stable"
    slope = numerator / denominator
    pct_change = (slope / y_mean * 100) if y_mean > 0 else 0
    if pct_change > 10:
        return "degrading"
    elif pct_change < -10:
        return "improving"
    else:
        return "stable"


def main():
    records = load_history(days_back=7)
    if not records:
        print(f"No history found in {HISTORY_FILE} for the past 7 days")
        return

    # Group by source_id
    by_source = {}
    for rec in records:
        sid = rec["source_id"]
        if sid not in by_source:
            by_source[sid] = []
        by_source[sid].append(rec)

    source_aggregates = []
    total_sla_breaches = 0

    for source_id, measurements in sorted(by_source.items()):
        rtimes = [m["rto_seconds"] for m in measurements]
        sla_s = measurements[0].get("sla_seconds", 300)
        adherent = [m for m in measurements if m["status"] == "within-sla"]
        breaches = [m for m in measurements if m["status"] == "exceeds-sla"]
        total_sla_breaches += len(breaches)

        # Sort by date for trend calculation
        sorted_by_date = sorted(measurements, key=lambda x: x["date"])
        rto_by_date = [m["rto_seconds"] for m in sorted_by_date]

        agg = {
            "source_id": source_id,
            "week": WEEK_KEY,
            "measurement_count": len(measurements),
            "sla_seconds": sla_s,
            "rto_min": min(rtimes),
            "rto_max": max(rtimes),
            "rto_avg": round(statistics.mean(rtimes), 1),
            "rto_p95": compute_p95(rtimes),
            "sla_adherence_rate_pct": round(len(adherent) / len(measurements) * 100, 1),
            "sla_breach_count": len(breaches),
            "avg_sla_pct_consumed": round(
                statistics.mean(m["sla_pct_consumed"] for m in measurements), 1
            ),
            "trend": trend_direction(rto_by_date),
        }
        source_aggregates.append(agg)
        print(
            f"  {source_id}: avg={agg['rto_avg']}s p95={agg['rto_p95']}s "
            f"adherence={agg['sla_adherence_rate_pct']}% trend={agg['trend']}"
        )

    overall_trend_values = [a["rto_avg"] for a in source_aggregates]
    overall_trend = trend_direction(overall_trend_values) if len(overall_trend_values) > 1 else "stable"

    weekly_summary = {
        "week": WEEK_KEY,
        "period_start": (TODAY - timedelta(days=6)).isoformat(),
        "period_end": TODAY.isoformat(),
        "sources": source_aggregates,
        "total_measurements": len(records),
        "total_sla_breaches": total_sla_breaches,
        "overall_trend": overall_trend,
    }

    with open(WEEKLY_FILE, "w") as f:
        json.dump(weekly_summary, f, indent=2)

    print(f"\nWeekly aggregate written to {WEEKLY_FILE}")
    print(f"Overall trend: {overall_trend}, total SLA breaches: {total_sla_breaches}")


if __name__ == "__main__":
    main()
