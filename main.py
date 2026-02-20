"""
Project Command — IBM Carbon Edition
=====================================
Run:
    pip install streamlit plotly pandas requests cryptography
    streamlit run app.py

IBM Carbon Design System aesthetic:
  • IBM Plex Mono + IBM Plex Sans typography
  • Dark UI: #161616 base, #262626 layer, #0f62fe interactive blue
  • Precise 8px grid, sharp corners, utilitarian data-density
  • No gradients, no shadows — geometry and contrast carry weight

New features vs v1:
  • Sprint planning board (create / edit sprints)
  • Risk register with severity matrix
  • Budget tracker with burn-down chart
  • Retrospective notes per sprint
  • Export data to CSV
  • Dark IBM Carbon UI throughout
  • Team member edit / delete
  • Project status transitions with history log
  • AI: generate retro summary, risk analysis, sprint forecast
  • AI usage analytics chart
"""

# ─────────────────────────────────────────────────────────────────────────────
import base64, hashlib, json, os, sqlite3, time, uuid, math
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from threading import Lock
from typing import Optional
import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

try:
    from cryptography.fernet import Fernet, InvalidToken
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════
APP_TITLE      = "Project Command"
APP_VERSION    = "3.0.0"
DB_PATH        = Path(os.getenv("DATABASE_PATH", "project_command.db"))
SECRET_KEY     = os.getenv("APP_SECRET_KEY", "dev-secret-key-change-in-production-32c")
DEEPSEEK_URL   = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MONTHLY_BUDGET = float(os.getenv("AI_MONTHLY_BUDGET_USD", "50.0"))
MAX_TOKENS     = int(os.getenv("AI_MAX_TOKENS", "1200"))
RATE_LIMIT_RPM = int(os.getenv("AI_RATE_LIMIT_RPM", "20"))
AI_TIMEOUT     = int(os.getenv("AI_TIMEOUT_SECONDS", "30"))

PRICING = {
    "deepseek-chat":  {"in": 0.14, "out": 0.28},
    "deepseek-coder": {"in": 0.14, "out": 0.28},
}

SYSTEM_PROMPTS = {
    "therapy":    "You are a senior project management consultant. Provide structured, evidence-based analysis. Use bullet points. Max 300 words.",
    "simulator":  "You are a quantitative risk and schedule simulator. Provide probabilistic forecasts with ranges. Max 300 words.",
    "insights":   "You are a cross-project portfolio analyst. Identify patterns and transferable lessons. Be precise. Max 300 words.",
    "retro":      "You are an agile coach facilitating a sprint retrospective. Structure as: Went Well / Improve / Action Items. Max 300 words.",
    "risk":       "You are a project risk analyst. Rate risks by probability and impact. Format as a structured list. Max 300 words.",
    "forecast":   "You are a sprint velocity forecasting expert. Provide data-driven delivery date estimates with confidence intervals. Max 300 words.",
    "general":    "You are a professional project management assistant. Be concise and actionable. Max 300 words.",
}

# IBM Carbon colours
C_BG        = "#161616"
C_LAYER     = "#262626"
C_LAYER2    = "#393939"
C_BORDER    = "#525252"
C_BLUE      = "#0f62fe"
C_CYAN      = "#0043ce"
C_TEXT      = "#f4f4f4"
C_TEXT_SEC  = "#a8a8a8"
C_GREEN     = "#24a148"
C_YELLOW    = "#f1c21b"
C_RED       = "#da1e28"
C_ORANGE    = "#ff832b"

