"""
Mandatory Scenario 2: Spend Anomaly Diagnosis
==============================================
When costs spike (e.g., cloud infra +40% MoM), this agent:
1. Ingests time-series spend data by category/resource
2. Diagnoses root cause: provisioning error vs seasonal traffic vs autoscaling misconfiguration
3. Recommends (or executes) the appropriate corrective action per root cause

Two-stage reasoning:
  Stage 1 (statistical): Detect anomaly, compute magnitude, check seasonality baseline
  Stage 2 (AI): Diagnose cause from pattern signatures, recommend action

Usage:
    python spend_anomaly.py --data spend_timeseries.csv
    python spend_anomaly.py --demo

CSV Format:
    date (YYYY-MM-DD), category, resource_id, cost_inr, unit_count, notes
"""

import json
import argparse
import csv
import os
import statistics
from datetime import datetime, date, timedelta
from collections import defaultdict

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


# ─────────────────────────────────────────────
# DATA LOADER
# ─────────────────────────────────────────────

def load_timeseries(filepath: str) -> list[dict]:
    records = []
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({
                "date":        row.get("date", ""),
                "category":    row.get("category", "").strip().lower(),
                "resource_id": row.get("resource_id", ""),
                "cost_inr":    float(row.get("cost_inr", 0) or 0),
                "unit_count":  float(row.get("unit_count", 0) or 0),
                "notes":       row.get("notes", ""),
            })
    return records


def generate_demo_data() -> list[dict]:
    """Generate a realistic cloud spend time series with a deliberate anomaly."""
    today = date.today()
    records = []

    # 90 days of baseline data + anomaly in last 30 days
    categories = {
        "ec2_compute":   {"base": 120000, "variance": 0.05},
        "s3_storage":    {"base": 45000,  "variance": 0.03},
        "rds_database":  {"base": 80000,  "variance": 0.02},
        "data_transfer": {"base": 30000,  "variance": 0.08},
        "lambda":        {"base": 15000,  "variance": 0.10},
    }

    for day_offset in range(90):
        d = today - timedelta(days=89 - day_offset)
        for cat, params in categories.items():
            base = params["base"]
            import random
            random.seed(day_offset * 7 + hash(cat) % 100)
            noise = random.gauss(0, base * params["variance"])

            # Inject anomaly: ec2_compute spikes +40% in last 30 days due to autoscaling bug
            if cat == "ec2_compute" and day_offset >= 60:
                base = base * 1.42  # +42% spike
                notes = "autoscaling_group_misconfigured" if day_offset == 60 else ""
            else:
                notes = ""

            cost = max(0, base + noise)
            unit = cost / 0.12  # fake unit count

            records.append({
                "date":        d.isoformat(),
                "category":    cat,
                "resource_id": f"{cat.upper()}-001",
                "cost_inr":    round(cost, 2),
                "unit_count":  round(unit, 0),
                "notes":       notes,
            })

    return records


# ─────────────────────────────────────────────
# STAGE 1: STATISTICAL ANOMALY DETECTION
# ─────────────────────────────────────────────

def aggregate_monthly(records: list[dict]) -> dict:
    """Aggregate spend by category × month."""
    monthly = defaultdict(lambda: defaultdict(float))
    for r in records:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d")
            month_key = f"{d.year}-{d.month:02d}"
            monthly[r["category"]][month_key] += r["cost_inr"]
        except:
            pass
    return monthly


def detect_anomalies(monthly: dict, spike_threshold: float = 0.20) -> list[dict]:
    """Identify categories with MoM spend spikes above threshold."""
    anomalies = []
    for category, months in monthly.items():
        sorted_months = sorted(months.items())
        if len(sorted_months) < 2:
            continue

        for i in range(1, len(sorted_months)):
            prev_month, prev_cost = sorted_months[i - 1]
            curr_month, curr_cost = sorted_months[i]

            if prev_cost == 0:
                continue

            pct_change = (curr_cost - prev_cost) / prev_cost

            if abs(pct_change) >= spike_threshold:
                # Compute historical baseline (all prior months)
                prior_costs = [v for _, v in sorted_months[:i]]
                baseline_avg = statistics.mean(prior_costs) if prior_costs else prev_cost
                baseline_std = statistics.stdev(prior_costs) if len(prior_costs) > 1 else 0
                z_score = (curr_cost - baseline_avg) / baseline_std if baseline_std > 0 else 0

                anomalies.append({
                    "category":           category,
                    "prev_month":         prev_month,
                    "curr_month":         curr_month,
                    "prev_cost_inr":      round(prev_cost, 2),
                    "curr_cost_inr":      round(curr_cost, 2),
                    "pct_change":         round(pct_change * 100, 2),
                    "excess_spend_inr":   round(curr_cost - prev_cost, 2),
                    "baseline_avg_inr":   round(baseline_avg, 2),
                    "z_score":            round(z_score, 2),
                    "severity":           "CRITICAL" if abs(pct_change) > 0.40 else "HIGH" if abs(pct_change) > 0.25 else "MEDIUM",
                    "direction":          "SPIKE" if pct_change > 0 else "DROP",
                })

    return sorted(anomalies, key=lambda x: abs(x["excess_spend_inr"]), reverse=True)


