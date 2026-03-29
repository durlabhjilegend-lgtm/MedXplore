"""
MedXplore Intelligence — Flask Web Dashboard
Run: python app.py  →  http://127.0.0.1:5000
Login: admin / admin123
"""

from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
import json, os, subprocess, sys
from datetime import date, timedelta

app = Flask(__name__)
app.secret_key = "medxplore_secret_2024"

USERS = {"admin": "admin123", "pharmacist": "pharma123"}

# ── inline HTML templates ─────────────────────────────────────────────────────

LOGIN_HTML = """
<!DOCTYPE html><html><head><title>MedXplore Login</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);min-height:100vh;
     display:flex;align-items:center;justify-content:center;font-family:'Segoe UI',sans-serif}
.card{background:rgba(255,255,255,0.05);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.1);
      border-radius:16px;padding:48px 40px;width:360px;box-shadow:0 25px 50px rgba(0,0,0,0.4)}
h1{color:#fff;font-size:1.8rem;margin-bottom:4px;text-align:center}
.sub{color:#7eccc5;text-align:center;font-size:.85rem;margin-bottom:32px}
label{color:#a0c4c0;font-size:.8rem;font-weight:600;letter-spacing:.5px;text-transform:uppercase}
input{width:100%;padding:12px 16px;border-radius:8px;border:1px solid rgba(255,255,255,0.15);
      background:rgba(255,255,255,0.08);color:#fff;font-size:.95rem;margin:8px 0 20px;outline:none}
input:focus{border-color:#7eccc5}
button{width:100%;padding:13px;background:linear-gradient(90deg,#00b4d8,#0077b6);
       color:#fff;border:none;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer;
       transition:opacity .2s}
button:hover{opacity:.85}
.err{color:#ff6b6b;font-size:.85rem;text-align:center;margin-bottom:16px}
.hint{color:#556;font-size:.78rem;text-align:center;margin-top:20px}
</style></head><body>
<div class="card">
  <h1>MedXplore</h1>
  <div class="sub">Cost Intelligence Platform</div>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <form method="post">
    <label>Username</label>
    <input name="username" placeholder="admin" required>
    <label>Password</label>
    <input name="password" type="password" placeholder="••••••••" required>
    <button type="submit">Sign In</button>
  </form>
  <div class="hint">admin / admin123 &nbsp;|&nbsp; pharmacist / pharma123</div>
</div>
</body></html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html><html><head><title>MedXplore Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',sans-serif;min-height:100vh}
nav{background:#161b22;border-bottom:1px solid #30363d;padding:0 32px;display:flex;
    align-items:center;justify-content:space-between;height:60px}
.logo{color:#58a6ff;font-weight:700;font-size:1.2rem;letter-spacing:1px}
.logo span{color:#7eccc5}
.nav-right{display:flex;align-items:center;gap:20px}
.nav-right a{color:#8b949e;text-decoration:none;font-size:.9rem}
.nav-right a:hover{color:#e6edf3}
.badge{background:#21262d;border:1px solid #30363d;padding:4px 12px;border-radius:20px;
       font-size:.8rem;color:#58a6ff}
main{max-width:1200px;margin:0 auto;padding:32px 24px}
h2{font-size:1.4rem;margin-bottom:4px}
.subtitle{color:#8b949e;font-size:.9rem;margin-bottom:32px}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px;margin-bottom:36px}
.kpi{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;position:relative;overflow:hidden}
.kpi::before{content:'';position:absolute;top:0;left:0;width:4px;height:100%;background:var(--accent)}
.kpi-label{color:#8b949e;font-size:.8rem;font-weight:600;letter-spacing:.5px;text-transform:uppercase;margin-bottom:8px}
.kpi-value{font-size:1.9rem;font-weight:700;color:#e6edf3}
.kpi-sub{color:#8b949e;font-size:.8rem;margin-top:4px}
.green{--accent:#3fb950} .blue{--accent:#58a6ff} .orange{--accent:#d29922} .red{--accent:#f85149}
.section{margin-bottom:36px}
.section h3{font-size:1.1rem;color:#e6edf3;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.tag{font-size:.7rem;padding:2px 8px;border-radius:12px;font-weight:600}
.tag-green{background:#1a3c2a;color:#3fb950} .tag-red{background:#3c1a1a;color:#f85149}
.tag-blue{background:#1a2a3c;color:#58a6ff} .tag-orange{background:#3c2e1a;color:#d29922}
.btn-row{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}
.btn{padding:10px 20px;border-radius:8px;border:none;font-size:.88rem;font-weight:600;
     cursor:pointer;transition:all .2s;text-decoration:none;display:inline-block}
.btn-primary{background:linear-gradient(90deg,#00b4d8,#0077b6);color:#fff}
.btn-primary:hover{opacity:.85}
.btn-outline{background:transparent;border:1px solid #30363d;color:#8b949e}
.btn-outline:hover{border-color:#58a6ff;color:#58a6ff}
.table-wrap{background:#161b22;border:1px solid #30363d;border-radius:12px;overflow:hidden}
table{width:100%;border-collapse:collapse}
th{background:#21262d;color:#8b949e;font-size:.78rem;font-weight:600;text-transform:uppercase;
   letter-spacing:.5px;padding:12px 16px;text-align:left}
td{padding:12px 16px;font-size:.88rem;border-top:1px solid #21262d;vertical-align:middle}
tr:hover td{background:#1c2128}
.agent-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}
.agent-card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px}
.agent-card h4{font-size:1rem;margin-bottom:8px;color:#e6edf3}
.agent-card p{color:#8b949e;font-size:.85rem;margin-bottom:16px;line-height:1.5}
.status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
.dot-green{background:#3fb950} .dot-yellow{background:#d29922} .dot-red{background:#f85149}
.output-box{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:16px;
            font-family:monospace;font-size:.82rem;color:#7eccc5;max-height:320px;
            overflow-y:auto;white-space:pre-wrap;line-height:1.6;margin-top:12px}
.loading{color:#8b949e;font-style:italic}
footer{text-align:center;color:#484f58;font-size:.8rem;padding:32px;border-top:1px solid #21262d;margin-top:48px}
</style></head><body>

<nav>
  <div class="logo">Med<span>Xplore</span> Intelligence</div>
  <div class="nav-right">
    <span class="badge">{{ session.username }} &nbsp;|&nbsp; {{ role }}</span>
    <a href="/logout">Sign out</a>
  </div>
</nav>

<main>
  <h2>Cost Intelligence Dashboard</h2>
  <div class="subtitle">Multi-agent platform — Detect &bull; Diagnose &bull; Recommend &bull; Execute</div>

  <!-- KPI cards -->
  <div class="kpi-grid">
    <div class="kpi green">
      <div class="kpi-label">Est. Annual Saving</div>
      <div class="kpi-value">Rs 1.52 Cr</div>
      <div class="kpi-sub">Across all agent findings</div>
    </div>
    <div class="kpi blue">
      <div class="kpi-label">Vendors Flagged</div>
      <div class="kpi-value">8 clusters</div>
      <div class="kpi-sub">Consolidation potential: Rs 63.75L</div>
    </div>
    <div class="kpi orange">
      <div class="kpi-label">Spend Anomalies</div>
      <div class="kpi-value">6 detected</div>
      <div class="kpi-sub">Excess spend: Rs 1.00 Cr</div>
    </div>
    <div class="kpi red">
      <div class="kpi-label">SLA Penalty at Risk</div>
      <div class="kpi-value">Rs 15L</div>
      <div class="kpi-sub">3 days to deadline</div>
    </div>
  </div>

  <!-- Run Agents -->
  <div class="section">
    <h3>Run Agents</h3>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="runAgent('vendor')">Run Vendor Dedup</button>
      <button class="btn btn-primary" onclick="runAgent('spend')">Run Spend Anomaly</button>
      <button class="btn btn-primary" onclick="runAgent('sla')">Run SLA Sentinel</button>
    </div>
    <div id="agent-output" class="output-box" style="display:none"></div>
  </div>

  <!-- Agent Status -->
  <div class="section">
    <h3>Agent Registry</h3>
    <div class="agent-grid">
      <div class="agent-card">
        <h4><span class="status-dot dot-green"></span>Vendor Dedup Agent</h4>
        <p>Fuzzy-matches vendor names across procurement data. Identifies duplicate entities and quantifies consolidation savings via two-pass (rule + AI) approach.</p>
        <span class="tag tag-green">AUTO_EXECUTE</span>
      </div>
      <div class="agent-card">
        <h4><span class="status-dot dot-green"></span>Spend Anomaly Agent</h4>
        <p>Detects MoM cost spikes using Z-score baseline. AI diagnoses root cause: provisioning error, autoscaling misconfiguration, or security incident.</p>
        <span class="tag tag-orange">STAGE_FOR_APPROVAL</span>
      </div>
      <div class="agent-card">
        <h4><span class="status-dot dot-yellow"></span>SLA Sentinel</h4>
        <p>Projects SLA shortfall from task completion rates. Produces exact reassignment plan with penalty exposure quantified per day of delay.</p>
        <span class="tag tag-red">ESCALATE</span>
      </div>
      <div class="agent-card">
        <h4><span class="status-dot dot-green"></span>Orchestrator</h4>
        <p>Synthesizes all agent findings. Deduplicates actions. Builds unified Before/After financial model ranked by ROI. Routes to approval queues.</p>
        <span class="tag tag-blue">COORDINATOR</span>
      </div>
    </div>
  </div>

  <!-- Vendor Table -->
  <div class="section">
    <h3>Top Vendor Consolidation Opportunities</h3>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Vendor A</th><th>Vendor B</th><th>Category</th><th>Combined Spend</th><th>Saving (15%)</th><th>Confidence</th></tr></thead>
        <tbody>
          <tr><td>1</td><td>Abbott India</td><td>Abbot India Ltd</td><td>Drugs</td><td>Rs 53,00,000</td><td>Rs 7,95,000</td><td><span class="tag tag-green">HIGH</span></td></tr>
          <tr><td>2</td><td>Cipla Limited</td><td>Cipla Ltd.</td><td>Drugs</td><td>Rs 47,00,000</td><td>Rs 7,05,000</td><td><span class="tag tag-green">HIGH</span></td></tr>
          <tr><td>3</td><td>3M Healthcare</td><td>3M Health Care India</td><td>Devices</td><td>Rs 20,50,000</td><td>Rs 3,07,500</td><td><span class="tag tag-green">HIGH</span></td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- Anomaly Table -->
  <div class="section">
    <h3>Spend Anomalies Detected</h3>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Category</th><th>Change</th><th>Excess Spend</th><th>Severity</th><th>Root Cause</th><th>Action</th></tr></thead>
        <tbody>
          <tr><td>EC2 Compute</td><td style="color:#f85149">+42%</td><td>Rs 50,40,000</td><td><span class="tag tag-red">CRITICAL</span></td><td>Autoscaling misconfiguration</td><td><span class="tag tag-blue">AUTO_EXECUTE</span></td></tr>
          <tr><td>RDS Database</td><td style="color:#f85149">+38%</td><td>Rs 30,40,000</td><td><span class="tag tag-red">CRITICAL</span></td><td>Provisioning error</td><td><span class="tag tag-orange">APPROVAL</span></td></tr>
          <tr><td>S3 Storage</td><td style="color:#d29922">+28%</td><td>Rs 12,60,000</td><td><span class="tag tag-orange">HIGH</span></td><td>Data pipeline runaway</td><td><span class="tag tag-orange">APPROVAL</span></td></tr>
          <tr><td>Data Transfer</td><td style="color:#d29922">+25%</td><td>Rs 7,50,000</td><td><span class="tag tag-orange">HIGH</span></td><td>Under investigation</td><td><span class="tag tag-blue">MONITOR</span></td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- Financial Model -->
  <div class="section">
    <h3>Before / After Financial Model — 500-bed Hospital</h3>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Cost Category</th><th>Before</th><th>After</th><th>Annual Saving</th></tr></thead>
        <tbody>
          <tr><td>Drug expiry write-offs</td><td>Rs 8L/month</td><td>Rs 1.6L/month</td><td style="color:#3fb950"><b>Rs 76.8L</b></td></tr>
          <tr><td>Procurement rate overspend</td><td>Rs 3L/month</td><td>Rs 0.6L/month</td><td style="color:#3fb950"><b>Rs 28.8L</b></td></tr>
          <tr><td>Vendor duplication</td><td>Rs 15L/year</td><td>Rs 3L/year</td><td style="color:#3fb950"><b>Rs 12L</b></td></tr>
          <tr><td>Overstock capital freed</td><td>Rs 40L locked</td><td>Rs 10L locked</td><td style="color:#3fb950"><b>Rs 30L freed</b></td></tr>
          <tr><td>Regulatory penalty exposure</td><td>Rs 5L/year</td><td>Rs 0</td><td style="color:#3fb950"><b>Rs 5L</b></td></tr>
          <tr style="background:#1a3c2a"><td><b>TOTAL</b></td><td></td><td></td><td style="color:#3fb950;font-size:1.1rem"><b>Rs 1.52 Crore/year</b></td></tr>
        </tbody>
      </table>
    </div>
  </div>

</main>
<footer>MedXplore Intelligence &copy; 2024 &mdash; ROI: 12-18x &mdash; Deployment cost: Rs 8-12L/year</footer>

<script>
function runAgent(agent) {
  const box = document.getElementById('agent-output');
  box.style.display = 'block';
  box.textContent = 'Running agent... please wait...';
  fetch('/run-agent/' + agent)
    .then(r => r.json())
    .then(data => { box.textContent = data.output; })
    .catch(e => { box.textContent = 'Error: ' + e; });
}
</script>
</body></html>
"""

# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def login():
    if "username" in session:
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if USERS.get(u) == p:
            session["username"] = u
            return redirect(url_for("dashboard"))
        error = "Invalid username or password"
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return redirect(url_for("login"))
    role = "Administrator" if session["username"] == "admin" else "Pharmacist"
    return render_template_string(DASHBOARD_HTML, session=session, role=role)


@app.route("/run-agent/<agent>")
def run_agent(agent):
    if "username" not in session:
        return jsonify({"output": "Not authenticated"}), 401

    script_map = {
        "vendor": ["python", "vendor_dedup.py", "--demo"],
        "spend":  ["python", "spend_anomaly.py", "--demo"],
        "sla":    ["python", "sla_sentinel.py",  "--demo"],
    }
    cmd = script_map.get(agent)
    if not cmd:
        return jsonify({"output": "Unknown agent"})

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        output = result.stdout or result.stderr or "(no output)"
    except subprocess.TimeoutExpired:
        output = "Agent timed out after 60s"
    except Exception as e:
        output = f"Error running agent: {e}"

    return jsonify({"output": output})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    print("=" * 55)
    print("  MedXplore Intelligence — Starting...")
    print("  URL  : http://127.0.0.1:5000")
    print("  Login: admin / admin123")
    print("=" * 55)
    app.run(debug=False, port=5000)
