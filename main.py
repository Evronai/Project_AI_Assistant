"""
Project AI Assistant — Single-file Streamlit Edition
=====================================================
Run:  pip install streamlit plotly pandas requests cryptography
      streamlit run app.py

All production patterns from the multi-file version, condensed:
  • Fernet-encrypted API key storage (SQLite)
  • Pydantic settings from environment / .env
  • Retry + rate limiting on AI calls
  • Budget enforcement
  • Structured audit log
  • Health sidebar
  • Idempotent seeder
"""

# ─────────────────────────────────────────────────────────────────────────────
# Stdlib
# ─────────────────────────────────────────────────────────────────────────────
import base64
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Third-party
# ─────────────────────────────────────────────────────────────────────────────
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# Optional: cryptography for key encryption
try:
    from cryptography.fernet import Fernet, InvalidToken
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

APP_TITLE        = "Project AI Assistant"
APP_VERSION      = "2.0.0"
DB_PATH          = Path(os.getenv("DATABASE_PATH", "project_ai.db"))
SECRET_KEY       = os.getenv("APP_SECRET_KEY", "dev-secret-key-change-in-production-32c")
DEEPSEEK_URL     = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MONTHLY_BUDGET   = float(os.getenv("AI_MONTHLY_BUDGET_USD", "50.0"))
MAX_TOKENS       = int(os.getenv("AI_MAX_TOKENS", "1000"))
RATE_LIMIT_RPM   = int(os.getenv("AI_RATE_LIMIT_RPM", "20"))
AI_TIMEOUT       = int(os.getenv("AI_TIMEOUT_SECONDS", "30"))

# DeepSeek pricing per 1M tokens
PRICING = {"deepseek-chat": {"in": 0.14, "out": 0.28},
           "deepseek-coder": {"in": 0.14, "out": 0.28}}

SYSTEM_PROMPTS = {
    "therapy":   "You are an empathetic project management coach. Be concise and actionable. Max 250 words.",
    "simulator": "You are a quantitative project scenario simulator. Give probabilistic estimates. Max 250 words.",
    "insights":  "You are a cross-project pattern recognition expert. Be specific. Max 250 words.",
    "general":   "You are a professional project management assistant. Max 250 words.",
}

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2 — SECURITY
# ═════════════════════════════════════════════════════════════════════════════

def _fernet_key() -> bytes:
    digest = hashlib.sha256(SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)

def encrypt_secret(plaintext: str) -> str:
    if not plaintext or not CRYPTO_AVAILABLE:
        return plaintext  # Graceful degradation without cryptography package
    return Fernet(_fernet_key()).encrypt(plaintext.encode()).decode()

def decrypt_secret(ciphertext: str) -> Optional[str]:
    if not ciphertext:
        return None
    if not CRYPTO_AVAILABLE:
        return ciphertext
    try:
        return Fernet(_fernet_key()).decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return None

def mask_key(key: str) -> str:
    return key[:8] + "..." + "●" * 8 if key and len(key) > 8 else "●●●"

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3 — DATABASE
# ═════════════════════════════════════════════════════════════════════════════

