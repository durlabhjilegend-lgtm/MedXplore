"""
Mandatory Scenario 1: Vendor Duplicate Detection
=================================================
Given a procurement dataset with 500+ vendors, this agent:
1. Identifies duplicate/overlapping vendors (same service, different entity names)
2. Quantifies consolidation savings
3. Generates a ranked action plan

This uses a two-pass approach:
  Pass 1 (fast, free): Rule-based exact/fuzzy matching on name + category + geography
  Pass 2 (AI): Gemini resolves ambiguous matches and explains the consolidation rationale

Usage:
    python vendor_dedup.py --vendors vendors.csv
    python vendor_dedup.py --demo   (runs on 20 built-in sample vendors)

CSV Format:
    vendor_id, vendor_name, category, annual_spend_inr, country, contact_email, services
"""

import json
import argparse
import csv
import os
import re
from itertools import combinations
from difflib import SequenceMatcher

try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


# ─────────────────────────────────────────────
# DATA LOADER
# ─────────────────────────────────────────────

def load_vendors(filepath: str) -> list[dict]:
    vendors = []
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            vendors.append({
                "vendor_id":        row.get("vendor_id", ""),
                "vendor_name":      row.get("vendor_name", "").strip(),
                "category":         row.get("category", "").strip().lower(),
                "annual_spend_inr": float(row.get("annual_spend_inr", 0) or 0),
                "country":          row.get("country", "").strip().lower(),
                "contact_email":    row.get("contact_email", "").strip(),
                "phone":            row.get("phone", "").strip(),
                "services":         row.get("services", "").strip().lower(),
            })
    return vendors


DEMO_VENDORS = [
    {"vendor_id": "V001", "vendor_name": "Sun Pharma Ltd",            "category": "drugs",       "annual_spend_inr": 4500000, "country": "india", "contact_email": "procurement@sunpharma.com", "phone": "9876543210", "services": "pharmaceuticals"},
    {"vendor_id": "V002", "vendor_name": "Sun Pharmaceuticals",      "category": "drugs",       "annual_spend_inr": 3200000, "country": "india", "contact_email": "purchase@sunpharmaind.com", "phone": "9876543211", "services": "pharmaceuticals"},
    {"vendor_id": "V003", "vendor_name": "Cipla Limited",            "category": "drugs",       "annual_spend_inr": 2800000, "country": "india", "contact_email": "orders@cipla.com", "phone": "9123456780", "services": "pharmaceuticals"},
    {"vendor_id": "V004", "vendor_name": "Cipla Ltd.",              "category": "drugs",       "annual_spend_inr": 1900000, "country": "india", "contact_email": "supply@cipla.co.in", "phone": "9123456781", "services": "pharmaceuticals"},
    {"vendor_id": "V005", "vendor_name": "3M Healthcare",            "category": "devices",     "annual_spend_inr": 1200000, "country": "india", "contact_email": "india@3m.com", "phone": "9988776655", "services": "medical devices"},
    {"vendor_id": "V006", "vendor_name": "3M Health Care India",     "category": "devices",     "annual_spend_inr": 850000,  "country": "india", "contact_email": "sales@3mindia.com", "phone": "9988776656", "services": "medical devices"},
    {"vendor_id": "V007", "vendor_name": "Abbott India",             "category": "drugs",       "annual_spend_inr": 3100000, "country": "india", "contact_email": "abbott.orders@abbott.com", "phone": "9001234567", "services": "pharmaceuticals"},
    {"vendor_id": "V008", "vendor_name": "Abbot India Ltd",          "category": "drugs",       "annual_spend_inr": 2200000, "country": "india", "contact_email": "procurement@abbottindia.com", "phone": "9001234568", "services": "pharmaceuticals"},
    {"vendor_id": "V009", "vendor_name": "Baxter International",    "category": "devices",     "annual_spend_inr": 950000,  "country": "india", "contact_email": "baxter@baxter.in", "phone": "9871234560", "services": "medical devices"},
    {"vendor_id": "V010", "vendor_name": "Medline Industries",       "category": "consumables", "annual_spend_inr": 670000,  "country": "india", "contact_email": "info@medline.in", "phone": "9871234561", "services": "medical consumables"},
]


# ─────────────────────────────────────────────
# PASS 1: RULE-BASED MATCHING
# ─────────────────────────────────────────────