# ═════════════════════════════════════════════════════════════════════════════
# IBM CARBON CSS INJECTION
# ═════════════════════════════════════════════════════════════════════════════
def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

    /* ── Global reset ── */
    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', sans-serif !important;
        background-color: #161616 !important;
        color: #f4f4f4 !important;
    }

    /* ── Main container ── */
    .main .block-container {
        padding: 1.5rem 2rem 4rem 2rem !important;
        max-width: 1400px !important;
        background: #161616 !important;
    }

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {
        background: #0f0f0f !important;
        border-right: 1px solid #393939 !important;
    }
    section[data-testid="stSidebar"] * { color: #f4f4f4 !important; }
    section[data-testid="stSidebar"] .stRadio label {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.82rem !important;
        letter-spacing: 0.04em !important;
        padding: 6px 0 !important;
    }

    /* ── Page headers ── */
    h1, h2, h3 {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: -0.01em !important;
        color: #f4f4f4 !important;
    }
    h1 { font-size: 2rem !important; border-bottom: 2px solid #0f62fe; padding-bottom: 0.5rem; }
    h2 { font-size: 1.4rem !important; color: #c6c6c6 !important; }
    h3 { font-size: 1.1rem !important; color: #a8a8a8 !important; }

    /* ── Metric cards ── */
    [data-testid="metric-container"] {
        background: #262626 !important;
        border: 1px solid #393939 !important;
        border-top: 3px solid #0f62fe !important;
        padding: 1rem !important;
        border-radius: 0 !important;
    }
    [data-testid="metric-container"] label {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.72rem !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        color: #a8a8a8 !important;
    }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 1.8rem !important;
        font-weight: 600 !important;
        color: #f4f4f4 !important;
    }
    [data-testid="metric-container"] [data-testid="stMetricDelta"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.78rem !important;
    }

    /* ── Buttons ── */
    .stButton > button {
        background: #0f62fe !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 0 !important;
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 500 !important;
        font-size: 0.875rem !important;
        letter-spacing: 0.01em !important;
        padding: 0.6rem 1.2rem !important;
        transition: background 0.1s !important;
    }
    .stButton > button:hover { background: #0043ce !important; }
    .stButton > button[kind="secondary"] {
        background: #393939 !important;
        color: #f4f4f4 !important;
    }
    .stButton > button[kind="secondary"]:hover { background: #525252 !important; }

    /* ── Inputs ── */
    .stTextInput input, .stNumberInput input, .stTextArea textarea,
    .stSelectbox > div > div, .stMultiselect > div > div {
        background: #262626 !important;
        border: 1px solid #525252 !important;
        border-radius: 0 !important;
        color: #f4f4f4 !important;
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.875rem !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #0f62fe !important;
        box-shadow: inset 0 0 0 2px #0f62fe !important;
    }
    label { color: #c6c6c6 !important; font-size: 0.8rem !important; font-weight: 500 !important; }

    /* ── Dataframes ── */
    .stDataFrame { border: 1px solid #393939 !important; }
    .stDataFrame thead tr th {
        background: #393939 !important;
        color: #c6c6c6 !important;
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.72rem !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        border-bottom: 2px solid #525252 !important;
    }
    .stDataFrame tbody tr td {
        background: #262626 !important;
        color: #f4f4f4 !important;
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.82rem !important;
        border-bottom: 1px solid #393939 !important;
    }
    .stDataFrame tbody tr:hover td { background: #333333 !important; }

    /* ── Expanders ── */
    details {
        background: #1e1e1e !important;
        border: 1px solid #393939 !important;
        border-radius: 0 !important;
        padding: 0 !important;
    }
    summary {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.82rem !important;
        letter-spacing: 0.04em !important;
        padding: 0.8rem 1rem !important;
        color: #c6c6c6 !important;
        background: #262626 !important;
        border-bottom: 1px solid #393939 !important;
    }

    /* ── Divider ── */
    hr { border-color: #393939 !important; margin: 1.5rem 0 !important; }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        background: #1e1e1e !important;
        border-bottom: 2px solid #393939 !important;
        gap: 0 !important;
    }
    .stTabs [data-baseweb="tab"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.8rem !important;
        letter-spacing: 0.04em !important;
        color: #a8a8a8 !important;
        background: transparent !important;
        border-radius: 0 !important;
        padding: 0.75rem 1.25rem !important;
        border-bottom: 3px solid transparent !important;
    }
    .stTabs [aria-selected="true"] {
        color: #f4f4f4 !important;
        border-bottom: 3px solid #0f62fe !important;
        background: transparent !important;
    }
    .stTabs [data-baseweb="tab-panel"] {
        background: #161616 !important;
        padding-top: 1.5rem !important;
    }

    /* ── Progress bars ── */
    .stProgress > div > div {
        background: #393939 !important;
        border-radius: 0 !important;
        height: 6px !important;
    }
    .stProgress > div > div > div {
        background: #0f62fe !important;
        border-radius: 0 !important;
    }

    /* ── Alerts ── */
    .stAlert { border-radius: 0 !important; border-left: 4px solid !important; }
    .stSuccess { border-left-color: #24a148 !important; background: #0d2e1a !important; }
    .stError   { border-left-color: #da1e28 !important; background: #2d0a0e !important; }
    .stWarning { border-left-color: #f1c21b !important; background: #2c2200 !important; }
    .stInfo    { border-left-color: #0f62fe !important; background: #01162e !important; }

    /* ── Checkboxes / Radio ── */
    .stCheckbox label, .stRadio label {
        color: #c6c6c6 !important;
        font-size: 0.875rem !important;
    }

    /* ── Slider ── */
    .stSlider [data-testid="stThumbValue"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.78rem !important;
    }

    /* ── Select boxes dropdown ── */
    [data-baseweb="select"] * { background: #262626 !important; color: #f4f4f4 !important; }
    [data-baseweb="popover"] { background: #262626 !important; border: 1px solid #525252 !important; }

    /* ── IBM tag styles ── */
    .ibm-tag {
        display: inline-block;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.7rem;
        letter-spacing: 0.04em;
        padding: 2px 8px;
        margin: 1px 2px;
        border: 1px solid;
    }
    .ibm-tag-blue   { background: #001d6c; border-color: #0f62fe; color: #78a9ff; }
    .ibm-tag-green  { background: #071908; border-color: #24a148; color: #42be65; }
    .ibm-tag-yellow { background: #1c1500; border-color: #f1c21b; color: #f1c21b; }
    .ibm-tag-red    { background: #2d0a0e; border-color: #da1e28; color: #ff8389; }
    .ibm-tag-gray   { background: #262626; border-color: #525252; color: #a8a8a8; }
    .ibm-tag-orange { background: #231000; border-color: #ff832b; color: #ff832b; }

    /* ── Carbon card ── */
    .carbon-card {
        background: #262626;
        border: 1px solid #393939;
        border-top: 3px solid #0f62fe;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
    }
    .carbon-card-red  { border-top-color: #da1e28 !important; }
    .carbon-card-green{ border-top-color: #24a148 !important; }
    .carbon-card-yellow{ border-top-color: #f1c21b !important; }

    /* ── Mono labels ── */
    .mono-label {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.7rem;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #a8a8a8;
        margin-bottom: 4px;
    }
    .mono-value {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.4rem;
        font-weight: 600;
        color: #f4f4f4;
    }

    /* ── Risk matrix cell ── */
    .risk-cell {
        display: inline-block;
        width: 52px; height: 52px;
        line-height: 52px;
        text-align: center;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.75rem;
        font-weight: 600;
        border: 1px solid #393939;
    }

    /* ── Scrollable code block ── */
    .stCodeBlock { border-radius: 0 !important; }

    /* ── Form submit btn ── */
    .stForm [data-testid="stFormSubmitButton"] button {
        background: #24a148 !important;
        width: 100% !important;
    }
    .stForm [data-testid="stFormSubmitButton"] button:hover { background: #198038 !important; }

    /* ── Hide streamlit branding ── */
    #MainMenu, footer, header { visibility: hidden !important; }
    </style>
    """, unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# SECURITY
# ═════════════════════════════════════════════════════════════════════════════
def _fernet_key() -> bytes:
    digest = hashlib.sha256(SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)

def encrypt_secret(plaintext: str) -> str:
    if not plaintext or not CRYPTO_AVAILABLE:
        return plaintext
    return Fernet(_fernet_key()).encrypt(plaintext.encode()).decode()

def decrypt_secret(ciphertext: str) -> Optional[str]:
    if not ciphertext:
        return None
    if not CRYPTO_AVAILABLE:
        return ciphertext
    try:
        return Fernet(_fernet_key()).decrypt(ciphertext.encode()).decode()
    except Exception:
        return None

def mask_key(key: str) -> str:
    return key[:8] + "···" + "●" * 8 if key and len(key) > 8 else "●●●"

# ═════════════════════════════════════════════════════════════════════════════
# DATABASE
# ═════════════════════════════════════════════════════════════════════════════
@contextmanager
def get_conn():
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
            priority TEXT DEFAULT 'medium',
            start_date TEXT, end_date TEXT,
            team_size INTEGER DEFAULT 1,
            velocity REAL DEFAULT 20.0,
            budget REAL DEFAULT 10000.0,
            budget_spent REAL DEFAULT 0.0,
            total_points INTEGER DEFAULT 0,
            completed_points INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS project_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            detail TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS team_members (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            role TEXT,
            email TEXT,
            workload REAL DEFAULT 0.0,
            morale REAL DEFAULT 80.0,
            skills TEXT DEFAULT '[]',
            daily_rate REAL DEFAULT 0.0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sprints (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            number INTEGER NOT NULL,
            goal TEXT,
            start_date TEXT, end_date TEXT,
            planned_points INTEGER DEFAULT 0,
            completed_points INTEGER DEFAULT 0,
            blockers TEXT DEFAULT '[]',
            retro_notes TEXT DEFAULT '{}',
            status TEXT DEFAULT 'planned',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS risks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT DEFAULT 'technical',
            probability INTEGER DEFAULT 2,
            impact INTEGER DEFAULT 2,
            status TEXT DEFAULT 'open',
            owner TEXT,
            mitigation TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS budget_entries (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            entry_type TEXT DEFAULT 'expense',
            category TEXT DEFAULT 'other',
            entry_date TEXT DEFAULT (date('now')),
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS ai_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT DEFAULT 'deepseek',
            encrypted_api_key TEXT,
            model TEXT DEFAULT 'deepseek-chat',
            base_url TEXT DEFAULT 'https://api.deepseek.com',
            monthly_budget REAL DEFAULT 50.0,
            features TEXT DEFAULT '["therapy","simulator","insights","retro","risk","forecast"]',
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

# ── Query helpers ─────────────────────────────────────────────────────────────
def db_rows(q, p=()):
    with get_conn() as c: return [dict(r) for r in c.execute(q, p).fetchall()]

def db_one(q, p=()):
    with get_conn() as c:
        r = c.execute(q, p).fetchone(); return dict(r) if r else None

def db_exec(q, p=()):
    with get_conn() as c: c.execute(q, p)

def db_execmany(q, rows):
    with get_conn() as c: c.executemany(q, rows)

# ── Project helpers ───────────────────────────────────────────────────────────
def get_projects(): return db_rows("SELECT * FROM projects ORDER BY created_at DESC")

def get_project(pid): return db_one("SELECT * FROM projects WHERE id=?", (pid,))

def get_team(pid):
    rows = db_rows("SELECT * FROM team_members WHERE project_id=? ORDER BY name", (pid,))
    for r in rows: r["skills"] = json.loads(r.get("skills") or "[]")
    return rows

def get_sprints(pid):
    rows = db_rows("SELECT * FROM sprints WHERE project_id=? ORDER BY number", (pid,))
    for r in rows:
        r["blockers"] = json.loads(r.get("blockers") or "[]")
        r["retro_notes"] = json.loads(r.get("retro_notes") or "{}")
        planned = r["planned_points"] or 1
        r["completion_pct"] = min(100.0, r["completed_points"] / planned * 100)
        r["velocity"] = r["completed_points"]
    return rows

def get_risks(pid): return db_rows("SELECT * FROM risks WHERE project_id=? ORDER BY probability*impact DESC", (pid,))

def get_budget_entries(pid): return db_rows("SELECT * FROM budget_entries WHERE project_id=? ORDER BY entry_date DESC", (pid,))

def get_project_history(pid): return db_rows("SELECT * FROM project_history WHERE project_id=? ORDER BY created_at DESC LIMIT 30", (pid,))

def log_event(pid, event_type, detail=""):
    db_exec("INSERT INTO project_history (project_id,event_type,detail) VALUES (?,?,?)", (pid, event_type, detail))

def get_ai_config():
    cfg = db_one("SELECT * FROM ai_config WHERE is_active=1 ORDER BY updated_at DESC LIMIT 1")
    if cfg:
        cfg["api_key"] = decrypt_secret(cfg.get("encrypted_api_key") or "")
        cfg["features"] = json.loads(cfg.get("features") or "[]")
    return cfg

def get_monthly_cost():
    r = db_one("SELECT COALESCE(SUM(cost_usd),0) AS t FROM ai_usage_log WHERE success=1 AND strftime('%Y-%m',created_at)=strftime('%Y-%m','now')")
    return float(r["t"]) if r else 0.0

def save_ai_config(provider, api_key, model, base_url, budget, features):
    db_exec("UPDATE ai_config SET is_active=0")
    db_exec("INSERT INTO ai_config (provider,encrypted_api_key,model,base_url,monthly_budget,features,is_active,updated_at) VALUES (?,?,?,?,?,?,1,datetime('now'))",
            (provider, encrypt_secret(api_key), model, base_url, budget, json.dumps(features)))

def log_ai_usage(provider, model, feature, ptok, ctok, cost, success, error, duration_ms):
    db_exec("INSERT INTO ai_usage_log (provider,model,feature,prompt_tokens,completion_tokens,cost_usd,success,error_msg,duration_ms) VALUES (?,?,?,?,?,?,?,?,?)",
            (provider, model, feature, ptok, ctok, cost, int(success), error, duration_ms))

# ═════════════════════════════════════════════════════════════════════════════
# SEEDER
# ═════════════════════════════════════════════════════════════════════════════
SAMPLE_TEAM = [
    ("Alice Chen",   "Tech Lead",       "alice@example.com",  ["Python","Architecture","AWS"],  85.0, 75.0, 800.0),
    ("Bob Smith",    "Frontend Dev",    "bob@example.com",    ["React","TypeScript","CSS"],      70.0, 85.0, 650.0),
    ("Carol Davis",  "Backend Dev",     "carol@example.com",  ["Python","FastAPI","PostgreSQL"], 90.0, 62.0, 700.0),
    ("David Wilson", "DevOps",          "david@example.com",  ["AWS","Docker","Terraform"],      75.0, 80.0, 750.0),
    ("Eva Brown",    "QA Engineer",     "eva@example.com",    ["Selenium","pytest","k6"],        60.0, 90.0, 600.0),
    ("Frank Miller", "Product Manager", "frank@example.com",  ["Agile","Scrum","Figma"],         80.0, 70.0, 720.0),
]

SAMPLE_RISKS = [
    ("Third-party API dependency",  "Core payments rely on external API with 99.5% SLA", "technical",  3, 4, "open",   "Alice Chen",   "Implement circuit breaker + fallback provider"),
    ("Key person dependency",       "Alice Chen holds critical architecture knowledge",   "people",     2, 5, "open",   "Frank Miller", "Knowledge transfer sessions + documentation sprint"),
    ("Regulatory compliance gap",   "GDPR audit scheduled Q4 — current coverage 60%",    "compliance", 3, 3, "mitigated","Carol Davis", "Engage external DPO, complete gap analysis"),
    ("Budget overrun risk",         "Infra costs trending 15% above forecast",           "financial",  3, 3, "open",   "David Wilson", "Reserved instance purchasing, cost alerting"),
    ("Scope creep",                 "Stakeholder feature requests growing each sprint",  "delivery",   4, 2, "open",   "Frank Miller", "Strict change control process, sprint goal lock-in"),
]

def seed_if_empty():
    if get_projects(): return
    pid = str(uuid.uuid4())
    db_exec("INSERT INTO projects (id,name,description,status,priority,start_date,end_date,team_size,velocity,budget,budget_spent,total_points,completed_points) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid,"E-Commerce Platform","Modern e-commerce with AI-driven product recommendations and real-time inventory","active","high","2024-01-15","2024-09-30",6,45.5,150000.0,87400.0,270,210))

    for name, role, email, skills, workload, morale, rate in SAMPLE_TEAM:
        db_exec("INSERT INTO team_members (id,project_id,name,role,email,skills,workload,morale,daily_rate) VALUES (?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()),pid,name,role,email,json.dumps(skills),workload,morale,rate))

    sprint_data = [(45,42,"Launch checkout flow","completed"),(45,40,"Payment integration","completed"),
                   (45,35,"API issues","completed"),(45,43,"Performance optimisation","completed"),
                   (45,38,"Mobile responsive","active"),(45,0,"Search & recommendations","planned")]
    for i,(pl,co,goal,status) in enumerate(sprint_data,1):
        blockers = ["Payment gateway timeout errors"] if i==3 else []
        db_exec("INSERT INTO sprints (id,project_id,number,goal,start_date,end_date,planned_points,completed_points,blockers,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()),pid,i,goal,f"2024-{i:02d}-01",f"2024-{i:02d}-14",pl,co,json.dumps(blockers),status))

    for title,desc,cat,prob,impact,status,owner,mitigation in SAMPLE_RISKS:
        db_exec("INSERT INTO risks (id,project_id,title,description,category,probability,impact,status,owner,mitigation) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()),pid,title,desc,cat,prob,impact,status,owner,mitigation))

    # Budget entries
    budget_items = [
        ("AWS infrastructure (Q1)","expense","infrastructure",12400.0,"2024-01-31"),
        ("Contractor: UX designer","expense","people",8500.0,"2024-02-15"),
        ("Software licences","expense","tools",3200.0,"2024-02-28"),
        ("AWS infrastructure (Q2)","expense","infrastructure",14100.0,"2024-04-30"),
        ("Security audit","expense","compliance",6800.0,"2024-03-20"),
        ("AWS infrastructure (Q3)","expense","infrastructure",13900.0,"2024-07-31"),
        ("Performance testing tools","expense","tools",1800.0,"2024-05-10"),
        ("Training: team certification","expense","people",4200.0,"2024-06-01"),
        ("Client milestone payment","income","revenue",22500.0,"2024-04-01"),
    ]
    for desc,etype,cat,amount,edate in budget_items:
        db_exec("INSERT INTO budget_entries (id,project_id,description,amount,entry_type,category,entry_date) VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()),pid,desc,amount,etype,cat,edate))

    log_event(pid,"project_created","Initial project setup")
    log_event(pid,"status_change","Status set to active")

# ═════════════════════════════════════════════════════════════════════════════
# RATE LIMITER
# ═════════════════════════════════════════════════════════════════════════════
class RateLimiter:
    def __init__(self, max_tokens, period=60.0):
        self._max=float(max_tokens); self._tokens=float(max_tokens)
        self._period=period; self._last=time.monotonic(); self._lock=Lock()
    def acquire(self):
        with self._lock:
            now=time.monotonic()
            self._tokens=min(self._max,self._tokens+(now-self._last)/self._period*self._max)
            self._last=now
            if self._tokens>=1.0: self._tokens-=1.0; return True
            return False

def get_rl():
    if "_rl" not in st.session_state: st.session_state._rl=RateLimiter(RATE_LIMIT_RPM)
    return st.session_state._rl

# ═════════════════════════════════════════════════════════════════════════════
# AI ENGINE
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
    cfg = get_ai_config()
    if not cfg or not cfg.get("api_key"):
        return AIResponse(False, error="AI not configured — add API key in ⚙ Settings")
    monthly_cost = get_monthly_cost()
    budget = cfg.get("monthly_budget", MONTHLY_BUDGET)
    if monthly_cost >= budget:
        return AIResponse(False, error=f"Monthly budget ${budget:.2f} exceeded (${monthly_cost:.2f} spent)")
    if not get_rl().acquire():
        return AIResponse(False, error="Rate limit — wait a moment")
    model = cfg.get("model","deepseek-chat")
    api_key = cfg["api_key"]
    base_url = cfg.get("base_url", DEEPSEEK_URL)
    messages = [{"role":"system","content":SYSTEM_PROMPTS.get(feature,SYSTEM_PROMPTS["general"])}]
    if context:
        messages.append({"role":"user","content":f"Context: {json.dumps(context,separators=(',',':'))[:2000]}"})
    messages.append({"role":"user","content":prompt[:2500]})
    headers = {"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}
    payload = {"model":model,"messages":messages,"temperature":0.7,"max_tokens":MAX_TOKENS,"stream":False}
    last_error = ""
    for attempt in range(3):
        if attempt > 0: time.sleep(2**attempt)
        try:
            t0 = time.monotonic()
            r = requests.post(f"{base_url}/chat/completions",headers=headers,json=payload,timeout=AI_TIMEOUT)
            dur = int((time.monotonic()-t0)*1000)
            if r.status_code==200:
                data=r.json(); content=data["choices"][0]["message"]["content"]
                usage=data.get("usage",{}); ptok=usage.get("prompt_tokens",0); ctok=usage.get("completion_tokens",0)
                p=PRICING.get(model,{"in":0.14,"out":0.28})
                cost=ptok/1e6*p["in"]+ctok/1e6*p["out"]
                log_ai_usage("deepseek",model,feature,ptok,ctok,cost,True,None,dur)
                return AIResponse(True,content=content,cost_usd=cost,duration_ms=dur,prompt_tokens=ptok,completion_tokens=ctok,model=model)
            elif r.status_code in (429,503): last_error=f"HTTP {r.status_code}"; continue
            else: last_error=f"HTTP {r.status_code}: {r.text[:150]}"; break
        except requests.exceptions.Timeout: last_error="Timeout"
        except requests.exceptions.ConnectionError: last_error="Cannot reach API"; break
        except Exception as e: last_error=str(e); break
    log_ai_usage("deepseek",model,feature,0,0,0,False,last_error,0)
    return AIResponse(False,error=last_error)

def test_api_key(api_key, base_url):
    try:
        r=requests.post(f"{base_url}/chat/completions",
            headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},
            json={"model":"deepseek-chat","messages":[{"role":"user","content":"Reply OK only."}],"max_tokens":5},
            timeout=10)
        if r.status_code==200: return True,"✅  API key valid"
        return False,f"❌  HTTP {r.status_code}: {r.text[:100]}"
    except requests.exceptions.ConnectionError: return False,"❌  Cannot reach endpoint"
    except requests.exceptions.Timeout: return False,"❌  Connection timed out"
    except Exception as e: return False,f"❌  {e}"

# ═════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ═════════════════════════════════════════════════════════════════════════════
RISK_SCORE_COLOR = {(1,1):"#393939",(1,2):"#393939",(1,3):"#f1c21b",(1,4):"#ff832b",(1,5):"#da1e28",
                    (2,1):"#393939",(2,2):"#f1c21b",(2,3):"#f1c21b",(2,4):"#ff832b",(2,5):"#da1e28",
                    (3,1):"#f1c21b",(3,2):"#f1c21b",(3,3):"#ff832b",(3,4):"#da1e28",(3,5):"#da1e28",
                    (4,1):"#ff832b",(4,2):"#ff832b",(4,3):"#da1e28",(4,4):"#da1e28",(4,5):"#da1e28",
                    (5,1):"#da1e28",(5,2):"#da1e28",(5,3):"#da1e28",(5,4):"#da1e28",(5,5):"#da1e28"}

def tag(text, kind="blue"):
    return f'<span class="ibm-tag ibm-tag-{kind}">{text}</span>'

def status_tag(status):
    m={"active":"green","planning":"blue","completed":"gray","on_hold":"yellow","at_risk":"red"}
    return tag(status.upper().replace("_"," "), m.get(status,"gray"))

def priority_tag(p):
    m={"critical":"red","high":"orange","medium":"yellow","low":"green"}
    return tag(p.upper(), m.get(p,"gray"))

def risk_score_tag(prob, impact):
    score = prob * impact
    if score>=12: return tag(f"CRITICAL  {score}","red")
    if score>=8:  return tag(f"HIGH  {score}","orange")
    if score>=4:  return tag(f"MEDIUM  {score}","yellow")
    return tag(f"LOW  {score}","gray")

def plotly_theme():
    return dict(
        plot_bgcolor="#1e1e1e", paper_bgcolor="#1e1e1e",
        font=dict(family="IBM Plex Mono", color="#c6c6c6", size=11),
        xaxis=dict(gridcolor="#393939", linecolor="#525252", tickcolor="#525252"),
        yaxis=dict(gridcolor="#393939", linecolor="#525252", tickcolor="#525252"),
        margin=dict(l=8,r=8,t=36,b=8),
        legend=dict(bgcolor="#1e1e1e",bordercolor="#393939",borderwidth=1),
    )

def render_ai_result(resp: AIResponse, header: str):
    if resp.success:
        st.markdown(f"""
        <div class="carbon-card">
            <div class="mono-label">{header}</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(resp.content)
        st.markdown(f'<span class="ibm-tag ibm-tag-gray">{resp.model}</span> '
                    f'<span class="ibm-tag ibm-tag-gray">${resp.cost_usd:.6f}</span> '
                    f'<span class="ibm-tag ibm-tag-gray">{resp.duration_ms}ms</span>',
                    unsafe_allow_html=True)
    else:
        st.error(f"AI Error: {resp.error}")

def section_header(title, subtitle=""):
    st.markdown(f"<h1>{title}</h1>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f"<p style='color:#a8a8a8;font-size:0.9rem;margin-top:-0.5rem;font-family:IBM Plex Mono,monospace'>{subtitle}</p>", unsafe_allow_html=True)

def df_to_csv(df): return df.to_csv(index=False).encode("utf-8")

def ai_gate(label: str = "AI FEATURES") -> bool:
    """
    Render inline API-key setup when AI is not yet configured.
    Returns True  → AI ready, caller may render AI buttons.
    Returns False → setup panel shown, caller should skip AI buttons.
    """
    cfg = get_ai_config()
    if cfg and cfg.get("api_key"):
        return True

    st.markdown(f"""
    <div style="background:#1a1a00;border:1px solid #f1c21b;border-left:4px solid #f1c21b;
                padding:1.25rem 1.5rem;margin:1rem 0">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;letter-spacing:0.1em;
                    color:#f1c21b;margin-bottom:0.5rem">
            ⚡ {label} — API KEY REQUIRED
        </div>
        <div style="font-family:'IBM Plex Sans',sans-serif;font-size:0.875rem;color:#c6c6c6;margin-bottom:0.25rem">
            Enter your DeepSeek API key to unlock all AI features.
            Get a free key at
            <a href="https://platform.deepseek.com" target="_blank" style="color:#78a9ff">
            platform.deepseek.com</a> → API Keys → Create.
        </div>
    </div>
    """, unsafe_allow_html=True)

    form_key = "ai_gate_" + label.replace(" ", "_").replace("/", "_")
    with st.form(form_key):
        c1, c2 = st.columns([4, 1])
        quick_key = c1.text_input(
            "API Key", type="password",
            placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            label_visibility="collapsed",
        )
        submitted = c2.form_submit_button("ACTIVATE", use_container_width=True)
        if submitted:
            if not quick_key.strip():
                st.error("Paste your API key above.")
            elif not quick_key.strip().startswith("sk-"):
                st.error("Key must start with sk-")
            else:
                with st.spinner("Testing connection..."):
                    ok, msg = test_api_key(quick_key.strip(), DEEPSEEK_URL)
                if ok:
                    save_ai_config("deepseek", quick_key.strip(), "deepseek-chat",
                                   DEEPSEEK_URL, MONTHLY_BUDGET,
                                   ["therapy","simulator","insights","retro","risk","forecast"])
                    st.success("✅  AI activated — features unlocked.")
                    st.rerun()
                else:
                    st.error(f"Connection failed: {msg}")
    return False

def select_project():
    projects = get_projects()
    if not projects: return None, None
    names = [p["name"] for p in projects]
    key = "global_project_select"
    if key not in st.session_state: st.session_state[key] = names[0]
    sel = st.sidebar.selectbox("▸ Active Project", names, key=key)
    return next(p for p in projects if p["name"]==sel), projects

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
def page_dashboard(project, projects):
    pid = project["id"]
    team = get_team(pid)
    sprints = get_sprints(pid)
    risks = get_risks(pid)
    budget_entries = get_budget_entries(pid)
    monthly_cost = get_monthly_cost()
    cfg = get_ai_config()
    budget = cfg["monthly_budget"] if cfg else MONTHLY_BUDGET

    avg_morale   = sum(m["morale"]   for m in team)/len(team) if team else 0
    avg_workload = sum(m["workload"] for m in team)/len(team) if team else 0
    completed_sprints = [s for s in sprints if s["status"]=="completed"]
    avg_velocity = sum(s["completed_points"] for s in completed_sprints)/len(completed_sprints) if completed_sprints else 0
    open_risks   = len([r for r in risks if r["status"]=="open"])
    total_expense = sum(e["amount"] for e in budget_entries if e["entry_type"]=="expense")
    budget_pct    = total_expense/project["budget"]*100 if project["budget"] else 0

    # Header
    section_header("COMMAND CENTER", f"{project['name']}  ·  {project['status'].upper()}")
    st.markdown(
        status_tag(project["status"]) + "  " + priority_tag(project.get("priority","medium")),
        unsafe_allow_html=True
    )
    st.markdown("")

    # KPI row
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("VELOCITY", f"{avg_velocity:.0f} pts", f"Sprint avg")
    c2.metric("MORALE", f"{avg_morale:.0f}/100", f"{'↑ Good' if avg_morale>70 else '↓ At risk'}")
    c3.metric("WORKLOAD", f"{avg_workload:.0f}%", f"{'↑ Overloaded' if avg_workload>85 else 'Nominal'}", delta_color="inverse" if avg_workload>85 else "normal")
    c4.metric("OPEN RISKS", str(open_risks), f"{'⚠ Needs attention' if open_risks>3 else 'Managed'}", delta_color="inverse" if open_risks>3 else "off")
    c5.metric("BUDGET USED", f"{budget_pct:.0f}%", f"${total_expense:,.0f} of ${project['budget']:,.0f}")
    c6.metric("AI SPEND MTD", f"${monthly_cost:.4f}", f"${budget-monthly_cost:.2f} left")

    st.markdown("---")

    # ── Charts row 1 ──────────────────────────────────────────
    col_l, col_r = st.columns([3,2])

    with col_l:
        if sprints:
            df_vel = pd.DataFrame([{
                "Sprint": f"S{s['number']}",
                "Planned": s["planned_points"],
                "Completed": s["completed_points"],
                "Status": s["status"]
            } for s in sprints])
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Planned", x=df_vel["Sprint"], y=df_vel["Planned"],
                                 marker_color="#393939", marker_line_color="#525252", marker_line_width=1))
            fig.add_trace(go.Bar(name="Completed", x=df_vel["Sprint"], y=df_vel["Completed"],
                                 marker_color="#0f62fe"))
            # Velocity trend line
            if len(completed_sprints) > 1:
                comp_data = df_vel[df_vel["Status"]=="completed"]
                fig.add_trace(go.Scatter(name="Velocity trend", x=comp_data["Sprint"], y=comp_data["Completed"],
                                         mode="lines+markers", line=dict(color="#42be65",width=2,dash="dot"),
                                         marker=dict(size=6,color="#42be65")))
            fig.update_layout(title="SPRINT VELOCITY", barmode="overlay", **plotly_theme())
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No sprint data.")

    with col_r:
        # Risk matrix heatmap
        if risks:
            z = [[0]*5 for _ in range(5)]
            for r in risks:
                if r["status"]!="closed":
                    p,i = min(r["probability"],5)-1, min(r["impact"],5)-1
                    z[p][i] += 1
            colorscale = [[0,"#1e1e1e"],[0.01,"#262626"],[0.3,"#f1c21b"],[0.6,"#ff832b"],[1.0,"#da1e28"]]
            fig2 = go.Figure(go.Heatmap(
                z=z, x=["1-Negligible","2-Minor","3-Moderate","4-Major","5-Catastrophic"],
                y=["1-Rare","2-Unlikely","3-Possible","4-Likely","5-Almost Certain"],
                colorscale=colorscale, showscale=False,
                text=[[str(v) if v>0 else "" for v in row] for row in z],
                texttemplate="%{text}", textfont=dict(size=14,color="white",family="IBM Plex Mono")
            ))
            fig2.update_layout(title="RISK MATRIX", **plotly_theme())
            fig2.update_xaxes(tickfont=dict(size=9))
            fig2.update_yaxes(tickfont=dict(size=9))
            st.plotly_chart(fig2, use_container_width=True)

    # ── Charts row 2 ──────────────────────────────────────────
    col_a, col_b = st.columns(2)

    with col_a:
        # Budget burn-down
        if budget_entries:
            df_b = pd.DataFrame(budget_entries)
            df_b["entry_date"] = pd.to_datetime(df_b["entry_date"])
            df_b = df_b.sort_values("entry_date")
            df_b["cumulative"] = df_b.apply(
                lambda x: x["amount"] if x["entry_type"]=="expense" else -x["amount"], axis=1
            ).cumsum()
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(
                x=df_b["entry_date"], y=df_b["cumulative"],
                fill="tozeroy", fillcolor="rgba(15,98,254,0.15)",
                line=dict(color="#0f62fe",width=2), name="Spend"
            ))
            fig3.add_hline(y=project["budget"], line_color="#da1e28", line_dash="dash",
                           annotation_text="BUDGET LIMIT", annotation_font_color="#da1e28",
                           annotation_font_family="IBM Plex Mono", annotation_font_size=10)
            fig3.update_layout(title="BUDGET BURN", showlegend=False, **plotly_theme())
            st.plotly_chart(fig3, use_container_width=True)

    with col_b:
        # Team workload radar
        if team:
            fig4 = go.Figure()
            names = [m["name"].split()[0] for m in team]
            workloads = [m["workload"] for m in team]
            morales = [m["morale"] for m in team]
            fig4.add_trace(go.Bar(name="Workload", x=names, y=workloads,
                                  marker_color="#ff832b", marker_line_width=0))
            fig4.add_trace(go.Bar(name="Morale", x=names, y=morales,
                                  marker_color="#42be65", marker_line_width=0))
            fig4.add_hline(y=85, line_color="#da1e28", line_dash="dash",
                           annotation_text="OVERLOAD", annotation_font_color="#da1e28",
                           annotation_font_size=9, annotation_font_family="IBM Plex Mono")
            fig4.update_layout(title="TEAM HEALTH", barmode="group", **plotly_theme())
            st.plotly_chart(fig4, use_container_width=True)

    # ── AI Quick Actions ──────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="mono-label">AI ANALYSIS</div>', unsafe_allow_html=True)

    p_ctx = {k: project[k] for k in ("name","status","team_size","velocity","budget")}

    if ai_gate("DASHBOARD AI ANALYSIS"):
        b1,b2,b3 = st.columns(3)
        run_health = b1.button("HEALTH ANALYSIS",   use_container_width=True)
        run_sim    = b2.button("SCENARIO FORECAST", use_container_width=True)
        run_risk   = b3.button("RISK ANALYSIS",     use_container_width=True)

        if run_health:
            with st.spinner("Analysing..."):
                ts = {"avg_morale":avg_morale,"avg_workload":avg_workload,"count":len(team)}
                prompt = (f"Analyse health of '{project['name']}'. Morale:{avg_morale:.1f}/100, "
                          f"Workload:{avg_workload:.1f}%, Team:{len(team)}, Open risks:{open_risks}, "
                          f"Budget used:{budget_pct:.0f}%.\n"
                          "Give: 1) Health score 1-10 with rationale  2) Top 3 concerns ranked  3) Immediate action")
                resp = call_ai(prompt,"therapy",{"project":p_ctx,"team":ts})
            render_ai_result(resp,"HEALTH ANALYSIS")

        if run_sim:
            remaining_pts = project.get("total_points",0) - project.get("completed_points",0)
            with st.spinner("Simulating..."):
                prompt = (f"Forecast delivery for '{project['name']}'. Avg velocity:{avg_velocity:.1f} pts/sprint, "
                          f"Remaining:{remaining_pts} points, Team:{len(team)}, Budget remaining:${project['budget']-total_expense:,.0f}.\n"
                          "Give: 1) Expected delivery date range  2) Probability of on-time delivery  3) Top schedule risk")
                resp = call_ai(prompt,"forecast",p_ctx)
            render_ai_result(resp,"DELIVERY FORECAST")

        if run_risk:
            risk_summary = [{"title":r["title"],"score":r["probability"]*r["impact"],"status":r["status"]} for r in risks]
            with st.spinner("Analysing risks..."):
                prompt = (f"Analyse risks for '{project['name']}'. Current risks:\n"
                          + "\n".join(f"- {r['title']} (score:{r['score']}, {r['status']})" for r in risk_summary)
                          + "\nGive: 1) Critical risks to address now  2) Emerging patterns  3) Recommended mitigations")
                resp = call_ai(prompt,"risk",{"risks":risk_summary,"project":p_ctx})
            render_ai_result(resp,"RISK ANALYSIS")


# ═════════════════════════════════════════════════════════════════════════════
# PAGE: SPRINT BOARD
# ═════════════════════════════════════════════════════════════════════════════
def page_sprints(project, projects):
    pid = project["id"]
    sprints = get_sprints(pid)
    section_header("SPRINT BOARD", f"{project['name']}")

    tabs = st.tabs(["OVERVIEW","PLANNING","RETROSPECTIVE","AI FORECAST"])

    # ── Overview tab ───────────────────────────────────────────
    with tabs[0]:
        if not sprints:
            st.info("No sprints. Create one in PLANNING.")
        else:
            # Status swimlanes
            status_groups = {"completed":[],"active":[],"planned":[]}
            for s in sprints:
                status_groups.get(s["status"],[]).append(s)

            for status, label in [("completed","✓ COMPLETED"),("active","► ACTIVE"),("planned","◇ PLANNED")]:
                group = status_groups[status]
                if not group: continue
                st.markdown(f'<div class="mono-label" style="margin-top:1rem">{label}</div>', unsafe_allow_html=True)
                cols = st.columns(min(len(group),3))
                for i,s in enumerate(group):
                    with cols[i%3]:
                        pct = s["completion_pct"]
                        border_color = "#24a148" if status=="completed" else "#0f62fe" if status=="active" else "#525252"
                        st.markdown(f"""
                        <div style="background:#262626;border:1px solid #393939;border-top:3px solid {border_color};padding:1rem;margin-bottom:0.5rem">
                            <div class="mono-label">SPRINT {s['number']}</div>
                            <div style="font-size:0.9rem;color:#f4f4f4;margin:4px 0">{s.get('goal','—')}</div>
                            <div style="margin:8px 0">
                                <div style="background:#393939;height:4px">
                                    <div style="background:{border_color};height:4px;width:{pct}%"></div>
                                </div>
                            </div>
                            <span style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;color:#a8a8a8">
                                {s['completed_points']}/{s['planned_points']} pts · {pct:.0f}%
                            </span>
                        </div>
                        """, unsafe_allow_html=True)

            # Velocity chart
            st.markdown("---")
            df_v = pd.DataFrame([{"S":f"S{s['number']}","Planned":s["planned_points"],"Completed":s["completed_points"]} for s in sprints])
            fig = px.bar(df_v, x="S", y=["Planned","Completed"], barmode="overlay",
                         color_discrete_map={"Planned":"#393939","Completed":"#0f62fe"},
                         title="VELOCITY HISTORY")
            fig.update_layout(**plotly_theme())
            st.plotly_chart(fig, use_container_width=True)

            # Export
            csv = df_to_csv(pd.DataFrame([{k:v for k,v in s.items() if k not in ("blockers","retro_notes")} for s in sprints]))
            st.download_button("↓ EXPORT SPRINTS CSV", csv, "sprints.csv", "text/csv")

    # ── Planning tab ───────────────────────────────────────────
    with tabs[1]:
        st.markdown('<div class="mono-label">CREATE SPRINT</div>', unsafe_allow_html=True)
        next_num = (max(s["number"] for s in sprints)+1) if sprints else 1
        with st.form("sprint_form"):
            c1,c2 = st.columns(2)
            goal = st.text_input("Sprint Goal *", placeholder="e.g. Complete checkout flow integration")
            c1,c2,c3 = st.columns(3)
            start = c1.date_input("Start Date", value=date.today())
            end   = c2.date_input("End Date",   value=date.today()+timedelta(days=13))
            pts   = c3.number_input("Planned Points", 1, 500, 45)
            status = st.selectbox("Status", ["planned","active","completed"])
            if st.form_submit_button(f"CREATE SPRINT {next_num}"):
                if not goal.strip():
                    st.error("Sprint goal required.")
                else:
                    db_exec("INSERT INTO sprints (id,project_id,number,goal,start_date,end_date,planned_points,status) VALUES (?,?,?,?,?,?,?,?)",
                            (str(uuid.uuid4()),pid,next_num,goal.strip(),str(start),str(end),pts,status))
                    log_event(pid,"sprint_created",f"Sprint {next_num}: {goal}")
                    st.success(f"Sprint {next_num} created!"); st.rerun()

        if sprints:
            st.markdown("---")
            st.markdown('<div class="mono-label">UPDATE SPRINT</div>', unsafe_allow_html=True)
            sprint_names = [f"Sprint {s['number']}: {s.get('goal','')[:40]}" for s in sprints]
            sel_idx = st.selectbox("Select sprint to update", range(len(sprint_names)),
                                   format_func=lambda i: sprint_names[i])
            sel_sprint = sprints[sel_idx]
            with st.form("update_sprint_form"):
                c1,c2 = st.columns(2)
                new_completed = c1.number_input("Completed Points", 0, 500, sel_sprint["completed_points"])
                new_status = c2.selectbox("Status", ["planned","active","completed"],
                                          index=["planned","active","completed"].index(sel_sprint["status"]))
                new_blockers_raw = st.text_area("Blockers (one per line)", "\n".join(sel_sprint["blockers"]))
                if st.form_submit_button("UPDATE SPRINT"):
                    new_blockers = [b.strip() for b in new_blockers_raw.split("\n") if b.strip()]
                    db_exec("UPDATE sprints SET completed_points=?,status=?,blockers=? WHERE id=?",
                            (new_completed,new_status,json.dumps(new_blockers),sel_sprint["id"]))
                    log_event(pid,"sprint_updated",f"Sprint {sel_sprint['number']}: {new_completed}pts, {new_status}")
                    st.success("Sprint updated!"); st.rerun()

    # ── Retrospective tab ──────────────────────────────────────
    with tabs[2]:
        completed = [s for s in sprints if s["status"]=="completed"]
        if not completed:
            st.info("No completed sprints yet.")
        else:
            sel_retro = st.selectbox("Select sprint for retrospective",
                                     [f"Sprint {s['number']}: {s.get('goal','')}" for s in completed])
            sel_idx = int(sel_retro.split(":")[0].replace("Sprint","").strip())-1
            sprint = next((s for s in completed if s["number"]==sel_idx+1), completed[0])
            existing = sprint.get("retro_notes",{})

            with st.form("retro_form"):
                went_well  = st.text_area("✓ WENT WELL",    value=existing.get("went_well",""),  height=100)
                improve    = st.text_area("△ TO IMPROVE",   value=existing.get("improve",""),    height=100)
                action     = st.text_area("▶ ACTION ITEMS", value=existing.get("actions",""),    height=100)
                if st.form_submit_button("SAVE RETROSPECTIVE"):
                    notes = {"went_well":went_well,"improve":improve,"actions":action}
                    db_exec("UPDATE sprints SET retro_notes=? WHERE id=?", (json.dumps(notes),sprint["id"]))
                    st.success("Retrospective saved!"); st.rerun()

            st.markdown("---")
            if ai_gate("SPRINT RETROSPECTIVE AI"):
                if st.button("AI RETROSPECTIVE SUMMARY"):
                    with st.spinner("Generating..."):
                        prompt = (f"Summarise retrospective for Sprint {sprint['number']} of '{project['name']}'.\n"
                                  f"Velocity: {sprint['completed_points']}/{sprint['planned_points']} pts.\n"
                                  f"Went well: {existing.get('went_well','none')}\n"
                                  f"To improve: {existing.get('improve','none')}\n"
                                  f"Actions: {existing.get('actions','none')}\n"
                                  "Generate: executive summary, key patterns, prioritised action recommendations.")
                        resp = call_ai(prompt,"retro",{"sprint":sprint["number"],"project":project["name"]})
                    render_ai_result(resp,"AI RETROSPECTIVE SUMMARY")

    # ── AI Forecast tab ────────────────────────────────────────
    with tabs[3]:
        if not ai_gate("SPRINT AI FORECAST"):
            pass
        else:
            completed_sprints_fc = [s for s in sprints if s["status"]=="completed"]
            remaining = project.get("total_points",0)-project.get("completed_points",0)
            velocities = [s["completed_points"] for s in completed_sprints_fc] if completed_sprints_fc else [30]
            avg_v = sum(velocities)/len(velocities) if velocities else 30
            sprints_left = math.ceil(remaining/avg_v) if avg_v else "unknown"

            col1,col2,col3 = st.columns(3)
            col1.metric("REMAINING POINTS", f"{remaining}")
            col2.metric("AVG VELOCITY", f"{avg_v:.1f} pts")
            col3.metric("EST. SPRINTS LEFT", str(sprints_left))

            scenario = st.selectbox("Scenario", ["Current pace","Add 1 senior dev","Reduce scope 20%","Add 1 dev + reduce scope 10%"])
            if st.button("GENERATE FORECAST"):
                with st.spinner("Forecasting..."):
                    prompt = (f"Sprint delivery forecast for '{project['name']}'.\n"
                              f"Remaining: {remaining} points. Avg velocity: {avg_v:.1f} pts/sprint.\n"
                              f"Past velocities: {velocities}\nScenario: {scenario}\n"
                              f"Sprint length: 2 weeks. Budget remaining: ${project['budget']-sum(e['amount'] for e in get_budget_entries(pid) if e['entry_type']=='expense'):,.0f}\n"
                              "Give: 1) Delivery date range with 80% confidence interval  "
                              "2) Probability of meeting original deadline  "
                              "3) Recommended sprint capacity for next sprint  "
                              "4) Risk factors affecting forecast")
                    resp = call_ai(prompt,"forecast")
                render_ai_result(resp,f"DELIVERY FORECAST — {scenario.upper()}")


# ═════════════════════════════════════════════════════════════════════════════
# PAGE: RISK REGISTER
# ═════════════════════════════════════════════════════════════════════════════
def page_risks(project, projects):
    pid = project["id"]
    risks = get_risks(pid)
    section_header("RISK REGISTER", f"{project['name']}")

    # Summary bar
    open_r    = [r for r in risks if r["status"]=="open"]
    mitig_r   = [r for r in risks if r["status"]=="mitigated"]
    closed_r  = [r for r in risks if r["status"]=="closed"]
    critical_r = [r for r in open_r if r["probability"]*r["impact"]>=12]

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("TOTAL RISKS", len(risks))
    c2.metric("OPEN", len(open_r), delta=f"{len(critical_r)} critical", delta_color="inverse" if critical_r else "off")
    c3.metric("MITIGATED", len(mitig_r))
    c4.metric("CLOSED", len(closed_r))

    tabs = st.tabs(["REGISTER","MATRIX","ADD RISK","AI ANALYSIS"])

    # ── Register tab ───────────────────────────────────────────
    with tabs[0]:
        filter_status = st.multiselect("Filter by status", ["open","mitigated","closed"], default=["open","mitigated"])
        filter_risks = [r for r in risks if r["status"] in filter_status] if filter_status else risks

        for r in filter_risks:
            score = r["probability"]*r["impact"]
            border = "#da1e28" if score>=12 else "#ff832b" if score>=8 else "#f1c21b" if score>=4 else "#393939"
            st.markdown(f"""
            <div style="background:#262626;border:1px solid #393939;border-left:4px solid {border};padding:1rem;margin-bottom:0.75rem">
                <div style="display:flex;justify-content:space-between;align-items:flex-start">
                    <div>
                        <span style="font-family:'IBM Plex Mono',monospace;font-weight:600;color:#f4f4f4">{r['title']}</span>
                        <span style="margin-left:12px">{risk_score_tag(r['probability'],r['impact'])}</span>
                        {tag(r['category'].upper(),'blue')}
                        {tag(r['status'].upper(),'green' if r['status']=='closed' else 'yellow' if r['status']=='mitigated' else 'red')}
                    </div>
                    <span style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;color:#a8a8a8">Owner: {r.get('owner','—')}</span>
                </div>
                <p style="color:#a8a8a8;font-size:0.85rem;margin:0.5rem 0">{r.get('description','')}</p>
                <div style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;color:#42be65">
                    ▶ Mitigation: {r.get('mitigation','—')}
                </div>
            </div>
            """, unsafe_allow_html=True)

        if risks:
            df_r = pd.DataFrame([{
                "Title":r["title"],"Category":r["category"],
                "Probability":r["probability"],"Impact":r["impact"],
                "Score":r["probability"]*r["impact"],"Status":r["status"],
                "Owner":r.get("owner",""),"Mitigation":r.get("mitigation","")
            } for r in risks])
            csv = df_to_csv(df_r)
            st.download_button("↓ EXPORT RISK REGISTER CSV", csv, "risks.csv", "text/csv")

    # ── Matrix tab ─────────────────────────────────────────────
    with tabs[1]:
        st.markdown('<div class="mono-label">RISK PROBABILITY × IMPACT MATRIX</div>', unsafe_allow_html=True)
        impact_labels  = ["1\nNegligible","2\nMinor","3\nModerate","4\nMajor","5\nCatastrophic"]
        prob_labels    = ["5\nAlmost Certain","4\nLikely","3\nPossible","2\nUnlikely","1\nRare"]
        grid = {(p,i):[] for p in range(1,6) for i in range(1,6)}
        for r in risks:
            if r["status"]!="closed":
                grid[(r["probability"],r["impact"])].append(r["title"][:20])
        rows_html = ""
        for prob in range(5,0,-1):
            row = f'<tr><td style="font-family:IBM Plex Mono,monospace;font-size:0.7rem;color:#a8a8a8;padding:4px 8px">{prob}</td>'
            for impact in range(1,6):
                score = prob*impact
                bg = "#2d0a0e" if score>=12 else "#231000" if score>=8 else "#1c1500" if score>=4 else "#1e1e1e"
                border = "#da1e28" if score>=12 else "#ff832b" if score>=8 else "#f1c21b" if score>=4 else "#393939"
                items = grid.get((prob,impact),[])
                content = "<br>".join(f'<span style="color:#f4f4f4;font-size:0.7rem">{t}</span>' for t in items) if items else ""
                row += f'<td style="background:{bg};border:1px solid {border};padding:8px;min-width:100px;vertical-align:top;font-family:IBM Plex Mono,monospace">{content}&nbsp;</td>'
            rows_html += row + "</tr>"
        header = '<tr><th style="font-family:IBM Plex Mono,monospace;font-size:0.7rem;color:#a8a8a8;padding:4px">P / I</th>' + "".join(f'<th style="font-family:IBM Plex Mono,monospace;font-size:0.7rem;color:#a8a8a8;padding:4px 8px">{l}</th>' for l in impact_labels) + "</tr>"
        st.markdown(f'<table style="border-collapse:collapse;width:100%"><thead>{header}</thead><tbody>{rows_html}</tbody></table>', unsafe_allow_html=True)

    # ── Add Risk tab ───────────────────────────────────────────
    with tabs[2]:
        team = get_team(pid)
        team_names = [m["name"] for m in team] + ["External"]
        with st.form("add_risk_form"):
            title = st.text_input("Risk Title *")
            desc  = st.text_area("Description")
            c1,c2,c3 = st.columns(3)
            cat    = c1.selectbox("Category", ["technical","people","financial","compliance","delivery","external"])
            prob   = c2.slider("Probability (1-5)", 1, 5, 2)
            impact = c3.slider("Impact (1-5)", 1, 5, 2)
            c4,c5 = st.columns(2)
            owner  = c4.selectbox("Risk Owner", team_names)
            status = c5.selectbox("Status", ["open","mitigated","closed"])
            mitigation = st.text_area("Mitigation Plan")
            score = prob*impact
            st.markdown(f"Risk Score: {risk_score_tag(prob,impact)}", unsafe_allow_html=True)
            if st.form_submit_button("ADD RISK"):
                if not title.strip():
                    st.error("Title required.")
                else:
                    db_exec("INSERT INTO risks (id,project_id,title,description,category,probability,impact,status,owner,mitigation) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (str(uuid.uuid4()),pid,title.strip(),desc,cat,prob,impact,status,owner,mitigation))
                    log_event(pid,"risk_added",f"{title} (score:{score})")
                    st.success("Risk added!"); st.rerun()

    # ── AI Analysis tab ────────────────────────────────────────
    with tabs[3]:
        if ai_gate("RISK AI ANALYSIS"):
            if st.button("GENERATE AI RISK ANALYSIS"):
                risk_data = [{"title":r["title"],"score":r["probability"]*r["impact"],"category":r["category"],"status":r["status"]} for r in risks]
                with st.spinner("Analysing..."):
                    prompt = (f"Comprehensive risk analysis for '{project['name']}'.\n"
                              f"Open risks: {len(open_r)}, Critical (score≥12): {len(critical_r)}\n"
                              "Risks:\n" + "\n".join(f"- {r['title']} | {r['category']} | score:{r['score']} | {r['status']}" for r in risk_data)
                              + "\nProvide: 1) Top 3 immediate risks requiring action  "
                              "2) Risk pattern analysis  3) Specific mitigations for highest risks  "
                              "4) Risk forecast for next sprint")
                    resp = call_ai(prompt,"risk",{"project":project["name"],"risks":risk_data})
                render_ai_result(resp,"AI RISK ANALYSIS")


# ═════════════════════════════════════════════════════════════════════════════
# PAGE: BUDGET
# ═════════════════════════════════════════════════════════════════════════════
def page_budget(project, projects):
    pid = project["id"]
    entries = get_budget_entries(pid)
    section_header("BUDGET TRACKER", f"{project['name']}")

    expenses = [e for e in entries if e["entry_type"]=="expense"]
    income   = [e for e in entries if e["entry_type"]=="income"]
    total_expense = sum(e["amount"] for e in expenses)
    total_income  = sum(e["amount"] for e in income)
    budget = project["budget"]
    remaining = budget - total_expense + total_income
    budget_pct = total_expense/budget*100 if budget else 0

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("TOTAL BUDGET",  f"${budget:,.0f}")
    c2.metric("TOTAL SPEND",   f"${total_expense:,.0f}", f"{budget_pct:.1f}% used", delta_color="inverse" if budget_pct>90 else "off")
    c3.metric("INCOME",        f"${total_income:,.0f}")
    c4.metric("NET REMAINING", f"${remaining:,.0f}", delta_color="inverse" if remaining<0 else "normal")

    pct_clamped = min(100,budget_pct)
    bar_color = "#da1e28" if budget_pct>90 else "#ff832b" if budget_pct>75 else "#0f62fe"
    st.markdown(f"""
    <div style="margin:1rem 0">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.72rem;color:#a8a8a8;margin-bottom:4px">BUDGET UTILISATION — {budget_pct:.1f}%</div>
        <div style="background:#393939;height:8px">
            <div style="background:{bar_color};height:8px;width:{pct_clamped}%;transition:width 0.5s"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    tabs = st.tabs(["BURN-DOWN","BREAKDOWN","LOG ENTRY","EXPORT"])

    with tabs[0]:
        if entries:
            df_b = pd.DataFrame(entries)
            df_b["entry_date"] = pd.to_datetime(df_b["entry_date"])
            df_b = df_b.sort_values("entry_date")
            df_b["signed"] = df_b.apply(lambda x: x["amount"] if x["entry_type"]=="expense" else -x["amount"],axis=1)
            df_b["cumulative"] = df_b["signed"].cumsum()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_b["entry_date"],y=df_b["cumulative"],
                                     fill="tozeroy",fillcolor="rgba(15,98,254,0.12)",
                                     line=dict(color="#0f62fe",width=2.5),name="Cumulative spend",
                                     hovertemplate="<b>%{x|%b %d}</b><br>$%{y:,.0f}<extra></extra>"))
            fig.add_hline(y=budget,line_color="#da1e28",line_dash="dash",
                          annotation_text="BUDGET LIMIT",annotation_font_color="#da1e28",
                          annotation_font_size=9,annotation_font_family="IBM Plex Mono")
            fig.update_layout(title="CUMULATIVE SPEND vs BUDGET",**plotly_theme())
            st.plotly_chart(fig,use_container_width=True)

    with tabs[1]:
        if expenses:
            by_cat = {}
            for e in expenses:
                by_cat[e["category"]] = by_cat.get(e["category"],0)+e["amount"]
            df_cat = pd.DataFrame(list(by_cat.items()),columns=["Category","Amount"])
            col1,col2 = st.columns(2)
            with col1:
                fig2 = go.Figure(go.Pie(
                    labels=df_cat["Category"],values=df_cat["Amount"],
                    hole=0.5,
                    marker_colors=["#0f62fe","#42be65","#ff832b","#da1e28","#f1c21b","#8a3ffc"],
                    textfont=dict(family="IBM Plex Mono",size=10),
                    hovertemplate="<b>%{label}</b><br>$%{value:,.0f}<br>%{percent}<extra></extra>"
                ))
                fig2.update_layout(title="SPEND BY CATEGORY",**plotly_theme(),showlegend=True)
                st.plotly_chart(fig2,use_container_width=True)
            with col2:
                df_cat["Amount"] = df_cat["Amount"].apply(lambda x: f"${x:,.0f}")
                df_cat["%"] = [(by_cat[r]/total_expense*100) if total_expense else 0 for r in by_cat]
                df_cat["%"] = df_cat["%"].apply(lambda x: f"{x:.1f}%")
                st.dataframe(df_cat,use_container_width=True,hide_index=True)

    with tabs[2]:
        with st.form("budget_entry_form"):
            desc = st.text_input("Description *")
            c1,c2,c3 = st.columns(3)
            amount = c1.number_input("Amount ($)", 0.01, 10_000_000.0, 1000.0)
            etype  = c2.selectbox("Type", ["expense","income"])
            cat    = c3.selectbox("Category", ["infrastructure","people","tools","compliance","marketing","revenue","other"])
            edate  = st.date_input("Date", value=date.today())
            if st.form_submit_button("LOG ENTRY"):
                if not desc.strip():
                    st.error("Description required.")
                else:
                    db_exec("INSERT INTO budget_entries (id,project_id,description,amount,entry_type,category,entry_date) VALUES (?,?,?,?,?,?,?)",
                            (str(uuid.uuid4()),pid,desc.strip(),amount,etype,cat,str(edate)))
                    log_event(pid,"budget_entry",f"{etype}: ${amount:,.0f} — {desc}")
                    st.success("Entry logged!"); st.rerun()

    with tabs[3]:
        if entries:
            df_exp = pd.DataFrame(entries)[["description","amount","entry_type","category","entry_date"]]
            st.dataframe(df_exp,use_container_width=True,hide_index=True)
            csv = df_to_csv(df_exp)
            st.download_button("↓ EXPORT BUDGET CSV", csv, "budget.csv", "text/csv")


# ═════════════════════════════════════════════════════════════════════════════
# PAGE: TEAM
# ═════════════════════════════════════════════════════════════════════════════
def page_team(project, projects):
    pid = project["id"]
    team = get_team(pid)
    section_header("TEAM MANAGEMENT", f"{project['name']}")

    if team:
        avg_morale   = sum(m["morale"]   for m in team)/len(team)
        avg_workload = sum(m["workload"] for m in team)/len(team)
        overloaded   = sum(1 for m in team if m["workload"]>85)
        low_morale_n = sum(1 for m in team if m["morale"]<60)
        total_daily  = sum(m.get("daily_rate",0) for m in team)

        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("HEADCOUNT",    len(team))
        c2.metric("AVG MORALE",   f"{avg_morale:.0f}/100", f"{'↑ Good' if avg_morale>70 else '↓ Risk'}")
        c3.metric("AVG WORKLOAD", f"{avg_workload:.0f}%",  delta_color="inverse" if avg_workload>85 else "normal")
        c4.metric("AT RISK",      overloaded+low_morale_n, f"{overloaded} overloaded · {low_morale_n} morale")
        c5.metric("DAILY COST",   f"${total_daily:,.0f}")

        tabs = st.tabs(["ROSTER","WORKLOAD CHART","EDIT MEMBER","AI INSIGHTS"])

        with tabs[0]:
            for m in team:
                wc = "green" if m["workload"]<70 else "yellow" if m["workload"]<85 else "red"
                mc = "green" if m["morale"]>70  else "yellow" if m["morale"]>50  else "red"
                skills_html = " ".join(tag(s,"blue") for s in m["skills"][:5])
                st.markdown(f"""
                <div style="background:#262626;border:1px solid #393939;padding:1rem 1.25rem;margin-bottom:0.5rem;display:flex;justify-content:space-between;align-items:center">
                    <div style="flex:2">
                        <span style="font-family:'IBM Plex Mono',monospace;font-weight:600;color:#f4f4f4">{m['name']}</span>
                        <span style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;color:#a8a8a8;margin-left:12px">{m['role']}</span><br>
                        <span style="font-size:0.75rem;color:#a8a8a8">{m.get('email','')}</span>
                    </div>
                    <div style="flex:2;text-align:center">{skills_html}</div>
                    <div style="flex:1;text-align:center">
                        {tag(f"WL {m['workload']:.0f}%", wc)}
                        {tag(f"MO {m['morale']:.0f}", mc)}
                    </div>
                    <div style="font-family:'IBM Plex Mono',monospace;font-size:0.82rem;color:#a8a8a8;flex:1;text-align:right">
                        ${m.get('daily_rate',0):,.0f}/day
                    </div>
                </div>
                """, unsafe_allow_html=True)
            csv = df_to_csv(pd.DataFrame([{k:v for k,v in m.items() if k!="skills"} for m in team]))
            st.download_button("↓ EXPORT TEAM CSV", csv, "team.csv", "text/csv")

        with tabs[1]:
            df_t = pd.DataFrame([{"Name":m["name"].split()[0],"Workload":m["workload"],"Morale":m["morale"]} for m in team])
            fig = px.bar(df_t,x="Name",y=["Workload","Morale"],barmode="group",
                         color_discrete_map={"Workload":"#ff832b","Morale":"#42be65"},
                         title="TEAM WORKLOAD & MORALE")
            fig.add_hline(y=85,line_color="#da1e28",line_dash="dash",
                          annotation_text="OVERLOAD THRESHOLD",annotation_font_color="#da1e28",
                          annotation_font_size=9,annotation_font_family="IBM Plex Mono")
            fig.update_layout(**plotly_theme())
            st.plotly_chart(fig,use_container_width=True)

        with tabs[2]:
            sel_name = st.selectbox("Select member", [m["name"] for m in team])
            sel_m = next(m for m in team if m["name"]==sel_name)
            with st.form("edit_member_form"):
                c1,c2 = st.columns(2)
                new_role  = c1.text_input("Role",  value=sel_m["role"])
                new_email = c2.text_input("Email", value=sel_m.get("email",""))
                new_skills_raw = st.text_input("Skills (comma-separated)", value=", ".join(sel_m["skills"]))
                c3,c4,c5 = st.columns(3)
                new_wl   = c3.slider("Workload %", 0, 100, int(sel_m["workload"]))
                new_mo   = c4.slider("Morale",     0, 100, int(sel_m["morale"]))
                new_rate = c5.number_input("Daily Rate ($)", 0.0, 10000.0, float(sel_m.get("daily_rate",0)))
                col_save,col_del = st.columns(2)
                save = col_save.form_submit_button("SAVE CHANGES")
                delete = col_del.form_submit_button("DELETE MEMBER")
                if save:
                    new_skills = [s.strip() for s in new_skills_raw.split(",") if s.strip()]
                    db_exec("UPDATE team_members SET role=?,email=?,skills=?,workload=?,morale=?,daily_rate=? WHERE id=?",
                            (new_role,new_email,json.dumps(new_skills),new_wl,new_mo,new_rate,sel_m["id"]))
                    log_event(pid,"member_updated",f"{sel_name}: workload={new_wl}%, morale={new_mo}")
                    st.success("Member updated!"); st.rerun()
                if delete:
                    db_exec("DELETE FROM team_members WHERE id=?", (sel_m["id"],))
                    log_event(pid,"member_removed",sel_name)
                    st.warning(f"{sel_name} removed from team."); st.rerun()

        with tabs[3]:
            if ai_gate("TEAM AI INSIGHTS"):
                if st.button("AI TEAM HEALTH ANALYSIS"):
                    team_summary = [{"name":m["name"],"role":m["role"],"workload":m["workload"],"morale":m["morale"]} for m in team]
                    with st.spinner("Analysing team..."):
                        prompt = (f"Team health analysis for '{project['name']}'.\n"
                                  f"Avg morale: {avg_morale:.1f}, Avg workload: {avg_workload:.1f}%, "
                                  f"Overloaded: {overloaded}, Low morale: {low_morale_n}\n"
                                  "Team:\n" + "\n".join(f"- {m['name']} ({m['role']}): WL={m['workload']:.0f}% MO={m['morale']:.0f}" for m in team)
                                  + "\nGive: 1) Individual members at risk  2) Team dynamic concerns  "
                                  "3) Workload redistribution recommendation  4) Morale improvement actions")
                        resp = call_ai(prompt,"therapy",{"team":team_summary})
                    render_ai_result(resp,"TEAM HEALTH ANALYSIS")
    else:
        st.info("No team members. Add one below.")

    st.markdown("---")
    with st.expander("➕ ADD TEAM MEMBER"):
        with st.form("add_member_form"):
            c1,c2 = st.columns(2)
            name  = c1.text_input("Full Name *")
            role  = c2.text_input("Role")
            c3,c4 = st.columns(2)
            email = c3.text_input("Email")
            rate  = c4.number_input("Daily Rate ($)", 0.0, 10000.0, 600.0)
            skills_raw = st.text_input("Skills (comma-separated)", placeholder="Python, AWS, Docker")
            c5,c6 = st.columns(2)
            wl = c5.slider("Initial Workload %", 0, 100, 70)
            mo = c6.slider("Initial Morale",     0, 100, 80)
            if st.form_submit_button("ADD MEMBER"):
                if not name.strip():
                    st.error("Name required.")
                else:
                    skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
                    db_exec("INSERT INTO team_members (id,project_id,name,role,email,skills,workload,morale,daily_rate) VALUES (?,?,?,?,?,?,?,?,?)",
                            (str(uuid.uuid4()),pid,name.strip(),role,email,json.dumps(skills),wl,mo,rate))
                    log_event(pid,"member_added",name.strip())
                    st.success(f"{name} added!"); st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# PAGE: PROJECTS
# ═════════════════════════════════════════════════════════════════════════════
def page_projects(project, projects):
    section_header("PROJECTS","Portfolio overview")

    tabs = st.tabs(["PORTFOLIO","CREATE PROJECT","ACTIVITY LOG"])

    with tabs[0]:
        if not projects:
            st.info("No projects. Create one.")
        else:
            df = pd.DataFrame([{
                "Name":p["name"],"Status":p["status"].upper(),
                "Priority":p.get("priority","medium").upper(),
                "Team":p["team_size"],"Velocity":f"{p['velocity']:.1f}",
                "Budget":f"${p['budget']:,.0f}","Start":p.get("start_date","—"),"End":p.get("end_date","—")
            } for p in projects])
            st.dataframe(df,use_container_width=True,hide_index=True)

            if len(projects)>1:
                if ai_gate("PORTFOLIO AI ANALYSIS"):
                    if st.button("AI PORTFOLIO COMPARE"):
                        with st.spinner("Comparing projects..."):
                            plist = "\n".join(f"- {p['name']}: {p['status']}, vel={p['velocity']:.1f}, budget=${p['budget']:,.0f}" for p in projects[:4])
                            prompt = f"Compare this portfolio:\n{plist}\n\nGive: 1) Healthiest project  2) Most at-risk  3) Resource allocation recommendation  4) Portfolio-level risk"
                            resp = call_ai(prompt,"insights",{"projects":[{"name":p["name"],"status":p["status"]} for p in projects]})
                        render_ai_result(resp,"PORTFOLIO ANALYSIS")

    with tabs[1]:
        with st.form("create_project_form"):
            name = st.text_input("Project Name *")
            desc = st.text_area("Description")
            c1,c2,c3 = st.columns(3)
            status   = c1.selectbox("Status",   ["planning","active","on_hold","completed"])
            priority = c2.selectbox("Priority",  ["critical","high","medium","low"])
            c4,c5 = st.columns(2)
            start = c4.date_input("Start Date")
            end   = c5.date_input("End Date", value=date.today()+timedelta(days=90))
            c6,c7,c8 = st.columns(3)
            ts  = c6.number_input("Team Size", 1,200,4)
            vel = c7.number_input("Est. Velocity (pts)", 1.0,500.0,30.0)
            bg  = c8.number_input("Budget ($)", 0.0,100_000_000.0,50_000.0,step=5000.0)
            total_pts = st.number_input("Total Story Points (backlog)", 0, 10000, 0)
            if st.form_submit_button("CREATE PROJECT"):
                if not name.strip():
                    st.error("Name required.")
                else:
                    db_exec("INSERT INTO projects (id,name,description,status,priority,start_date,end_date,team_size,velocity,budget,total_points) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (str(uuid.uuid4()),name.strip(),desc,status,priority,str(start),str(end),ts,vel,bg,total_pts))
                    st.success(f"'{name}' created!"); st.rerun()

    with tabs[2]:
        history = get_project_history(project["id"])
        if history:
            for h in history:
                icon = {"sprint_created":"🏃","sprint_updated":"✏️","risk_added":"⚠️","member_added":"👤",
                        "member_removed":"👤","budget_entry":"💰","status_change":"🔄","project_created":"🆕"}.get(h["event_type"],"•")
                st.markdown(f"""
                <div style="display:flex;gap:12px;padding:8px 0;border-bottom:1px solid #2a2a2a">
                    <span style="font-size:1rem">{icon}</span>
                    <div>
                        <span style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;color:#f4f4f4">{h['event_type'].replace('_',' ').upper()}</span>
                        <span style="font-family:'IBM Plex Mono',monospace;font-size:0.75rem;color:#a8a8a8;margin-left:8px">{h.get('detail','')}</span><br>
                        <span style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;color:#525252">{h['created_at']}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No activity yet.")


# ═════════════════════════════════════════════════════════════════════════════
# PAGE: SETTINGS
# ═════════════════════════════════════════════════════════════════════════════
def page_settings(project, projects):
    section_header("SETTINGS","AI configuration & system")

    cfg = get_ai_config()
    monthly_cost = get_monthly_cost()
    budget = cfg["monthly_budget"] if cfg else MONTHLY_BUDGET
    budget_pct = min(100.0, monthly_cost/budget*100) if budget else 0

    tabs = st.tabs(["AI CONFIGURATION","USAGE ANALYTICS","DATA MANAGEMENT"])

    with tabs[0]:
        st.markdown('<div class="mono-label" style="margin-bottom:12px">API CREDENTIALS</div>', unsafe_allow_html=True)
        if not CRYPTO_AVAILABLE:
            st.warning("⚠  `cryptography` package not installed — keys stored unencrypted. Run: `pip install cryptography`")

        st.info("Get your API key at [platform.deepseek.com](https://platform.deepseek.com). Keys are Fernet-encrypted at rest.", icon="🔑")

        with st.form("ai_config_form"):
            c1,c2 = st.columns(2)
            provider = c1.selectbox("Provider", ["deepseek"])
            model    = c2.selectbox("Model", ["deepseek-chat","deepseek-coder"],
                                    index=0 if not cfg else ["deepseek-chat","deepseek-coder"].index(cfg.get("model","deepseek-chat")))
            base_url = st.text_input("Base URL", value=cfg.get("base_url",DEEPSEEK_URL) if cfg else DEEPSEEK_URL)
            has_key = bool(cfg and cfg.get("api_key"))
            api_key = st.text_input("API Key", type="password",
                                    placeholder=f"sk-... {'(key saved: '+mask_key(cfg['api_key'])+')' if has_key else '(not set)'}",
                                    autocomplete="off")

            st.markdown('<div class="mono-label" style="margin-top:12px">ENABLED FEATURES</div>', unsafe_allow_html=True)
            feat_opts = {"therapy":"Project Health Analysis","simulator":"What-If Simulator",
                         "insights":"Cross-Project Insights","retro":"Sprint Retrospective",
                         "risk":"Risk Analysis","forecast":"Delivery Forecast"}
            current = cfg["features"] if cfg else list(feat_opts.keys())
            fcols = st.columns(3)
            features = []
            for i,(k,v) in enumerate(feat_opts.items()):
                if fcols[i%3].checkbox(v, value=k in current, key=f"f_{k}"):
                    features.append(k)

            st.markdown('<div class="mono-label" style="margin-top:12px">BUDGET CONTROL</div>', unsafe_allow_html=True)
            new_budget = st.number_input("Monthly Budget (USD)", 1.0, 10000.0, float(budget), step=5.0)
            st.progress(budget_pct/100, text=f"${monthly_cost:.4f} of ${budget:.2f} used this month ({budget_pct:.1f}%)")

            if st.form_submit_button("SAVE CONFIGURATION"):
                key_to_save = api_key.strip() if api_key and api_key.strip() else (cfg["api_key"] if cfg else "")
                if not key_to_save:
                    st.error("API key required.")
                elif not features:
                    st.error("Enable at least one feature.")
                else:
                    save_ai_config(provider, key_to_save, model, base_url, new_budget, features)
                    st.success("✅  Configuration saved."); st.rerun()

        st.markdown("---")
        st.markdown('<div class="mono-label">TEST CONNECTION</div>', unsafe_allow_html=True)
        c1,c2 = st.columns([3,1])
        test_key = c1.text_input("Key to test", type="password", key="test_key")
        if c2.button("TEST", use_container_width=True):
            if not test_key:
                st.warning("Enter a key.")
            else:
                with st.spinner("Connecting..."):
                    ok,msg = test_api_key(test_key, cfg.get("base_url",DEEPSEEK_URL) if cfg else DEEPSEEK_URL)
                (st.success if ok else st.error)(msg)

    with tabs[1]:
        # Usage over time
        rows = db_rows("SELECT * FROM ai_usage_log ORDER BY created_at DESC LIMIT 100")
        if rows:
            df_u = pd.DataFrame(rows)
            df_u["created_at"] = pd.to_datetime(df_u["created_at"])

            col1,col2 = st.columns(2)
            with col1:
                by_feat = df_u[df_u["success"]==1].groupby("feature")["cost_usd"].sum().reset_index()
                fig = px.pie(by_feat, values="cost_usd", names="feature", title="COST BY FEATURE",
                             hole=0.5, color_discrete_sequence=["#0f62fe","#42be65","#ff832b","#f1c21b","#da1e28","#8a3ffc"])
                fig.update_layout(**plotly_theme())
                st.plotly_chart(fig,use_container_width=True)
            with col2:
                daily = df_u[df_u["success"]==1].groupby(df_u["created_at"].dt.date)["cost_usd"].sum().reset_index()
                fig2 = px.bar(daily,x="created_at",y="cost_usd",title="DAILY AI COST",
                              color_discrete_sequence=["#0f62fe"])
                fig2.update_layout(**plotly_theme(),xaxis_title="",yaxis_title="USD")
                st.plotly_chart(fig2,use_container_width=True)

            # Table
            df_display = df_u[["created_at","feature","model","prompt_tokens","completion_tokens","cost_usd","success"]].copy()
            df_display["success"] = df_display["success"].map({1:"✓",0:"✗"})
            df_display["cost_usd"] = df_display["cost_usd"].apply(lambda x: f"${x:.6f}")
            st.dataframe(df_display.head(30),use_container_width=True,hide_index=True)

            total_cost = df_u[df_u["success"]==1]["cost_usd"].sum()
            total_calls = len(df_u)
            success_rate = df_u["success"].mean()*100
            c1,c2,c3 = st.columns(3)
            c1.metric("TOTAL COST", f"${total_cost:.4f}")
            c2.metric("TOTAL CALLS", total_calls)
            c3.metric("SUCCESS RATE", f"{success_rate:.1f}%")
        else:
            st.info("No AI usage recorded yet.")

    with tabs[2]:
        st.markdown('<div class="mono-label">EXPORT ALL DATA</div>', unsafe_allow_html=True)
        pid = project["id"]
        col1,col2,col3 = st.columns(3)
        team = get_team(pid)
        sprints = get_sprints(pid)
        risks = get_risks(pid)
        entries = get_budget_entries(pid)

        if team:
            col1.download_button("↓ TEAM CSV", df_to_csv(pd.DataFrame(team)), "team.csv","text/csv",use_container_width=True)
        if sprints:
            df_s = pd.DataFrame([{k:v for k,v in s.items() if k not in ("blockers","retro_notes")} for s in sprints])
            col2.download_button("↓ SPRINTS CSV", df_to_csv(df_s), "sprints.csv","text/csv",use_container_width=True)
        if risks:
            col3.download_button("↓ RISKS CSV", df_to_csv(pd.DataFrame(risks)), "risks.csv","text/csv",use_container_width=True)
        if entries:
            st.download_button("↓ BUDGET CSV", df_to_csv(pd.DataFrame(entries)), "budget.csv","text/csv",use_container_width=True)

        st.markdown("---")
        st.markdown('<div class="mono-label" style="color:#da1e28">DANGER ZONE</div>', unsafe_allow_html=True)
        with st.expander("⚠  DELETE PROJECT DATA"):
            st.error(f"This will permanently delete ALL data for '{project['name']}' including team, sprints, risks, and budget. This cannot be undone.")
            confirm = st.text_input("Type the project name to confirm deletion:")
            if st.button("DELETE PROJECT", type="primary"):
                if confirm == project["name"]:
                    db_exec("DELETE FROM projects WHERE id=?", (pid,))
                    st.success("Project deleted. Reloading..."); st.rerun()
                else:
                    st.error("Project name does not match.")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════
# PAGE: AI ASSISTANT — all features in one place, always visible
# ═════════════════════════════════════════════════════════════════════════════
def page_ai_assistant(project, projects):
    pid = project["id"]
    section_header("AI ASSISTANT", f"All AI features for  {project['name']}")

    # ── Gate: show setup if not configured ───────────────────
    cfg = get_ai_config()
    ai_ready = bool(cfg and cfg.get("api_key"))

    if not ai_ready:
        st.markdown("""
        <div style="background:#1a1a00;border:1px solid #f1c21b;border-left:4px solid #f1c21b;
                    padding:1.5rem 2rem;margin-bottom:2rem">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:0.8rem;letter-spacing:0.1em;
                        color:#f1c21b;margin-bottom:0.75rem">⚡ STEP 1 — ACTIVATE AI</div>
            <div style="font-family:'IBM Plex Sans',sans-serif;font-size:0.9rem;color:#c6c6c6;margin-bottom:0.5rem">
                All 6 AI features below require a DeepSeek API key.<br>
                Get a <strong style="color:#f4f4f4">free key</strong> at
                <a href="https://platform.deepseek.com" target="_blank" style="color:#78a9ff">
                platform.deepseek.com</a> → sign up → API Keys → Create key.
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("ai_assistant_setup"):
            c1, c2 = st.columns([5, 1])
            key_input = c1.text_input(
                "Paste API key here",
                type="password",
                placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                label_visibility="visible",
            )
            st.markdown("")
            if st.form_submit_button("✓  TEST & ACTIVATE", use_container_width=True):
                if not key_input.strip():
                    st.error("Paste your API key above.")
                elif not key_input.strip().startswith("sk-"):
                    st.error("Key must start with  sk-")
                else:
                    with st.spinner("Testing connection to DeepSeek..."):
                        ok, msg = test_api_key(key_input.strip(), DEEPSEEK_URL)
                    if ok:
                        save_ai_config("deepseek", key_input.strip(), "deepseek-chat",
                                       DEEPSEEK_URL, MONTHLY_BUDGET,
                                       ["therapy","simulator","insights","retro","risk","forecast"])
                        st.success("✅  AI activated — all features unlocked. Reloading...")
                        st.rerun()
                    else:
                        st.error(f"Connection failed: {msg}")
        st.markdown("---")
        st.markdown('<div style="font-family:IBM Plex Mono,monospace;font-size:0.8rem;color:#525252;text-align:center;padding:1rem">👇 Preview of all features available once activated</div>', unsafe_allow_html=True)

    # ── Load all project data upfront ────────────────────────
    team    = get_team(pid)
    sprints = get_sprints(pid)
    risks   = get_risks(pid)
    entries = get_budget_entries(pid)

    avg_morale   = sum(m["morale"]   for m in team)/len(team) if team else 75.0
    avg_workload = sum(m["workload"] for m in team)/len(team) if team else 70.0
    completed_sp = [s for s in sprints if s["status"]=="completed"]
    avg_velocity = sum(s["completed_points"] for s in completed_sp)/len(completed_sp) if completed_sp else 30.0
    open_risks   = [r for r in risks if r["status"]=="open"]
    total_expense= sum(e["amount"] for e in entries if e["entry_type"]=="expense")
    remaining_pts= project.get("total_points",0) - project.get("completed_points",0)
    p_ctx        = {k: project[k] for k in ("name","status","team_size","velocity","budget")}

    # ── Feature cards ─────────────────────────────────────────
    # Rendered in a 2-column grid. Each card:
    #   • Icon + title + description always visible
    #   • Input controls (scenario picker, sprint selector, etc.)
    #   • One big RUN button
    #   • Result appears inline below the card

    def feature_header(icon, title, desc, key_suffix):
        st.markdown(f"""
        <div style="background:#1e2a3a;border:1px solid #0f62fe;border-top:3px solid #0f62fe;
                    padding:1rem 1.25rem 0.5rem 1.25rem;margin-bottom:0">
            <div style="font-size:1.4rem;margin-bottom:4px">{icon}</div>
            <div style="font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:0.95rem;
                        color:#f4f4f4;letter-spacing:0.02em">{title}</div>
            <div style="font-family:'IBM Plex Sans',sans-serif;font-size:0.8rem;color:#a8a8a8;
                        margin-top:4px;min-height:2.4rem">{desc}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("")

    # ── Row 1: Health Analysis + What-If Simulator ────────────
    row1_l, row1_r = st.columns(2)

    # ── 1. PROJECT HEALTH ANALYSIS ───────────────────────────
    with row1_l:
        feature_header("🧠", "PROJECT HEALTH ANALYSIS",
                        "Score your project 1–10. Surfaces top concerns and one concrete action for the PM.",
                        "health")
        with st.container(border=True):
            st.markdown(f"""
            <div style="font-family:'IBM Plex Mono',monospace;font-size:0.75rem;color:#a8a8a8;padding:0.5rem 0">
                Team morale: <b style="color:#f4f4f4">{avg_morale:.0f}/100</b> &nbsp;·&nbsp;
                Workload: <b style="color:#f4f4f4">{avg_workload:.0f}%</b> &nbsp;·&nbsp;
                Open risks: <b style="color:#f4f4f4">{len(open_risks)}</b> &nbsp;·&nbsp;
                Budget used: <b style="color:#f4f4f4">{total_expense/project['budget']*100:.0f}%</b>
            </div>
            """, unsafe_allow_html=True)
            run_health = st.button("▶  RUN HEALTH ANALYSIS", key="btn_health",
                                   use_container_width=True, disabled=not ai_ready)

        if run_health:
            with st.spinner("Analysing project health..."):
                prompt = (
                    f"Project health analysis for '{project['name']}'.\n"
                    f"Status: {project['status']}, Priority: {project.get('priority','medium')}\n"
                    f"Team: {len(team)} people, avg morale {avg_morale:.1f}/100, avg workload {avg_workload:.1f}%\n"
                    f"Open risks: {len(open_risks)}, Sprint velocity: {avg_velocity:.1f} pts\n"
                    f"Budget: {total_expense/project['budget']*100:.1f}% used (${total_expense:,.0f} of ${project['budget']:,.0f})\n\n"
                    "Give:\n"
                    "1. Overall health score 1–10 with one-line rationale\n"
                    "2. Top 3 concerns in priority order (one sentence each)\n"
                    "3. One immediate action the PM should take this week"
                )
                resp = call_ai(prompt, "therapy", {"project": p_ctx, "team": {"avg_morale": avg_morale, "avg_workload": avg_workload}})
            render_ai_result(resp, "🧠 PROJECT HEALTH ANALYSIS")

    # ── 2. WHAT-IF SIMULATOR ─────────────────────────────────
    with row1_r:
        feature_header("🎲", "WHAT-IF SIMULATOR",
                        "Model the impact of team or scope changes on schedule, cost, and risk before committing.",
                        "sim")
        with st.container(border=True):
            sim_scenario = st.selectbox("Choose a scenario", [
                "Add 1 senior developer",
                "Add 2 senior developers",
                "Remove 1 team member (attrition)",
                "Reduce scope by 20%",
                "Reduce scope by 30%",
                "Extend deadline by 4 weeks",
                "Cut budget by 15%",
                "Add contractor for 6 weeks",
                "Custom…",
            ], key="sim_scenario", label_visibility="visible")
            if sim_scenario == "Custom…":
                sim_scenario = st.text_input("Describe your scenario", placeholder="e.g. Swap frontend dev for a designer", key="sim_custom")
            run_sim = st.button("▶  RUN SIMULATION", key="btn_sim",
                                use_container_width=True, disabled=not ai_ready)

        if run_sim:
            sim_scenario = st.session_state.get("sim_custom") if st.session_state.get("sim_scenario") == "Custom…" else st.session_state.get("sim_scenario", "Add 1 senior developer")
            with st.spinner(f"Simulating: {sim_scenario}..."):
                prompt = (
                    f"What-if simulation for '{project['name']}'.\n"
                    f"Current state: team={len(team)}, velocity={avg_velocity:.1f} pts/sprint, "
                    f"remaining={remaining_pts} pts, budget remaining=${project['budget']-total_expense:,.0f}\n"
                    f"Scenario: {sim_scenario}\n\n"
                    "Give:\n"
                    "1. Predicted outcome with probability estimate (%)\n"
                    "2. Impact on delivery date (weeks earlier/later)\n"
                    "3. Impact on budget ($)\n"
                    "4. Top risk introduced by this change\n"
                    "5. Recommendation: proceed / proceed with caution / avoid"
                )
                resp = call_ai(prompt, "simulator", p_ctx)
            render_ai_result(resp, f"🎲 SIMULATION — {sim_scenario.upper()}")

    st.markdown("---")

    # ── Row 2: Sprint Retrospective + Risk Analysis ───────────
    row2_l, row2_r = st.columns(2)

    # ── 3. SPRINT RETROSPECTIVE ───────────────────────────────
    with row2_l:
        feature_header("🔄", "SPRINT RETROSPECTIVE",
                        "Generate an AI-facilitated retro for any completed sprint: went well, improve, action items.",
                        "retro")
        with st.container(border=True):
            completed_names = [f"Sprint {s['number']}: {s.get('goal','')[:35]}" for s in completed_sp]
            if not completed_names:
                st.caption("No completed sprints yet.")
                run_retro = st.button("▶  RUN RETROSPECTIVE", key="btn_retro",
                                      use_container_width=True, disabled=True)
                sel_sprint_retro = None
            else:
                retro_choice = st.selectbox("Select sprint", completed_names, key="retro_sprint")
                sel_num = int(retro_choice.split(":")[0].replace("Sprint","").strip())
                sel_sprint_retro = next((s for s in completed_sp if s["number"]==sel_num), completed_sp[-1])
                existing_notes = sel_sprint_retro.get("retro_notes", {})
                run_retro = st.button("▶  RUN RETROSPECTIVE", key="btn_retro",
                                      use_container_width=True, disabled=not ai_ready)

        if run_retro and completed_sp:
            # Read sprint selection from session_state to get the value at button-press time
            retro_key = st.session_state.get("retro_sprint", completed_names[0] if completed_names else "")
            try:
                sel_num = int(retro_key.split(":")[0].replace("Sprint","").strip())
                sel_sprint_retro = next((s for s in completed_sp if s["number"]==sel_num), completed_sp[-1])
            except (ValueError, IndexError):
                sel_sprint_retro = completed_sp[-1]
            with st.spinner("Generating retrospective..."):
                notes = sel_sprint_retro.get("retro_notes", {})
                prompt = (
                    f"Sprint retrospective for Sprint {sel_sprint_retro['number']} of '{project['name']}'.\n"
                    f"Goal: {sel_sprint_retro.get('goal','not set')}\n"
                    f"Velocity: {sel_sprint_retro['completed_points']}/{sel_sprint_retro['planned_points']} pts "
                    f"({sel_sprint_retro['completion_pct']:.0f}% complete)\n"
                    f"Blockers: {', '.join(sel_sprint_retro['blockers']) or 'none'}\n"
                    f"Team notes — Went well: {notes.get('went_well','none')}\n"
                    f"Team notes — To improve: {notes.get('improve','none')}\n"
                    f"Team notes — Actions: {notes.get('actions','none')}\n\n"
                    "Structure your response as:\n"
                    "**WENT WELL** (2–3 bullets)\n"
                    "**TO IMPROVE** (2–3 bullets)\n"
                    "**ACTION ITEMS** (3 specific, owner-assignable tasks)\n"
                    "**PATTERN** (one insight connecting this sprint to the project trend)"
                )
                resp = call_ai(prompt, "retro", {"sprint": sel_sprint_retro["number"], "project": project["name"]})
            render_ai_result(resp, f"🔄 RETROSPECTIVE — SPRINT {sel_sprint_retro['number']}")

    # ── 4. RISK ANALYSIS ─────────────────────────────────────
    with row2_r:
        feature_header("⚠️", "RISK ANALYSIS",
                        "AI-prioritised risk report: critical items, emerging patterns, and specific mitigations.",
                        "risk")
        with st.container(border=True):
            risk_focus = st.selectbox("Focus area", [
                "Full risk register review",
                "Critical risks only (score ≥ 12)",
                "People & team risks",
                "Technical risks",
                "Financial risks",
                "Next sprint risk forecast",
            ], key="risk_focus", label_visibility="visible")
            if not risks:
                st.caption("No risks logged yet. Add risks in the Risk Register page.")
            run_risk_ai = st.button("▶  RUN RISK ANALYSIS", key="btn_risk",
                                    use_container_width=True, disabled=(not ai_ready or not risks))

        if run_risk_ai:
            # Read focus directly from session_state — guaranteed current value
            # even after Streamlit re-runs the script on button press
            risk_focus = st.session_state.get("risk_focus", "Full risk register review")

            # ── Build full risk data ──────────────────────────────
            all_risk_data = [{
                "title":      r["title"],
                "category":   r["category"],
                "probability":r["probability"],
                "impact":     r["impact"],
                "score":      r["probability"] * r["impact"],
                "status":     r["status"],
                "owner":      r.get("owner", "unassigned"),
                "mitigation": r.get("mitigation", "none"),
                "description":r.get("description", ""),
            } for r in risks]

            # ── Filter data AND tailor prompt per focus area ──────
            CATEGORY_MAP = {
                "People & team risks":  ["people"],
                "Technical risks":      ["technical"],
                "Financial risks":      ["financial"],
            }

            if risk_focus == "Critical risks only (score ≥ 12)":
                filtered = [r for r in all_risk_data if r["score"] >= 12]
                focus_instruction = (
                    "You are reviewing CRITICAL risks only (probability × impact ≥ 12).\n"
                    "Give:\n"
                    "1. For each critical risk: severity verdict, immediate action required, and who should own it\n"
                    "2. Are any of these risks connected or could they cascade? Explain\n"
                    "3. Emergency mitigation: what must be done in the next 48 hours\n"
                    "4. Escalation recommendation: which risks need executive attention"
                )

            elif risk_focus in CATEGORY_MAP:
                cats = CATEGORY_MAP[risk_focus]
                filtered = [r for r in all_risk_data if r["category"] in cats]
                category_label = risk_focus.replace(" risks", "").upper()
                focus_instruction = (
                    f"You are reviewing {risk_focus.upper()} ONLY — ignore other categories.\n"
                    "Give:\n"
                    f"1. Assessment of the {category_label} risk landscape: is it well-managed or a concern?\n"
                    f"2. Highest-priority {category_label} risk and why it outranks the others\n"
                    f"3. Gaps: what {category_label} risks are likely missing from this register?\n"
                    f"4. Specific {category_label} mitigation actions the team should take this sprint"
                )

            elif risk_focus == "Next sprint risk forecast":
                filtered = [r for r in all_risk_data if r["status"] == "open"]
                sprint_context = f"{len(completed_sp)} sprints completed, avg velocity {avg_velocity:.1f} pts"
                focus_instruction = (
                    "You are forecasting which risks are most likely to MATERIALISE in the next sprint.\n"
                    f"Sprint context: {sprint_context}\n"
                    "Give:\n"
                    "1. Top 2 risks most likely to hit in the next 2 weeks — explain your reasoning\n"
                    "2. Early warning signs the team should watch for each\n"
                    "3. Pre-emptive actions to take BEFORE the sprint starts\n"
                    "4. Risk that has the highest chance of derailing the sprint goal"
                )

            else:  # Full risk register review
                filtered = all_risk_data
                focus_instruction = (
                    "You are doing a FULL risk register review across all categories.\n"
                    "Give:\n"
                    "1. Overall risk posture: red / amber / green with one-line justification\n"
                    "2. Top 3 risks requiring immediate action (with specific next steps and owners)\n"
                    "3. One systemic pattern or root cause connecting multiple risks\n"
                    "4. One risk that appears underestimated based on its current score vs description"
                )

            # ── Fall back to all risks if filter returns nothing ──
            if not filtered:
                filtered = all_risk_data
                st.caption(f"No risks found in category '{risk_focus}' — showing full register.")

            risk_list_text = "\n".join(
                f"- [{r['category'].upper()}] {r['title']} "
                f"| P={r['probability']} I={r['impact']} Score={r['score']} "
                f"| {r['status'].upper()} | Owner: {r['owner']} "
                f"| Mitigation: {r['mitigation']}"
                for r in sorted(filtered, key=lambda x: -x["score"])
            )

            with st.spinner(f"Analysing: {risk_focus}..."):
                prompt = (
                    f"Risk analysis for project '{project['name']}'.\n"
                    f"Total risks in register: {len(risks)} "
                    f"({len(open_risks)} open, "
                    f"{len([r for r in risks if r['status']=='mitigated'])} mitigated, "
                    f"{len([r for r in risks if r['status']=='closed'])} closed)\n\n"
                    f"Risks being analysed ({len(filtered)} of {len(risks)}):\n"
                    f"{risk_list_text}\n\n"
                    f"{focus_instruction}"
                )
                resp = call_ai(prompt, "risk", {"project": project["name"], "focus": risk_focus, "risk_count": len(filtered)})
            render_ai_result(resp, f"⚠️ RISK ANALYSIS — {risk_focus.upper()}")

    st.markdown("---")

    # ── Row 3: Delivery Forecast + Cross-Project Insights ─────
    row3_l, row3_r = st.columns(2)

    # ── 5. DELIVERY FORECAST ─────────────────────────────────
    with row3_l:
        feature_header("📅", "DELIVERY FORECAST",
                        "Data-driven delivery date estimate with confidence intervals based on actual sprint velocity.",
                        "forecast")
        with st.container(border=True):
            velocities = [s["completed_points"] for s in completed_sp] if completed_sp else []
            st.markdown(f"""
            <div style="font-family:'IBM Plex Mono',monospace;font-size:0.75rem;color:#a8a8a8;padding:0.5rem 0">
                Remaining: <b style="color:#f4f4f4">{remaining_pts} pts</b> &nbsp;·&nbsp;
                Avg velocity: <b style="color:#f4f4f4">{avg_velocity:.1f} pts/sprint</b> &nbsp;·&nbsp;
                Sprints done: <b style="color:#f4f4f4">{len(completed_sp)}</b>
            </div>
            """, unsafe_allow_html=True)
            forecast_scenario = st.selectbox("Scenario", [
                "Current pace (no changes)",
                "Add 1 developer next sprint",
                "Reduce scope by 20%",
                "Team velocity improves 10% (learning curve)",
                "Velocity drops 15% (team fatigue)",
            ], key="forecast_scenario")
            run_forecast = st.button("▶  RUN FORECAST", key="btn_forecast",
                                     use_container_width=True, disabled=not ai_ready)

        if run_forecast:
            forecast_scenario = st.session_state.get("forecast_scenario", "Current pace (no changes)")
            with st.spinner("Calculating delivery forecast..."):
                prompt = (
                    f"Delivery forecast for '{project['name']}'.\n"
                    f"Total points: {project.get('total_points',0)}, "
                    f"Completed: {project.get('completed_points',0)}, "
                    f"Remaining: {remaining_pts} pts\n"
                    f"Sprint history (completed points): {velocities}\n"
                    f"Avg velocity: {avg_velocity:.1f} pts/sprint, Sprint length: 2 weeks\n"
                    f"Budget remaining: ${project['budget']-total_expense:,.0f}\n"
                    f"Target end date: {project.get('end_date','not set')}\n"
                    f"Scenario: {forecast_scenario}\n\n"
                    "Give:\n"
                    "1. Expected delivery date with 80% confidence interval (best / most likely / worst case)\n"
                    "2. Probability of hitting the original target end date (%)\n"
                    "3. Number of sprints remaining under this scenario\n"
                    "4. Budget projection at completion\n"
                    "5. Top factor that would change this forecast"
                )
                resp = call_ai(prompt, "forecast", p_ctx)
            render_ai_result(resp, f"📅 DELIVERY FORECAST — {forecast_scenario.upper()}")

    # ── 6. CROSS-PROJECT INSIGHTS ─────────────────────────────
    with row3_r:
        feature_header("🔗", "CROSS-PROJECT INSIGHTS",
                        "Compare projects in your portfolio to surface patterns, lessons, and resource opportunities.",
                        "insights")
        with st.container(border=True):
            all_projects = get_projects()
            if len(all_projects) < 2:
                st.caption("Add a second project to enable comparison.")
                run_insights = st.button("▶  RUN COMPARISON", key="btn_insights",
                                         use_container_width=True, disabled=True)
            else:
                other_projects = [p for p in all_projects if p["id"] != pid]
                compare_to = st.selectbox("Compare with", [p["name"] for p in other_projects], key="compare_proj")
                insights_focus = st.selectbox("Focus", [
                    "Overall comparison",
                    "Velocity & delivery performance",
                    "Team & resource patterns",
                    "Risk patterns",
                    "Budget efficiency",
                ], key="insights_focus")
                run_insights = st.button("▶  RUN COMPARISON", key="btn_insights",
                                         use_container_width=True, disabled=not ai_ready)

            if run_insights and len(all_projects) >= 2:
                # Read both selectors from session_state — guaranteed correct on re-run
                compare_to    = st.session_state.get("compare_proj", other_projects[0]["name"])
                insights_focus = st.session_state.get("insights_focus", "Overall comparison")
                proj_b = next((p for p in all_projects if p["name"] == compare_to), other_projects[0])
                team_b = get_team(proj_b["id"])
                sprints_b = get_sprints(proj_b["id"])
                completed_b = [s for s in sprints_b if s["status"]=="completed"]
                vel_b = sum(s["completed_points"] for s in completed_b)/len(completed_b) if completed_b else 0
                with st.spinner("Comparing projects..."):
                    prompt = (
                        f"Cross-project comparison. Focus: {insights_focus}\n\n"
                        f"Project A: '{project['name']}'\n"
                        f"  Status: {project['status']}, Team: {len(team)}, "
                        f"Velocity: {avg_velocity:.1f} pts/sprint, "
                        f"Budget: ${project['budget']:,.0f} ({total_expense/project['budget']*100:.0f}% used), "
                        f"Open risks: {len(open_risks)}\n\n"
                        f"Project B: '{proj_b['name']}'\n"
                        f"  Status: {proj_b['status']}, Team: {len(team_b)}, "
                        f"Velocity: {vel_b:.1f} pts/sprint, "
                        f"Budget: ${proj_b['budget']:,.0f}, "
                        f"Open risks: {len([r for r in get_risks(proj_b['id']) if r['status']=='open'])}\n\n"
                        "Give:\n"
                        "1. Which project is performing better and why\n"
                        "2. Most significant difference between the projects\n"
                        "3. Specific lesson from the better-performing project the other should adopt\n"
                        "4. Resource or process that could be shared between projects"
                    )
                    resp = call_ai(prompt, "insights")
                render_ai_result(resp, f"🔗 COMPARISON — {project['name'].upper()} vs {compare_to.upper()}")


# ═════════════════════════════════════════════════════════════════════════════
def main():
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="⬛",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()
    init_db()
    seed_if_empty()

    # ── Sidebar ───────────────────────────────────────────────
    with st.sidebar:
        st.markdown(f"""
        <div style="padding:1rem 0 0.5rem 0">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:1.1rem;font-weight:600;color:#f4f4f4;letter-spacing:0.05em">
                {APP_TITLE.upper()}
            </div>
            <div style="font-family:'IBM Plex Mono',monospace;font-size:0.68rem;color:#525252;letter-spacing:0.12em">
                v{APP_VERSION}
            </div>
        </div>
        """, unsafe_allow_html=True)

        project, projects = select_project()
        if not project:
            st.warning("No projects found.")
            st.stop()

        st.markdown("---")
        page = st.radio("", [
            "DASHBOARD",
            "⬡ AI ASSISTANT",
            "SPRINT BOARD",
            "RISK REGISTER",
            "BUDGET",
            "TEAM",
            "PROJECTS",
            "SETTINGS",
        ], label_visibility="collapsed")

        st.markdown("---")
        # Status panel
        cfg = get_ai_config()
        ai_ok = bool(cfg and cfg.get("api_key"))
        monthly_cost = get_monthly_cost()
        budget = cfg["monthly_budget"] if cfg else MONTHLY_BUDGET
        budget_pct_side = min(100, monthly_cost/budget*100) if budget else 0

        st.markdown(f"""
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;color:#525252;letter-spacing:0.08em;margin-bottom:8px">SYSTEM STATUS</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.8rem;color:{'#42be65' if ai_ok else '#da1e28'};margin-bottom:4px">
            {'● AI READY' if ai_ok else '● AI OFFLINE'}
        </div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.8rem;color:#42be65;margin-bottom:4px">
            ● DB CONNECTED
        </div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;color:#a8a8a8;margin-top:8px">
            AI BUDGET: ${monthly_cost:.4f} / ${budget:.2f}
        </div>
        <div style="background:#393939;height:3px;margin-top:4px">
            <div style="background:{'#da1e28' if budget_pct_side>90 else '#f1c21b' if budget_pct_side>70 else '#0f62fe'};height:3px;width:{budget_pct_side:.0f}%"></div>
        </div>
        """, unsafe_allow_html=True)

        # Sidebar quick-setup when AI not configured
        if not ai_ok:
            st.markdown("---")
            st.markdown('<div style="font-family:IBM Plex Mono,monospace;font-size:0.7rem;letter-spacing:0.08em;color:#f1c21b;margin-bottom:6px">⚡ QUICK SETUP</div>', unsafe_allow_html=True)
            with st.form("sidebar_ai_setup"):
                sb_key = st.text_input("DeepSeek API Key", type="password",
                                       placeholder="sk-...",
                                       label_visibility="collapsed",
                                       help="Get free key at platform.deepseek.com")
                if st.form_submit_button("ACTIVATE AI", use_container_width=True):
                    if not sb_key.strip():
                        st.error("Enter API key")
                    elif not sb_key.strip().startswith("sk-"):
                        st.error("Must start with sk-")
                    else:
                        with st.spinner("Connecting..."):
                            ok, msg = test_api_key(sb_key.strip(), DEEPSEEK_URL)
                        if ok:
                            save_ai_config("deepseek", sb_key.strip(), "deepseek-chat",
                                           DEEPSEEK_URL, MONTHLY_BUDGET,
                                           ["therapy","simulator","insights","retro","risk","forecast"])
                            st.success("✅ AI activated!")
                            st.rerun()
                        else:
                            st.error(msg)
            st.markdown('<div style="font-family:IBM Plex Mono,monospace;font-size:0.68rem;color:#525252">platform.deepseek.com → API Keys</div>', unsafe_allow_html=True)

        if not CRYPTO_AVAILABLE:
            st.markdown('<div style="font-family:IBM Plex Mono,monospace;font-size:0.7rem;color:#f1c21b;margin-top:8px">⚠ cryptography not installed</div>', unsafe_allow_html=True)

    # ── Route ─────────────────────────────────────────────────
    pages = {
        "DASHBOARD":       page_dashboard,
        "⬡ AI ASSISTANT":  page_ai_assistant,
        "SPRINT BOARD":    page_sprints,
        "RISK REGISTER":   page_risks,
        "BUDGET":          page_budget,
        "TEAM":            page_team,
        "PROJECTS":        page_projects,
        "SETTINGS":        page_settings,
    }
    pages[page](project, projects)


if __name__ == "__main__":
    main()