def analyze_resource_breakdown(records: list[dict], anomalous_categories: list[str],
                                 curr_month: str) -> dict:
    """For anomalous categories, break down which resources drove the spike."""
    breakdown = defaultdict(lambda: defaultdict(float))
    for r in records:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d")
            month_key = f"{d.year}-{d.month:02d}"
        except:
            continue

        if r["category"] in anomalous_categories and month_key == curr_month:
            breakdown[r["category"]][r["resource_id"]] += r["cost_inr"]

    return {cat: dict(sorted(res.items(), key=lambda x: x[1], reverse=True))
            for cat, res in breakdown.items()}


# ─────────────────────────────────────────────
# STAGE 2: AI ROOT CAUSE DIAGNOSIS
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an enterprise cost intelligence agent specializing in cloud and infrastructure spend anomaly diagnosis.

You will receive statistical anomaly data showing which cost categories spiked and by how much.
Your job is to:

1. Diagnose the most likely root cause for each anomaly from these possibilities:
   - PROVISIONING_ERROR: Someone spun up resources and forgot to tear them down
   - AUTOSCALING_MISCONFIGURATION: Autoscaling rules triggered incorrectly or have no ceiling
   - SEASONAL_TRAFFIC: Legitimate demand increase (check if it's a known peak period)
   - SECURITY_INCIDENT: Cryptomining, data exfiltration, unauthorized access
   - PRICING_CHANGE: Vendor rate change, reserved instance expiry
   - DATA_PIPELINE_RUNAWAY: A job ran in an infinite loop or processed data multiple times
   - UNKNOWN: Cannot determine from available data

2. For each root cause, recommend the SPECIFIC corrective action:
   - PROVISIONING_ERROR → List the top unused resources, auto-terminate if spend > threshold
   - AUTOSCALING_MISCONFIGURATION → Set max_instances cap, review scaling policy, rollback
   - SEASONAL_TRAFFIC → Accept cost, project forward, pre-negotiate capacity discounts
   - SECURITY_INCIDENT → Isolate resource immediately, escalate to security team
   - PRICING_CHANGE → Renegotiate contract, switch provider, or buy reserved instances
   - DATA_PIPELINE_RUNAWAY → Kill job, identify checkpoint, re-run from last clean state

3. For each anomaly: state what EVIDENCE supports the diagnosis and what EVIDENCE is missing

4. Estimate: if the root cause is fixed NOW vs. next month, what is the financial difference?

OUTPUT FORMAT — respond ONLY with valid JSON, no markdown, no preamble:
{
  "analysis_date": "YYYY-MM-DD",
  "total_excess_spend_identified_inr": 0.00,
  "total_recoverable_inr": 0.00,
  "diagnoses": [
    {
      "category": "...",
      "root_cause": "AUTOSCALING_MISCONFIGURATION",
      "confidence": "HIGH | MEDIUM | LOW",
      "evidence_supporting": ["..."],
      "evidence_missing": ["..."],
      "pct_change": 0.0,
      "excess_spend_inr": 0.00,
      "corrective_action": "...",
      "execution_mode": "AUTO_EXECUTE | STAGE_FOR_APPROVAL | ESCALATE",
      "cost_if_fixed_now_inr": 0.00,
      "cost_if_fixed_next_month_inr": 0.00,
      "urgency": "IMMEDIATE | 24_HOURS | 7_DAYS"
    }
  ],
  "recommended_monitoring": ["..."]
}"""


def run_ai_diagnosis(anomalies: list[dict], breakdown: dict, all_records: list[dict],
                     api_key: str) -> dict:
    client = anthropic.Anthropic(api_key=api_key)

    # Include some raw time-series context for top anomalous category
    top_cat = anomalies[0]["category"] if anomalies else None
    ts_sample = []
    if top_cat:
        for r in all_records:
            if r["category"] == top_cat:
                ts_sample.append({"date": r["date"], "cost": r["cost_inr"], "notes": r["notes"]})
        ts_sample = ts_sample[-60:]  # Last 60 days

    payload = {
        "anomalies":         anomalies,
        "resource_breakdown": breakdown,
        "timeseries_sample": ts_sample,
        "today":             date.today().isoformat(),
    }

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content":
            f"Diagnose these spend anomalies and recommend corrective actions:\n{json.dumps(payload, indent=2, default=str)}"}]
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ─────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────

def print_report(anomalies, ai_result=None):
    total_excess = sum(a["excess_spend_inr"] for a in anomalies if a["direction"] == "SPIKE")

    print("\n" + "═" * 65)
    print("  📈 SPEND ANOMALY DIAGNOSIS REPORT")
    print("═" * 65)
    print(f"  Anomalies detected    : {len(anomalies)}")
    print(f"  Total excess spend    : ₹{total_excess:>12,.2f}")
    print("─" * 65)

    if ai_result:
        print(f"  AI Recoverable        : ₹{ai_result.get('total_recoverable_inr', 0):>12,.2f}")
        print("\n  ROOT CAUSE DIAGNOSES:\n")
        for d in ai_result.get("diagnoses", []):
            icon = {"AUTOSCALING_MISCONFIGURATION": "⚙️ ", "PROVISIONING_ERROR": "🔧",
                    "SEASONAL_TRAFFIC": "📅", "SECURITY_INCIDENT": "🚨",
                    "PRICING_CHANGE": "💰", "DATA_PIPELINE_RUNAWAY": "🔄"}.get(d["root_cause"], "❓")
            print(f"  {icon} [{d['urgency']:<12}] {d['category'].upper()}")
            print(f"       Root cause  : {d['root_cause']} ({d['confidence']} confidence)")
            print(f"       Excess spend: ₹{d['excess_spend_inr']:,.0f}")
            print(f"       Action      : {d['corrective_action'][:70]}")
            print(f"       Mode        : {d['execution_mode']}")
            if d.get("evidence_supporting"):
                print(f"       Evidence    : {d['evidence_supporting'][0]}")
            print()
    else:
        for a in anomalies[:5]:
            print(f"  {'🔺' if a['direction']=='SPIKE' else '🔻'} {a['category'].upper():<20} "
                  f"{a['pct_change']:>+.1f}%  Excess: ₹{a['excess_spend_inr']:,.0f}  [{a['severity']}]")

    print("═" * 65 + "\n")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Spend Anomaly Diagnosis Agent")
    parser.add_argument("--data",      help="Path to spend time-series CSV")
    parser.add_argument("--demo",      action="store_true")
    parser.add_argument("--threshold", type=float, default=0.20, help="MoM spike threshold (default 0.20 = 20%)")
    parser.add_argument("--output",    default="spend_anomaly_report.json")
    parser.add_argument("--api-key",   help="Anthropic API key")
    args = parser.parse_args()

    if args.data:
        records = load_timeseries(args.data)
    else:
        print("🧪 Demo mode: generating 90-day cloud spend data with autoscaling anomaly\n")
        records = generate_demo_data()

    print(f"✅ Loaded {len(records)} spend records")

    monthly   = aggregate_monthly(records)
    anomalies = detect_anomalies(monthly, spike_threshold=args.threshold)
    print(f"🔍 Detected {len(anomalies)} anomalies above {args.threshold*100:.0f}% threshold")

    # Get the most recent anomalous month for breakdown
    curr_month = anomalies[0]["curr_month"] if anomalies else ""
    anomalous_cats = [a["category"] for a in anomalies]
    breakdown = analyze_resource_breakdown(records, anomalous_cats, curr_month)

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    ai_result = None
    if api_key and ANTHROPIC_AVAILABLE and anomalies:
        print("🤖 Running AI root cause diagnosis...")
        ai_result = run_ai_diagnosis(anomalies, breakdown, records, api_key)

    print_report(anomalies, ai_result)

    output = {"anomalies": anomalies, "resource_breakdown": breakdown, "ai_diagnosis": ai_result}
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"💾 Report saved to: {args.output}")


if __name__ == "__main__":
    main()