def normalize(name: str) -> str:
    """Strip legal suffixes and normalize for comparison."""
    suffixes = [r'\bltd\b', r'\blimited\b', r'\bpvt\b', r'\bprivate\b', r'\binc\b',
                r'\bcorp\b', r'\bllc\b', r'\bllp\b', r'\bco\b', r'\bservices\b',
                r'\btechnologies\b', r'\bsolutions\b', r'\bplatform\b', r'\bexpress\b',
                r'\bindia\b', r'\bindian\b']
    n = name.lower()
    for s in suffixes:
        n = re.sub(s, '', n)
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def find_duplicate_pairs(vendors: list[dict], threshold: float = 0.72) -> list[dict]:
    """Find likely duplicate vendor pairs using fuzzy name matching + category."""
    pairs = []
    seen = set()

    for i, j in combinations(range(len(vendors)), 2):
        a, b = vendors[i], vendors[j]

        if a["category"] != b["category"]:
            continue

        key = tuple(sorted([a["vendor_id"], b["vendor_id"]]))
        if key in seen:
            continue

        name_sim = similarity(a["vendor_name"], b["vendor_name"])

        def domain(email):
            parts = email.split("@")
            if len(parts) == 2:
                return parts[1].split(".")[0]
            return ""

        email_match = (domain(a["contact_email"]) == domain(b["contact_email"])
                       and domain(a["contact_email"]) != "")

        if name_sim >= threshold or email_match:
            combined_spend = a["annual_spend_inr"] + b["annual_spend_inr"]
            saving_estimate = combined_spend * 0.15

            pairs.append({
                "vendor_a_id":          a["vendor_id"],
                "vendor_a_name":        a["vendor_name"],
                "vendor_b_id":          b["vendor_id"],
                "vendor_b_name":        b["vendor_name"],
                "category":             a["category"],
                "name_similarity":      round(name_sim, 3),
                "email_domain_match":   email_match,
                "vendor_a_spend_inr":   a["annual_spend_inr"],
                "vendor_b_spend_inr":   b["annual_spend_inr"],
                "combined_spend_inr":   combined_spend,
                "estimated_saving_inr": round(saving_estimate, 2),
                "confidence":           "HIGH" if name_sim > 0.85 or email_match else "MEDIUM",
                "recommended_action":   (f"Merge {b['vendor_name']} into {a['vendor_name']} "
                                         f"(higher spend = preferred master). Renegotiate consolidated contract.")
            })
            seen.add(key)

    return sorted(pairs, key=lambda x: x["estimated_saving_inr"], reverse=True)


def group_duplicates(pairs: list[dict]) -> list[dict]:
    """Group related pairs into vendor clusters for deduplication."""
    parent = {}

    def find(x):
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        parent[find(x)] = find(y)

    for p in pairs:
        union(p["vendor_a_id"], p["vendor_b_id"])

    clusters = {}
    for p in pairs:
        root = find(p["vendor_a_id"])
        if root not in clusters:
            clusters[root] = {"vendor_ids": set(), "total_spend": 0, "pairs": []}
        clusters[root]["vendor_ids"].add(p["vendor_a_id"])
        clusters[root]["vendor_ids"].add(p["vendor_b_id"])
        clusters[root]["total_spend"] = max(clusters[root]["total_spend"], p["combined_spend_inr"])
        clusters[root]["pairs"].append(p)

    result = []
    for i, (root, cluster) in enumerate(clusters.items()):
        total = cluster["total_spend"]
        result.append({
            "cluster_id":            i + 1,
            "vendor_ids":            list(cluster["vendor_ids"]),
            "vendor_count":          len(cluster["vendor_ids"]),
            "total_spend_inr":       total,
            "saving_potential_inr":  round(total * 0.15, 2),
            "pairs":                 cluster["pairs"],
        })

    return sorted(result, key=lambda x: x["saving_potential_inr"], reverse=True)


# ─────────────────────────────────────────────
# PASS 2: AI ANALYSIS (google-genai SDK)
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a procurement intelligence agent specializing in vendor consolidation.

You will receive a list of suspected duplicate vendor pairs identified by rule-based matching.
Your job is to:
1. Validate each pair — confirm if they are truly duplicates, subsidiaries, or distinct entities
2. For each confirmed duplicate group, identify the MASTER vendor (highest leverage, better terms)
3. Quantify consolidation saving more precisely:
   - Contract renegotiation savings: 10-20% of combined spend
   - Admin/onboarding cost saved: Rs 50,000-Rs 2,00,000 per vendor eliminated
   - Payment processing saved: Rs 5,000-Rs 20,000 per vendor per year
4. Rank the actions by ROI (savings vs effort)
5. Flag any HIGH RISK consolidations (e.g., single-source risk, regulatory vendor)

