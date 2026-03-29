"""
Mandatory Scenario 3: SLA Penalty Prevention
=============================================
When a service team is trending toward missing a contractual SLA with days remaining:
1. Projects the shortfall (will they miss? by how much?)
2. Identifies which tasks to reprioritize to recover
3. Either reassigns resources autonomously (low risk) OR escalates with specific recovery plan

Usage:
    python sla_sentinel.py --tasks tasks.csv --sla sla_config.json
    python sla_sentinel.py --demo

CSV Format (tasks.csv):
    task_id, task_name, priority, status, estimated_hours, completed_hours, assigned_to, deadline, sla_category

JSON Format (sla_config.json):
    {"sla_name": "...", "deadline": "YYYY-MM-DD", "completion_target_pct": 95, "penalty_per_day_inr": 100000}
"""

import json
import argparse
import csv
import os
from datetime import datetime, date, timedelta
from collections import defaultdict

try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


# ─────────────────────────────────────────────
# DATA LOADERS
# ─────────────────────────────────────────────

def load_tasks(filepath: str) -> list[dict]:
    tasks = []
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            tasks.append({
                "task_id":         row.get("task_id", ""),
                "task_name":       row.get("task_name", ""),
                "priority":        row.get("priority", "MEDIUM").upper(),
                "status":          row.get("status", "IN_PROGRESS").upper(),
                "estimated_hours": float(row.get("estimated_hours", 0) or 0),
                "completed_hours": float(row.get("completed_hours", 0) or 0),
                "assigned_to":     row.get("assigned_to", "Unassigned"),
                "deadline":        row.get("deadline", ""),
                "sla_category":    row.get("sla_category", "standard"),
            })
    return tasks


DEMO_TASKS = [
    {"task_id": "T001", "task_name": "Customer data migration",      "priority": "CRITICAL", "status": "IN_PROGRESS", "estimated_hours": 40, "completed_hours": 28, "assigned_to": "Ravi Kumar",  "deadline": "", "sla_category": "data"},
    {"task_id": "T002", "task_name": "API endpoint testing",         "priority": "HIGH",     "status": "IN_PROGRESS", "estimated_hours": 16, "completed_hours": 6,  "assigned_to": "Priya Singh", "deadline": "", "sla_category": "qa"},
    {"task_id": "T003", "task_name": "Security audit review",        "priority": "HIGH",     "status": "NOT_STARTED", "estimated_hours": 24, "completed_hours": 0,  "assigned_to": "Amit Sharma", "deadline": "", "sla_category": "compliance"},
    {"task_id": "T004", "task_name": "Load balancer configuration",  "priority": "CRITICAL", "status": "DONE",        "estimated_hours": 8,  "completed_hours": 8,  "assigned_to": "Neha Gupta",  "deadline": "", "sla_category": "infra"},
    {"task_id": "T005", "task_name": "Performance benchmarking",     "priority": "MEDIUM",   "status": "IN_PROGRESS", "estimated_hours": 12, "completed_hours": 4,  "assigned_to": "Rohit Mehta", "deadline": "", "sla_category": "qa"},
    {"task_id": "T006", "task_name": "Documentation update",         "priority": "LOW",      "status": "NOT_STARTED", "estimated_hours": 8,  "completed_hours": 0,  "assigned_to": "Priya Singh", "deadline": "", "sla_category": "docs"},
    {"task_id": "T007", "task_name": "Database index optimization",  "priority": "HIGH",     "status": "IN_PROGRESS", "estimated_hours": 20, "completed_hours": 10, "assigned_to": "Ravi Kumar",  "deadline": "", "sla_category": "data"},
    {"task_id": "T008", "task_name": "UI regression testing",        "priority": "MEDIUM",   "status": "NOT_STARTED", "estimated_hours": 16, "completed_hours": 0,  "assigned_to": "Amit Sharma", "deadline": "", "sla_category": "qa"},
    {"task_id": "T009", "task_name": "Failover configuration",       "priority": "CRITICAL", "status": "IN_PROGRESS", "estimated_hours": 10, "completed_hours": 3,  "assigned_to": "Neha Gupta",  "deadline": "", "sla_category": "infra"},
    {"task_id": "T010", "task_name": "Stakeholder sign-off meeting", "priority": "HIGH",     "status": "NOT_STARTED", "estimated_hours": 4,  "completed_hours": 0,  "assigned_to": "Rohit Mehta", "deadline": "", "sla_category": "governance"},
]

