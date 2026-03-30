# MedXplore Intelligence — Architecture Document

## System Overview

MedXplore Intelligence is a **domain-adaptable, multi-agent Cost Intelligence platform**.
It was designed and demonstrated in pharmaceutical inventory management, but the same
agent architecture is intentionally general-purpose — it handles any Track 3 scenario:
vendor deduplication, cloud spend anomaly diagnosis, and SLA penalty prevention.

The platform runs a **detect → diagnose → recommend → execute/stage** loop on enterprise
datasets. Every agent output carries a quantified financial impact (₹), an execution mode,
and an approval level — enabling autonomous action within defined risk thresholds while
preserving human oversight for high-stakes decisions.

---

## Agent Roles

| Agent | Responsibility | Input | Output |
|---|---|---|---|
| **Expiry Watchdog** | Detects pharmaceutical inventory at expiry risk, classifies severity, calculates write-off exposure | Inventory DB / CSV | Ranked action list with ₹ impact per batch |
| **Spend Intelligence** | Detects rate variance, duplicate procurement, overstock capital lock-in | Procurement + billing CSV/DB | Leakage map with ₹ savings per fix |
| **Vendor Dedup Agent** | Identifies duplicate/overlapping vendors via fuzzy matching + AI validation, quantifies consolidation savings | Vendor master list | Ranked merger plan with confidence scores |
| **Spend Anomaly Agent** | Diagnoses MoM cost spikes by root cause (provisioning error, autoscaling, seasonal, security) | Time-series cost data | Root cause + corrective action per category |
| **SLA Sentinel** | Projects SLA shortfall, identifies reclaimable hours, produces specific task reassignment plan | Task list + SLA config | Recovery plan with exact reassignments |
| **Orchestrator** | Synthesizes findings from all agents, deduplicates actions, builds unified Before/After financial model, ranks by ROI | All agent outputs | Master action queue + executive financial model |

---

## Agent Communication Pattern

```
┌──────────────────────────────────────────────────────────────────┐
│                        DATA INGESTION LAYER                      │
│   SQLite DB ──► CSV/JSON ──► External APIs (future: REST/MCP)   │
└────────────────────────────┬─────────────────────────────────────┘
                             │ structured JSON payloads
          ┌──────────────────┼──────────────────────┐
          │                  │                      │
          ▼                  ▼                      ▼
   [Specialist Agent 1] [Specialist Agent 2] [Specialist Agent 3]
   Expiry Watchdog      Spend Intelligence   Vendor Dedup / SLA
          │                  │                      │
          └──────────────────┼──────────────────────┘
                             │ agent_result dicts (JSON)
                             ▼
                    ┌─────────────────┐
                    │   ORCHESTRATOR  │   ← synthesizes, ranks, deduplicates
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       AUTO_EXECUTE    STAGE_FOR_APPROVAL   ESCALATE
       (risk < ₹50k)   (₹50k–₹5L)        (> ₹5L or
       No approval      Admin queue        regulatory)
       needed
```

**Communication format:** All agents communicate via structured JSON dicts with a
fixed schema: `{action_type, financial_impact_inr, execution_mode, approval_level,
confidence_score, deadline, root_cause}`. This allows the Orchestrator to consume
outputs from any agent interchangeably.

**No shared state:** Agents are stateless. Each agent call receives the full context
it needs — no agent reads another agent's intermediate state. The Orchestrator
assembles the final picture by merging outputs.

---

## Tool Integration

| Tool | How Used | Agent |
|---|---|---|
| **SQLite / PostgreSQL** | Primary data store; SQL views pre-compute expiry status and financial exposure | All |
| **Gemini API (Gemini-sonnet-4)** | Pass 2 of every agent — validates rule-based findings, adds root cause reasoning, produces structured JSON action plans | All |
| **Fuzzy string matching** (`difflib`) | Pass 1 of Vendor Dedup — O(n²) pairwise name similarity without API cost | Vendor Dedup |
| **Statistical baseline** (`statistics`) | Pass 1 of Spend Anomaly — Z-score and MoM variance detection | Spend Anomaly |
| **ReportLab** | PDF generation for billing receipts and audit reports | Flask app |
| **CSV/JSON ingest** | Accepts any structured dataset — no schema lock-in | All |
| **SQL Triggers (4)** | Auto-populate AuditLog on every INSERT/UPDATE/DELETE — zero manual logging | Flask app / DB |

**Cost efficiency design:** Every agent uses a **two-pass architecture** — fast, free
rule-based analysis first, then AI only on the ambiguous subset. For a 500-vendor
dataset, Pass 1 (fuzzy matching) reduces the AI payload to ~20-50 pairs instead of
500 × 499 / 2 = 124,750 combinations. This cuts API cost by 99%+ while maintaining accuracy.