OUTPUT FORMAT - respond ONLY with valid JSON, no markdown, no preamble:
{
  "total_vendors_analyzed": 0,
  "duplicates_confirmed": 0,
  "total_consolidation_saving_inr": 0.00,
  "ranked_actions": [
    {
      "rank": 1,
      "cluster_name": "...",
      "vendor_ids_to_merge": ["V002"],
      "master_vendor_id": "V001",
      "master_vendor_name": "...",
      "confirmed_duplicate": true,
      "confidence": "HIGH",
      "contract_saving_inr": 0.00,
      "admin_saving_inr": 0.00,
      "total_saving_inr": 0.00,
      "risk_flags": [],
      "action_steps": ["Step 1", "Step 2"],
      "timeline_days": 30,
      "approval_required": "PROCUREMENT_HEAD"
    }
  ],
  "summary": "..."
}"""


def run_ai_analysis(vendors: list[dict], pairs: list[dict], clusters: list[dict],
                    api_key: str) -> dict:
    if not GEMINI_AVAILABLE:
        raise ImportError("google-genai is not installed. Run: pip install google-genai")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required")

    client = genai.Client(api_key=api_key)

    payload = {
        "total_vendors":      len(vendors),
        "suspected_clusters": clusters[:15],
        "suspected_pairs":    pairs[:20],
    }
    full_prompt = (SYSTEM_PROMPT + "\n\n"
                   "Analyze these vendor duplicate clusters and produce a ranked consolidation plan:\n"
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

def print_report(vendors, pairs, clusters, ai_result=None):
    total_spend  = sum(v["annual_spend_inr"] for v in vendors)
    total_saving = sum(c["saving_potential_inr"] for c in clusters)

    print("\n" + "=" * 65)
    print("  VENDOR DEDUPLICATION INTELLIGENCE REPORT")
    print("=" * 65)
    print(f"  Vendors analyzed          : {len(vendors)}")
    print(f"  Duplicate pairs found     : {len(pairs)}")
    print(f"  Vendor clusters to merge  : {len(clusters)}")
    print(f"  Total annual spend        : Rs {total_spend:>12,.0f}")
    print(f"  Consolidation saving (est): Rs {total_saving:>12,.0f}  ({total_saving/total_spend*100:.1f}% of spend)")
    print("=" * 65)

    if ai_result:
        print(f"\n  [AI] CONFIRMS: {ai_result.get('duplicates_confirmed', '?')} duplicates")
        print(f"  Total saving (AI refined): Rs {ai_result.get('total_consolidation_saving_inr', 0):,.0f}")
        print(f"\n  {ai_result.get('summary', '')}\n")
        print("  RANKED ACTIONS:\n")
        for a in ai_result.get("ranked_actions", [])[:5]:
            print(f"  [{a['rank']}] Merge into: {a['master_vendor_name']}")
            print(f"       Vendors to merge : {a['vendor_ids_to_merge']}")
            print(f"       Total saving     : Rs {a['total_saving_inr']:,.0f}  | Timeline: {a['timeline_days']} days")
            print(f"       Approval required: {a.get('approval_required', 'N/A')}")
            if a.get("risk_flags"):
                print(f"       [!] Risks        : {', '.join(a['risk_flags'])}")
            print()
    else:
        print("\n  TOP CONSOLIDATION OPPORTUNITIES (rule-based):\n")
        for i, c in enumerate(clusters[:5]):
            print(f"  [{i+1}] Cluster: {c['vendor_ids']}  ({c['vendor_count']} vendors)")
            print(f"       Combined spend: Rs {c['total_spend_inr']:,.0f}  |  Saving: Rs {c['saving_potential_inr']:,.0f}")
            if c["pairs"]:
                top = c["pairs"][0]
                print(f"       Best match: '{top['vendor_a_name']}' <-> '{top['vendor_b_name']}' "
                      f"(similarity: {top['name_similarity']:.0%}, {top['confidence']})")
            print()

    print("=" * 65 + "\n")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Vendor Duplicate Detection Agent")
    parser.add_argument("--vendors",   help="Path to vendors CSV")
    parser.add_argument("--demo",      action="store_true", help="Run on built-in sample data")
    parser.add_argument("--threshold", type=float, default=0.72, help="Fuzzy match threshold (0-1)")
    parser.add_argument("--output",    default="vendor_dedup_report.json")
    parser.add_argument("--api-key",   help="Gemini API key")
    args = parser.parse_args()

    if args.vendors:
        vendors = load_vendors(args.vendors)
    else:
        print("Demo mode: using 20 built-in sample vendors\n")
        vendors = DEMO_VENDORS

    print(f"Loaded {len(vendors)} vendors")

    pairs    = find_duplicate_pairs(vendors, threshold=args.threshold)
    clusters = group_duplicates(pairs)
    print(f"Found {len(pairs)} pairs -> {len(clusters)} consolidation clusters")

    api_key   = args.api_key or os.environ.get("GEMINI_API_KEY")
    ai_result = None
    if api_key and GEMINI_AVAILABLE and pairs:
        print("Running AI validation...")
        try:
            ai_result = run_ai_analysis(vendors, pairs, clusters, api_key)
        except Exception as e:
            print(f"AI step failed ({e}) — showing rule-based results only")

    print_report(vendors, pairs, clusters, ai_result)

    output = {
        "vendors_analyzed": len(vendors),
        "pairs":            pairs,
        "clusters":         clusters,
        "ai_analysis":      ai_result,
    }
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"Report saved to: {args.output}")


if __name__ == "__main__":
    main()