DEMO_SLA = {
    "sla_name":              "Phase 2 System Delivery",
    "deadline":              (date.today() + timedelta(days=3)).isoformat(),
    "completion_target_pct": 95,
    "penalty_per_day_inr":   150000,
    "max_penalty_inr":       1500000,
    "team_hours_per_day":    8,
    "team_size":             5,
}


# ─────────────────────────────────────────────
# STAGE 1: SLA PROJECTION
# ─────────────────────────────────────────────

def compute_sla_status(tasks: list[dict], sla: dict) -> dict:
    today = date.today()
    try:
        deadline = datetime.strptime(sla["deadline"], "%Y-%m-%d").date()
    except Exception:
        deadline = today + timedelta(days=3)

    days_remaining       = (deadline - today).days
    total_hours_est      = sum(t["estimated_hours"] for t in tasks)
    total_hours_done     = sum(t["completed_hours"] for t in tasks)
    total_hours_remaining = sum(
        max(0, t["estimated_hours"] - t["completed_hours"])
        for t in tasks if t["status"] != "DONE"
    )
    pct_complete = (total_hours_done / total_hours_est * 100) if total_hours_est > 0 else 0

    team_capacity_hours = (days_remaining
                           * sla.get("team_hours_per_day", 8)
                           * sla.get("team_size", 5))
    shortfall_hours = total_hours_remaining - team_capacity_hours
    will_miss       = shortfall_hours > 0

    critical_remaining = [
        t for t in tasks
        if t["priority"] in ("CRITICAL", "HIGH") and t["status"] != "DONE"
    ]
    critical_hours_remaining = sum(
        max(0, t["estimated_hours"] - t["completed_hours"])
        for t in critical_remaining
    )

    penalty_per_day = sla.get("penalty_per_day_inr", 0)
    max_penalty     = sla.get("max_penalty_inr", penalty_per_day * 10)

    if will_miss and days_remaining >= 0:
        hours_per_day     = sla.get("team_hours_per_day", 8) * sla.get("team_size", 5)
        days_late         = (shortfall_hours / hours_per_day) if hours_per_day > 0 else 1
        projected_penalty = min(max_penalty, round(days_late * penalty_per_day, 0))
    else:
        days_late         = 0
        projected_penalty = 0

    return {
        "sla_name":                 sla.get("sla_name", "SLA"),
        "deadline":                  deadline.isoformat(),
        "days_remaining":           days_remaining,
        "pct_complete":             round(pct_complete, 1),
        "target_pct":               sla.get("completion_target_pct", 95),
        "total_hours_estimated":    total_hours_est,
        "total_hours_done":         total_hours_done,
        "total_hours_remaining":    total_hours_remaining,
        "team_capacity_hours":      team_capacity_hours,
        "shortfall_hours":          round(max(0, shortfall_hours), 1),
        "will_miss_sla":            will_miss,
        "estimated_days_late":      round(days_late, 1),
        "projected_penalty_inr":    projected_penalty,
        "max_penalty_inr":          max_penalty,
        "critical_tasks_remaining": len(critical_remaining),
        "critical_hours_remaining": critical_hours_remaining,
        "risk_level":               ("CRITICAL" if days_remaining <= 2 and will_miss else
                                     "HIGH"     if days_remaining <= 5 and will_miss else
                                     "MEDIUM"   if will_miss else "LOW"),
    }


def identify_reassignment_options(tasks: list[dict], sla_status: dict) -> dict:
    deferrable = [
        t for t in tasks
        if t["priority"] in ("LOW", "MEDIUM") and t["status"] == "NOT_STARTED"
    ]

    low_priority_assignments = defaultdict(list)
    for t in tasks:
        if t["priority"] == "LOW" and t["status"] in ("IN_PROGRESS", "NOT_STARTED"):
            low_priority_assignments[t["assigned_to"]].append(t)

    at_risk_critical = [
        t for t in tasks
        if t["priority"] in ("CRITICAL", "HIGH") and t["status"] != "DONE"
        and (t["completed_hours"] / t["estimated_hours"] < 0.5
             if t["estimated_hours"] > 0 else True)
    ]

    hours_reclaimable = sum(
        t["estimated_hours"] - t["completed_hours"] for t in deferrable
    )

    return {
        "deferrable_tasks":       deferrable,
        "hours_reclaimable":      round(hours_reclaimable, 1),
        "low_priority_workers":   dict(low_priority_assignments),
        "at_risk_critical_tasks": at_risk_critical,
        "reassignment_feasible":  hours_reclaimable >= sla_status["shortfall_hours"] * 0.8,
    }