---

## Autonomy Depth

The system completes multiple steps without human intervention:

**Fully autonomous (AUTO_EXECUTE):**
1. Load and parse dataset (CSV/DB)
2. Run rule-based classification (expiry tiers, anomaly detection, fuzzy matching)
3. Call Gemini API with structured prompt
4. Parse and validate JSON response
5. Flag expired batches as non-dispensable in DB
6. Write findings to AuditLog
7. Generate and save JSON + PDF report
8. Print ranked action list to console/dashboard

**Staged for approval:**
- Procurement consolidation decisions > ₹50,000
- Vendor merger actions
- Resource reassignments affecting headcount

**Escalated:**
- Regulatory compliance violations
- SLA penalties > ₹5 Lakhs
- Security incident diagnoses

---

## Error Handling & Graceful Degradation

| Failure Mode | Handling |
|---|---|
| **Gemini API unavailable** | Falls back to rule-based analysis — all agents produce output without AI. Degraded confidence but never silent failure. |
| **Malformed CSV/DB data** | Per-row try/catch; bad rows are skipped and counted in a `parse_errors` field. Report always generated. |
| **JSON parse failure (AI response)** | Strips markdown fences, retries once. If still fails, returns raw text with `parse_failed: true` flag. |
| **Empty dataset** | Returns `{"status": "no_data", "message": "..."}` — never crashes. |
| **Partial DB (missing tables)** | SQL queries wrapped in try/except; missing tables return empty lists, not exceptions. |
| **AI returns unexpected structure** | Schema validation with `.get()` defaults — missing keys never cause KeyError. |

**Enterprise readiness signals:**
- Full AuditLog via SQL triggers — every action traceable
- Role-based access: Admin vs Pharmacist — agents can only execute within role scope
- Atomic transactions — billing and inventory updates never partially commit
- `CHECK` constraints on DB — inventory quantity can never go negative
- All financial figures rounded to 2 decimal places — no floating point presentation errors

---

## Before/After Financial Model (Illustrative, 500-bed hospital)

| Cost Category | Before | After | Annual Saving |
|---|---|---|---|
| Drug expiry write-offs | ₹8L/month | ₹1.6L/month | **₹76.8L** |
| Procurement rate overspend | ₹3L/month | ₹0.6L/month | **₹28.8L** |
| Vendor duplication (admin + rate) | ₹15L/year | ₹3L/year | **₹12L** |
| Overstock capital freed | ₹40L locked | ₹10L locked | **₹30L freed** |
| Regulatory penalty exposure | ₹5L/year | ₹0 | **₹5L** |
| **TOTAL** | | | **₹1.52 Crore/year** |

Deployment cost: ₹8–12L/year → **ROI: 12–18x**

**Assumptions:** 4% baseline expiry rate on ₹2Cr monthly procurement; 80% of at-risk batches
caught 30+ days early; 60% returnable to supplier; 15% procurement rate savings from consolidation.

---

## Surprise Scenario Readiness

The architecture handles novel scenarios because:

1. **Agents accept any structured CSV/JSON** — no hardcoded domain assumptions
2. **The AI system prompt is parameterized** — changing the domain only requires updating the prompt
3. **The orchestrator pattern is domain-agnostic** — it consumes any `{action, impact, mode}` output
4. **Graceful degradation** — if a scenario doesn't match any agent's domain, the rule-based fallback still runs and produces a ranked output

---

## Running the System

```bash
# Install
pip install flask reportlab Gemini

# Set API key (optional — falls back to rules without it)
export Gemini_API_KEY=your_key

# Run mandatory scenario 1: Vendor deduplication
python agents/vendor_dedup.py --demo

# Run mandatory scenario 2: Spend anomaly (40% cloud spike)
python agents/spend_anomaly.py --demo

# Run mandatory scenario 3: SLA penalty prevention (3 days left)
python agents/sla_sentinel.py --demo

# Run full orchestrator on pharma domain
python agents/orchestrator.py --demo

# Launch the web app
python app.py   # → http://127.0.0.1:5000  (admin/admin123)
```

On **your own data:**
```bash
python agents/vendor_dedup.py --vendors your_500_vendors.csv
python agents/spend_anomaly.py --data your_cloud_spend.csv
python agents/sla_sentinel.py --tasks your_tasks.csv --sla your_sla.json
```
**Developed by Durlabh Biswas, Ayush Kumar, Shreyan Porel**