@contextmanager
def get_conn():
    """Thread-safe SQLite connection context manager."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'planning',
            start_date TEXT, end_date TEXT,
            team_size INTEGER DEFAULT 1,
            velocity REAL DEFAULT 20.0,
            budget REAL DEFAULT 10000.0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS team_members (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            role TEXT,
            workload REAL DEFAULT 0.0,
            morale REAL DEFAULT 80.0,
            skills TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sprints (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            number INTEGER NOT NULL,
            start_date TEXT, end_date TEXT,
            planned_points INTEGER DEFAULT 0,
            completed_points INTEGER DEFAULT 0,
            blockers TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS ai_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT DEFAULT 'deepseek',
            encrypted_api_key TEXT,
            model TEXT DEFAULT 'deepseek-chat',
            base_url TEXT DEFAULT 'https://api.deepseek.com',
            monthly_budget REAL DEFAULT 50.0,
            features TEXT DEFAULT '["therapy","simulator","insights"]',
            is_active INTEGER DEFAULT 1,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS ai_usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT, model TEXT, feature TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            success INTEGER DEFAULT 1,
            error_msg TEXT,
            duration_ms INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)

# ── Query helpers ──────────────────────────────────────────────────────────

def db_rows(query: str, params=()) -> list[dict]:
    with get_conn() as c:
        return [dict(r) for r in c.execute(query, params).fetchall()]

def db_one(query: str, params=()) -> Optional[dict]:
    with get_conn() as c:
        r = c.execute(query, params).fetchone()
        return dict(r) if r else None

def db_exec(query: str, params=()):
    with get_conn() as c:
        c.execute(query, params)

def get_projects() -> list[dict]:
    return db_rows("SELECT * FROM projects ORDER BY created_at DESC")

def get_team(project_id: str) -> list[dict]:
    rows = db_rows("SELECT * FROM team_members WHERE project_id=? ORDER BY name", (project_id,))
    for r in rows:
        r["skills"] = json.loads(r.get("skills") or "[]")
    return rows

def get_sprints(project_id: str) -> list[dict]:
    rows = db_rows("SELECT * FROM sprints WHERE project_id=? ORDER BY number", (project_id,))
    for r in rows:
        r["blockers"] = json.loads(r.get("blockers") or "[]")
        planned = r["planned_points"] or 1
        r["completion_pct"] = min(100.0, r["completed_points"] / planned * 100)
    return rows

def get_ai_config() -> Optional[dict]:
    cfg = db_one("SELECT * FROM ai_config WHERE is_active=1 ORDER BY updated_at DESC LIMIT 1")
    if cfg:
        cfg["api_key"] = decrypt_secret(cfg.get("encrypted_api_key") or "")
        cfg["features"] = json.loads(cfg.get("features") or "[]")
    return cfg

def get_monthly_cost() -> float:
    r = db_one("""
        SELECT COALESCE(SUM(cost_usd),0) AS total FROM ai_usage_log
        WHERE success=1 AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')
    """)
    return float(r["total"]) if r else 0.0

def save_ai_config(provider, api_key, model, base_url, budget, features):
    db_exec("UPDATE ai_config SET is_active=0")
    db_exec("""
        INSERT INTO ai_config (provider, encrypted_api_key, model, base_url, monthly_budget, features, is_active, updated_at)
        VALUES (?,?,?,?,?,?,1, datetime('now'))
    """, (provider, encrypt_secret(api_key), model, base_url, budget, json.dumps(features)))

def log_ai_usage(provider, model, feature, prompt_tok, comp_tok, cost, success, error, duration_ms):
    db_exec("""
        INSERT INTO ai_usage_log (provider, model, feature, prompt_tokens, completion_tokens,
            cost_usd, success, error_msg, duration_ms)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (provider, model, feature, prompt_tok, comp_tok, cost, int(success), error, duration_ms))

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4 — SEEDER
# ═════════════════════════════════════════════════════════════════════════════

SAMPLE_TEAM = [
    ("Alice Chen",   "Tech Lead",       ["Python","Architecture","AWS"],  85.0, 75.0),
    ("Bob Smith",    "Frontend Dev",    ["React","TypeScript","CSS"],      70.0, 85.0),
    ("Carol Davis",  "Backend Dev",     ["Python","FastAPI","PostgreSQL"], 90.0, 65.0),
    ("David Wilson", "DevOps",          ["AWS","Docker","Terraform"],      75.0, 80.0),
    ("Eva Brown",    "QA Engineer",     ["Selenium","pytest","k6"],        60.0, 90.0),
    ("Frank Miller", "Product Manager", ["Agile","Scrum","Figma"],         80.0, 70.0),
]