# ─────────────────────────────────────────────
# STAGE 2: AI RECOVERY PLANNING (google-genai SDK)
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an enterprise SLA and project delivery intelligence agent.

You will receive:
- Current SLA status (days remaining, shortfall, penalty at risk)
- Full task list with priorities, assignees, and completion status
- Reassignment options identified by rule-based analysis

Your job is to:
1. Confirm the SLA breach risk and exact penalty exposure
2. Produce a specific RECOVERY PLAN with exact task reassignments (who moves from what to what)
3. For each recovery action, specify:
   - execution_mode: AUTO_EXECUTE (low risk, clear owner) | STAGE_FOR_APPROVAL (budget/headcount) | ESCALATE (needs management)
   - approval_level: TEAM_LEAD | PROJECT_MANAGER | DIRECTOR
4. Calculate: penalty saved if plan is executed TODAY vs not executed
5. If the plan still cannot close the shortfall, recommend escalation with a specific message

OUTPUT FORMAT - respond ONLY with valid JSON, no markdown, no preamble:
{
  "breach_confirmed": true,
  "projected_penalty_inr": 0.00,
  "penalty_preventable_inr": 0.00,
  "recovery_feasible": true,
  "recovery_confidence": "HIGH",
  "recovery_plan": [
    {
      "action_id": 1,
      "action_type": "REASSIGN",
      "description": "Move Priya Singh from Documentation (T006) to API Testing (T002)",
      "from_task_id": "T006",
      "to_task_id": "T002",
      "assignee": "Priya Singh",
      "hours_reclaimed": 8.0,
      "execution_mode": "AUTO_EXECUTE",
      "approval_level": "TEAM_LEAD",
      "financial_impact_inr": 0.00
    }
  ],
  "escalation_message": "...",
  "post_recovery_completion_pct": 0.0,
  "remaining_risk": "..."
}"""


def run_ai_recovery_plan(tasks, sla_status, options, api_key: str) -> dict:
    if not GEMINI_AVAILABLE:
        raise ImportError("google-genai is not installed. Run: pip install google-genai")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required")

    client = genai.Client(api_key=api_key)

    payload = {
        "sla_status":           sla_status,
        "all_tasks":            tasks,
        "reassignment_options": options,
    }

    full_prompt = (SYSTEM_PROMPT
                   + "\n\nAnalyze this SLA breach risk and produce a specific recovery plan:\n"
                   + json.dumps(payload, indent=2, default=str))

    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=full_prompt,
        config=genai_types.GenerateContentConfig(max_output_tokens=3000),
    )

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ─────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────

def print_report(tasks, sla_status, options, ai_result=None):
    print("\n" + "=" * 65)
    print("  SLA PENALTY PREVENTION REPORT")
    print("=" * 65)
    status_tag = "[BREACH RISK]" if sla_status["will_miss_sla"] else "[ON TRACK]"
    print(f"  {status_tag} SLA: {sla_status['sla_name']}")
    print(f"  Deadline          : {sla_status['deadline']} ({sla_status['days_remaining']} days remaining)")
    print(f"  Current completion: {sla_status['pct_complete']:.1f}% / target {sla_status['target_pct']}%")
    print(f"  Hours remaining   : {sla_status['total_hours_remaining']:.0f}h  |  Capacity: {sla_status['team_capacity_hours']:.0f}h")
    print(f"  Shortfall         : {sla_status['shortfall_hours']:.0f}h  |  Est. days late: {sla_status['estimated_days_late']:.1f}")
    print(f"  Penalty at risk   : Rs {sla_status['projected_penalty_inr']:,.0f}  [MAX: Rs {sla_status['max_penalty_inr']:,.0f}]")
    print(f"  Risk level        : {sla_status['risk_level']}")
    print("-" * 65)
    print(f"  Reclaimable hours from deferral: {options['hours_reclaimable']:.0f}h  |  "
          f"Feasible: {'YES' if options['reassignment_feasible'] else 'NO'}")
    print("-" * 65)

    if ai_result:
        feasible_tag = "[RECOVERY FEASIBLE]" if ai_result.get("recovery_feasible") else "[RECOVERY NOT FEASIBLE]"
        print(f"\n  {feasible_tag} Confidence: {ai_result.get('recovery_confidence', '?')}")
        print(f"  Penalty preventable: Rs {ai_result.get('penalty_preventable_inr', 0):,.0f}")
        print(f"\n  RECOVERY PLAN ({len(ai_result.get('recovery_plan', []))} actions):\n")
        for a in ai_result.get("recovery_plan", []):
            mode_tag = {"AUTO_EXECUTE": "[AUTO]", "STAGE_FOR_APPROVAL": "[APPROVAL]",
                        "ESCALATE": "[ESCALATE]"}.get(a.get("execution_mode"), "[?]")
            print(f"  [{a['action_id']}] {mode_tag} {a['action_type']:<12} "
                  f"{a['description'][:55]}")
            print(f"       Approver: {a.get('approval_level','?')} | "
                  f"Hours reclaimed: {a.get('hours_reclaimed',0):.0f}h | "
                  f"Impact: Rs {a.get('financial_impact_inr',0):,.0f}")

        if ai_result.get("escalation_message"):
            print(f"\n  [ESCALATION MSG]:\n  \"{ai_result['escalation_message'][:200]}\"")

        print(f"\n  Post-recovery completion: {ai_result.get('post_recovery_completion_pct', 0):.1f}%")
        if ai_result.get("remaining_risk"):
            print(f"  Remaining risk: {ai_result['remaining_risk']}")
    else:
        print("\n  DEFERRABLE TASKS (rule-based):")
        for t in options["deferrable_tasks"][:5]:
            print(f"  - {t['task_id']}: {t['task_name']} ({t['estimated_hours']}h) — {t['assigned_to']}")
        print("\n  CRITICAL TASKS AT RISK:")
        for t in options["at_risk_critical_tasks"][:5]:
            rem = t["estimated_hours"] - t["completed_hours"]
            print(f"  [!] {t['task_id']}: {t['task_name']} ({rem:.0f}h remaining) — {t['assigned_to']}")

    print("\n" + "=" * 65 + "\n")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SLA Penalty Prevention Agent")
    parser.add_argument("--tasks",   help="Path to tasks CSV")
    parser.add_argument("--sla",     help="Path to SLA config JSON")
    parser.add_argument("--demo",    action="store_true")
    parser.add_argument("--output",  default="sla_prevention_report.json")
    parser.add_argument("--api-key", help="Gemini API key")
    args = parser.parse_args()

    # ── load data ──────────────────────────────────────────────────────────
    if args.tasks and args.sla:
        tasks = load_tasks(args.tasks)
        with open(args.sla) as f:
            sla = json.load(f)
    elif args.tasks and not args.sla:
        print("ERROR: --tasks requires --sla as well. Example:")
        print("  python sla_sentinel.py --tasks tasks.csv --sla sla_config.json")
        print("  python sla_sentinel.py --demo")
        raise SystemExit(1)
    else:
        print("Demo mode: SLA deadline in 3 days, team trending 25% short\n")
        tasks = DEMO_TASKS
        sla   = DEMO_SLA

    print(f"Loaded {len(tasks)} tasks | SLA deadline: {sla.get('deadline', 'N/A')}")

    sla_status = compute_sla_status(tasks, sla)
    options    = identify_reassignment_options(tasks, sla_status)

    if sla_status["will_miss_sla"]:
        print(f"[!] SLA BREACH PROJECTED — Rs {sla_status['projected_penalty_inr']:,.0f} at risk")
    else:
        print("[OK] SLA on track — monitoring only")

    api_key   = args.api_key or os.environ.get("GEMINI_API_KEY")
    ai_result = None
    if api_key and GEMINI_AVAILABLE:
        print("Running AI recovery planning...")
        try:
            ai_result = run_ai_recovery_plan(tasks, sla_status, options, api_key)
        except Exception as e:
            print(f"AI step failed ({e}) — showing rule-based results only")

    print_report(tasks, sla_status, options, ai_result)

    output = {"sla_status": sla_status, "options": options, "ai_recovery": ai_result}
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"Report saved to: {args.output}")


if __name__ == "__main__":
    main()