def seed_if_empty():
    if get_projects():
        return
    pid = str(uuid.uuid4())
    db_exec("""
        INSERT INTO projects (id, name, description, status, start_date, end_date, team_size, velocity, budget)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (pid, "E-Commerce Platform",
          "Modern e-commerce with AI-driven product recommendations",
          "active", "2024-01-15", "2024-09-30", 6, 45.5, 150_000.0))

    for name, role, skills, workload, morale in SAMPLE_TEAM:
        db_exec("""
            INSERT INTO team_members (id, project_id, name, role, skills, workload, morale)
            VALUES (?,?,?,?,?,?,?)
        """, (str(uuid.uuid4()), pid, name, role, json.dumps(skills), workload, morale))

    for i in range(1, 7):
        planned, completed = 45, max(28, 42 - max(0, (i-4)*5))
        blockers = ["Third-party API outage"] if i == 3 else []
        db_exec("""
            INSERT INTO sprints (id, project_id, number, start_date, end_date, planned_points, completed_points, blockers)
            VALUES (?,?,?,?,?,?,?,?)
        """, (str(uuid.uuid4()), pid, i, f"2024-{i:02d}-01", f"2024-{i:02d}-14",
              planned, completed, json.dumps(blockers)))

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5 — RATE LIMITER
# ═════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    def __init__(self, max_tokens: int, period: float = 60.0):
        self._max = float(max_tokens)
        self._tokens = float(max_tokens)
        self._period = period
        self._last = time.monotonic()
        self._lock = Lock()

    def acquire(self) -> bool:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self._max, self._tokens + (now - self._last) / self._period * self._max)
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

# Singleton rate limiter stored in session state
def get_rate_limiter() -> RateLimiter:
    if "_rate_limiter" not in st.session_state:
        st.session_state._rate_limiter = RateLimiter(RATE_LIMIT_RPM)
    return st.session_state._rate_limiter

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 6 — AI ENGINE
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class AIResponse:
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    cost_usd: float = 0.0
    duration_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""

def call_ai(prompt: str, feature: str = "general", context: Optional[dict] = None) -> AIResponse:
    """Make an AI API call with budget, rate, and retry guards."""
    cfg = get_ai_config()
    if not cfg or not cfg.get("api_key"):
        return AIResponse(False, error="AI not configured — add API key in ⚙️ Settings")

    monthly_cost = get_monthly_cost()
    budget = cfg.get("monthly_budget", MONTHLY_BUDGET)
    if monthly_cost >= budget:
        return AIResponse(False, error=f"Monthly budget of ${budget:.2f} exceeded (${monthly_cost:.2f} spent)")

    if not get_rate_limiter().acquire():
        return AIResponse(False, error="Rate limit reached — wait a moment and try again")

    model   = cfg.get("model", "deepseek-chat")
    api_key = cfg["api_key"]
    base_url = cfg.get("base_url", DEEPSEEK_URL)

    messages = [{"role": "system", "content": SYSTEM_PROMPTS.get(feature, SYSTEM_PROMPTS["general"])}]
    if context:
        messages.append({"role": "user", "content": f"Context: {json.dumps(context, separators=(',',':'))[:1500]}"})
    messages.append({"role": "user", "content": prompt[:2000]})

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": 0.7, "max_tokens": MAX_TOKENS, "stream": False}

    last_error = ""
    for attempt in range(3):
        if attempt > 0:
            time.sleep(2 ** attempt)
        try:
            t0 = time.monotonic()
            r = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=AI_TIMEOUT)
            duration_ms = int((time.monotonic() - t0) * 1000)

            if r.status_code == 200:
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                ptok = usage.get("prompt_tokens", 0)
                ctok = usage.get("completion_tokens", 0)
                p = PRICING.get(model, {"in": 0.14, "out": 0.28})
                cost = ptok / 1e6 * p["in"] + ctok / 1e6 * p["out"]
                log_ai_usage("deepseek", model, feature, ptok, ctok, cost, True, None, duration_ms)
                return AIResponse(True, content=content, cost_usd=cost,
                                  duration_ms=duration_ms, prompt_tokens=ptok,
                                  completion_tokens=ctok, model=model)
            elif r.status_code in (429, 503):
                last_error = f"HTTP {r.status_code} (retrying)"
                continue
            else:
                last_error = f"HTTP {r.status_code}: {r.text[:150]}"
                break
        except requests.exceptions.Timeout:
            last_error = "Request timed out"
        except requests.exceptions.ConnectionError:
            last_error = "Cannot reach API — check network"
            break
        except Exception as e:
            last_error = str(e)
            break

    log_ai_usage("deepseek", model, feature, 0, 0, 0, False, last_error, 0)
    return AIResponse(False, error=last_error)

def test_api_key(api_key: str, base_url: str) -> tuple[bool, str]:
    try:
        r = requests.post(f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat",
                  "messages": [{"role": "user", "content": "Reply with OK only."}],
                  "max_tokens": 5},
            timeout=10)
        if r.status_code == 200:
            return True, "✅ API key valid — connection successful"
        return False, f"❌ HTTP {r.status_code}: {r.text[:100]}"
    except requests.exceptions.ConnectionError:
        return False, "❌ Cannot reach endpoint — check URL and network"
    except requests.exceptions.Timeout:
        return False, "❌ Connection timed out"
    except Exception as e:
        return False, f"❌ {e}"

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 7 — UI HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def badge(text: str, color: str) -> str:
    """Inline HTML badge."""
    bg = {"green":"#d1fae5","yellow":"#fef3c7","red":"#fee2e2",
          "blue":"#dbeafe","gray":"#f3f4f6"}.get(color, "#f3f4f6")
    fg = {"green":"#065f46","yellow":"#92400e","red":"#991b1b",
          "blue":"#1e40af","gray":"#374151"}.get(color, "#374151")
    return f'<span style="background:{bg};color:{fg};padding:2px 10px;border-radius:12px;font-size:0.78rem;font-weight:600">{text}</span>'

def status_color(status: str) -> str:
    return {"active":"green","planning":"blue","completed":"gray","on_hold":"yellow"}.get(status,"gray")

def morale_color(v: float) -> str:
    return "green" if v > 70 else "yellow" if v > 50 else "red"

def workload_color(v: float) -> str:
    return "green" if v < 70 else "yellow" if v < 85 else "red"

def metric_card(col, label, value, sub="", delta=None):
    col.metric(label=label, value=value, delta=delta, help=sub)

def render_ai_result(resp: AIResponse, header: str):
    if resp.success:
        st.success(f"**{header}**")
        st.markdown(resp.content)
        st.caption(f"Model: {resp.model} · Cost: ${resp.cost_usd:.6f} · {resp.duration_ms}ms")
    else:
        st.error(f"AI Error: {resp.error}")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 8 — PAGES
# ═════════════════════════════════════════════════════════════════════════════

# ── Dashboard ─────────────────────────────────────────────────────────────

def page_dashboard():
    st.header("📊 Dashboard")

    projects = get_projects()
    if not projects:
        st.info("No projects found. Add one in the Projects page.")
        return

    project = projects[0]
    pid = project["id"]
    team = get_team(pid)
    sprints = get_sprints(pid)

    avg_morale   = sum(m["morale"] for m in team)   / len(team) if team else 75.0
    avg_workload = sum(m["workload"] for m in team)  / len(team) if team else 70.0
    monthly_cost = get_monthly_cost()
    cfg          = get_ai_config()
    budget       = cfg["monthly_budget"] if cfg else MONTHLY_BUDGET

    # ── KPI row ──────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Project", project["name"], project["status"].title())
    c2.metric("Team Morale", f"{avg_morale:.1f}/100",
              f"{'▲' if avg_morale > 70 else '▼'} {'Good' if avg_morale > 70 else 'At risk'}")
    c3.metric("Avg Workload", f"{avg_workload:.1f}%",
              f"{'▼ Healthy' if avg_workload < 70 else '▲ High'}")
    c4.metric("AI Spend (MTD)", f"${monthly_cost:.4f}",
              f"${budget - monthly_cost:.2f} remaining")

    st.divider()

    # ── Charts ────────────────────────────────────────────────
    col_l, col_r = st.columns(2)

    with col_l:
        if sprints:
            df_vel = pd.DataFrame([
                {"Sprint": f"S{s['number']}", "Planned": s["planned_points"], "Completed": s["completed_points"]}
                for s in sprints[-6:]
            ])
            fig = px.line(df_vel, x="Sprint", y=["Planned","Completed"],
                          title="Velocity Trend", markers=True,
                          color_discrete_map={"Planned":"#94a3b8","Completed":"#3b82f6"})
            fig.update_layout(margin=dict(l=0,r=0,t=35,b=0), legend_title="")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No sprint data yet.")

    with col_r:
        if team:
            df_team = pd.DataFrame([
                {"Name": m["name"].split()[0], "Workload": m["workload"], "Morale": m["morale"]}
                for m in team
            ])
            fig2 = px.bar(df_team, x="Name", y=["Workload","Morale"], barmode="group",
                          title="Team Health",
                          color_discrete_map={"Workload":"#f97316","Morale":"#10b981"})
            fig2.update_layout(margin=dict(l=0,r=0,t=35,b=0), legend_title="")
            st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # ── AI Actions ────────────────────────────────────────────
    st.subheader("🤖 AI Analysis")

    if not (cfg and cfg.get("api_key")):
        st.warning("AI not configured. Go to ⚙️ **Settings** and add your DeepSeek API key.")

    b1, b2, b3 = st.columns(3)
    run_health   = b1.button("🧠 Analyse Health",    use_container_width=True)
    run_simulate = b2.button("🎲 Run Simulation",    use_container_width=True)
    run_compare  = b3.button("🔗 Compare Projects",  use_container_width=True)

    p_ctx = {k: project[k] for k in ("name","status","team_size","velocity","budget")}

    if run_health:
        with st.spinner("Analysing project health..."):
            team_summary = {"avg_morale": avg_morale, "avg_workload": avg_workload, "count": len(team)}
            prompt = (
                f"Analyse health of '{project['name']}'. "
                f"Morale: {avg_morale:.1f}/100, Workload: {avg_workload:.1f}%, Team: {len(team)}.\n"
                "Provide: 1) Health score 1–10 with rationale  2) Top risk  3) One immediate action."
            )
            resp = call_ai(prompt, "therapy", {"project": p_ctx, "team": team_summary})
        render_ai_result(resp, "🧠 Health Analysis")

    if run_simulate:
        with st.spinner("Running simulation..."):
            prompt = (
                f"Simulate impact of adding 2 senior devs and removing 1 junior on '{project['name']}'. "
                f"Team: {project['team_size']}, velocity: {project['velocity']:.1f}, budget: ${project['budget']:,.0f}. "
                "Provide: 1) Probable outcome (% probability)  2) Main risk  3) Schedule impact."
            )
            resp = call_ai(prompt, "simulator", p_ctx)
        render_ai_result(resp, "🎲 Scenario Simulation")

    if run_compare:
        all_p = get_projects()
        if len(all_p) < 2:
            st.info("Only one project exists — creating a second for demo comparison.")
            p2id = str(uuid.uuid4())
            db_exec("""INSERT INTO projects (id,name,description,status,team_size,velocity,budget)
                       VALUES (?,?,?,?,?,?,?)""",
                    (p2id,"Mobile App (Demo)","Auto-created for comparison","planning",4,30.0,80000.0))
            all_p = get_projects()
        with st.spinner("Comparing projects..."):
            p2 = all_p[1]
            prompt = (
                f"Compare: A='{project['name']}' (status:{project['status']}, vel:{project['velocity']:.1f}, "
                f"budget:${project['budget']:,.0f}) vs "
                f"B='{p2['name']}' (status:{p2['status']}, vel:{p2['velocity']:.1f}, budget:${p2['budget']:,.0f}). "
                "Provide: 1) Key similarity  2) Biggest difference  3) Lesson from better performer."
            )
            resp = call_ai(prompt, "insights")
        render_ai_result(resp, "🔗 Project Comparison")


# ── Projects ──────────────────────────────────────────────────────────────

def page_projects():
    st.header("📋 Projects")

    projects = get_projects()
    if not projects:
        st.info("No projects yet.")
    else:
        # Table
        df = pd.DataFrame([{
            "Name":     p["name"],
            "Status":   p["status"].title(),
            "Team":     p["team_size"],
            "Velocity": f"{p['velocity']:.1f}",
            "Budget":   f"${p['budget']:,.0f}",
            "Start":    p.get("start_date","—"),
            "End":      p.get("end_date","—"),
        } for p in projects])
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Drill-down
        st.subheader("Project Detail")
        names = [p["name"] for p in projects]
        selected = st.selectbox("Select project", names)
        project = next(p for p in projects if p["name"] == selected)
        pid = project["id"]
        team = get_team(pid)
        sprints = get_sprints(pid)

        with st.expander("📌 Info", expanded=True):
            a, b = st.columns(2)
            a.write(f"**Description:** {project.get('description','—')}")
            a.write(f"**Timeline:** {project.get('start_date','?')} → {project.get('end_date','?')}")
            a.write(f"**Budget:** ${project['budget']:,.2f}")
            a.write(f"**Team size:** {len(team)} members")
            if sprints:
                recent = sprints[-3:]
                avg_v = sum(s["completed_points"] for s in recent) / len(recent)
                b.write(f"**Avg velocity:** {avg_v:.1f} pts/sprint")
            b.write(f"**Total sprints:** {len(sprints)}")

        if sprints:
            with st.expander("🏃 Recent Sprints"):
                df_s = pd.DataFrame([{
                    "Sprint": f"Sprint {s['number']}",
                    "Planned": s["planned_points"],
                    "Completed": s["completed_points"],
                    "Progress %": f"{s['completion_pct']:.0f}%",
                    "Blockers": ", ".join(s["blockers"]) if s["blockers"] else "None",
                } for s in sprints[-5:]])
                st.dataframe(df_s, use_container_width=True, hide_index=True)

    st.divider()
    with st.expander("➕ Add New Project"):
        with st.form("new_project_form"):
            n  = st.text_input("Project Name *")
            d  = st.text_area("Description")
            s  = st.selectbox("Status", ["planning","active","on_hold","completed"])
            c1, c2 = st.columns(2)
            sd = c1.date_input("Start Date")
            ed = c2.date_input("End Date")
            c3, c4, c5 = st.columns(3)
            ts = c3.number_input("Team Size", 1, 100, 4)
            vl = c4.number_input("Velocity (pts)", 1.0, 500.0, 30.0)
            bg = c5.number_input("Budget ($)", 0.0, 10_000_000.0, 50_000.0, step=1000.0)
            if st.form_submit_button("Create Project", type="primary"):
                if not n.strip():
                    st.error("Project name is required.")
                else:
                    db_exec("""
                        INSERT INTO projects (id,name,description,status,start_date,end_date,team_size,velocity,budget)
                        VALUES (?,?,?,?,?,?,?,?,?)
                    """, (str(uuid.uuid4()), n.strip(), d, s, str(sd), str(ed), ts, vl, bg))
                    st.success(f"Project '{n}' created!")
                    st.rerun()


# ── Team ──────────────────────────────────────────────────────────────────

def page_team():
    st.header("👥 Team")

    projects = get_projects()
    if not projects:
        st.info("Create a project first.")
        return

    names = [p["name"] for p in projects]
    sel = st.selectbox("Project", names)
    project = next(p for p in projects if p["name"] == sel)
    pid = project["id"]
    team = get_team(pid)

    if not team:
        st.info("No team members yet. Add one below.")
    else:
        avg_morale   = sum(m["morale"]   for m in team) / len(team)
        avg_workload = sum(m["workload"] for m in team) / len(team)
        overloaded   = sum(1 for m in team if m["workload"] > 85)
        low_morale_n = sum(1 for m in team if m["morale"]   < 60)

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Team Size",    len(team))
        c2.metric("Avg Morale",   f"{avg_morale:.1f}/100")
        c3.metric("Avg Workload", f"{avg_workload:.1f}%")
        c4.metric("At Risk",      overloaded + low_morale_n,
                  f"{overloaded} overloaded · {low_morale_n} low morale",
                  delta_color="inverse")

        st.divider()

        # Member cards
        for i, m in enumerate(team):
            with st.container(border=True):
                a, b, c = st.columns([3,2,3])
                a.markdown(f"**{m['name']}**  \n*{m['role']}*")
                wc = workload_color(m["workload"])
                mc = morale_color(m["morale"])
                b.markdown(
                    f"Workload: {badge(f\"{m['workload']:.0f}%\", wc)}  \n"
                    f"Morale:&nbsp;&nbsp;&nbsp;{badge(f\"{m['morale']:.0f}/100\", mc)}",
                    unsafe_allow_html=True,
                )
                c.markdown(f"Skills: `{'` · `'.join(m['skills']) if m['skills'] else 'None'}`")

    st.divider()
    with st.expander("➕ Add Team Member"):
        with st.form("add_member_form"):
            n  = st.text_input("Name *")
            r  = st.text_input("Role")
            sk = st.text_input("Skills (comma-separated)", placeholder="Python, AWS, Docker")
            c1, c2 = st.columns(2)
            wl = c1.slider("Workload %", 0, 100, 70)
            mr = c2.slider("Morale",     0, 100, 80)
            if st.form_submit_button("Add Member", type="primary"):
                if not n.strip():
                    st.error("Name is required.")
                else:
                    skills = [s.strip() for s in sk.split(",") if s.strip()]
                    db_exec("""
                        INSERT INTO team_members (id,project_id,name,role,skills,workload,morale)
                        VALUES (?,?,?,?,?,?,?)
                    """, (str(uuid.uuid4()), pid, n.strip(), r, json.dumps(skills), wl, mr))
                    st.success(f"Added {n}!")
                    st.rerun()


# ── Settings ──────────────────────────────────────────────────────────────

def page_settings():
    st.header("⚙️ AI Settings")

    cfg = get_ai_config()
    monthly_cost = get_monthly_cost()
    budget = cfg["monthly_budget"] if cfg else MONTHLY_BUDGET
    budget_pct = min(100.0, monthly_cost / budget * 100) if budget else 0

    st.info(
        "**Get a free API key:** [platform.deepseek.com](https://platform.deepseek.com) → "
        "Sign up → API Keys → Create. Keys are stored **encrypted** at rest.",
        icon="ℹ️",
    )

    with st.form("ai_settings_form"):
        c1, c2 = st.columns(2)
        provider = c1.selectbox("Provider", ["deepseek"], index=0)
        model    = c2.selectbox("Model",
                    ["deepseek-chat","deepseek-coder"],
                    index=0 if not cfg else ["deepseek-chat","deepseek-coder"].index(cfg.get("model","deepseek-chat")))
        base_url = st.text_input("Base URL", value=cfg.get("base_url", DEEPSEEK_URL) if cfg else DEEPSEEK_URL)

        api_key = st.text_input(
            "API Key",
            type="password",
            placeholder="sk-... " + (f"(saved: {mask_key(cfg['api_key'])})" if cfg and cfg.get("api_key") else "(not set)"),
            help="Leave blank to keep existing key.",
        )

        st.subheader("Features")
        feat_options = {"therapy":"🎭 Project Therapist","simulator":"🎲 What-If Simulator","insights":"🔗 Cross-Project Insights"}
        current_feats = cfg["features"] if cfg else list(feat_options.keys())
        features = [k for k, v in feat_options.items() if st.checkbox(v, value=k in current_feats, key=f"feat_{k}")]

        st.subheader("Budget")
        new_budget = st.number_input("Monthly Budget (USD)", min_value=1.0, value=float(budget), step=5.0)
        st.progress(budget_pct / 100, text=f"${monthly_cost:.4f} of ${budget:.2f} used ({budget_pct:.1f}%)")

        submitted = st.form_submit_button("💾 Save Configuration", type="primary")

    if submitted:
        key_to_save = api_key.strip() if api_key and api_key.strip() else (cfg["api_key"] if cfg else "")
        if not key_to_save:
            st.error("API key is required.")
        elif not features:
            st.error("Enable at least one feature.")
        elif new_budget <= 0:
            st.error("Budget must be > $0.")
        else:
            save_ai_config(provider, key_to_save, model, base_url, new_budget, features)
            st.success("✅ Configuration saved!")
            st.rerun()

    # ── Test connection (outside form) ───────────────────────
    st.divider()
    st.subheader("🔌 Test Connection")
    test_key = st.text_input("API key to test", type="password", key="test_key_input")
    test_url = st.text_input("Base URL", value=DEEPSEEK_URL, key="test_url_input")
    if st.button("Test"):
        if not test_key:
            st.warning("Enter a key to test.")
        else:
            with st.spinner("Connecting..."):
                ok, msg = test_api_key(test_key, test_url)
            (st.success if ok else st.error)(msg)

    # ── Usage log ─────────────────────────────────────────────
    st.divider()
    st.subheader("📈 Usage Log (last 20)")
    rows = db_rows("""
        SELECT created_at, feature, model, prompt_tokens, completion_tokens,
               ROUND(cost_usd,6) AS cost_usd,
               CASE success WHEN 1 THEN '✅' ELSE '❌' END AS ok,
               error_msg
        FROM ai_usage_log ORDER BY created_at DESC LIMIT 20
    """)
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No usage recorded yet.")


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 9 — MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Bootstrap
    init_db()
    seed_if_empty()

    # ── Sidebar ───────────────────────────────────────────────
    with st.sidebar:
        st.markdown(f"## 🤖 {APP_TITLE}")
        st.caption(f"v{APP_VERSION}")
        st.divider()

        page = st.radio(
            "Navigate",
            ["📊 Dashboard", "📋 Projects", "👥 Team", "⚙️ Settings"],
            label_visibility="collapsed",
        )

        st.divider()

        # Health snapshot
        cfg = get_ai_config()
        ai_ok = bool(cfg and cfg.get("api_key"))
        projects = get_projects()
        monthly_cost = get_monthly_cost()
        budget = cfg["monthly_budget"] if cfg else MONTHLY_BUDGET
        budget_pct = min(100.0, monthly_cost / budget * 100) if budget else 0

        st.markdown("**System Status**")
        st.markdown(f"{'🟢' if ai_ok else '🔴'} AI: {'Ready' if ai_ok else 'Not configured'}")
        st.markdown(f"🟢 DB: {len(projects)} project(s)")
        st.progress(budget_pct / 100, text=f"Budget: {budget_pct:.1f}% used")

        if not ai_ok:
            st.warning("Add API key in ⚙️ Settings.")

        st.divider()
        st.caption(f"DB: `{DB_PATH.name}`")
        if not CRYPTO_AVAILABLE:
            st.warning("⚠️ `cryptography` not installed — API keys stored unencrypted.\n`pip install cryptography`")

    # ── Page routing ──────────────────────────────────────────
    if "Dashboard" in page:
        page_dashboard()
    elif "Projects" in page:
        page_projects()
    elif "Team" in page:
        page_team()
    elif "Settings" in page:
        page_settings()


if __name__ == "__main__":
    main()
