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

    /* ═══════════════════════════════════════════════
       BASE — mobile-first, scaled up for desktop
    ═══════════════════════════════════════════════ */
    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', sans-serif !important;
        background-color: #161616 !important;
        color: #f4f4f4 !important;
        -webkit-tap-highlight-color: transparent;
        -webkit-text-size-adjust: 100%;
    }

    /* ── Main container — tight on mobile, roomy on desktop ── */
    .main .block-container {
        padding: 1rem 0.75rem 5rem 0.75rem !important;
        max-width: 1400px !important;
        background: #161616 !important;
    }
    @media (min-width: 768px) {
        .main .block-container {
            padding: 1.5rem 2rem 4rem 2rem !important;
        }
    }

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {
        background: #0f0f0f !important;
        border-right: 1px solid #393939 !important;
    }
    section[data-testid="stSidebar"] * { color: #f4f4f4 !important; }
    section[data-testid="stSidebar"] .stRadio label {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.9rem !important;        /* larger tap target on mobile */
        letter-spacing: 0.04em !important;
        padding: 10px 0 !important;          /* 44px min touch target */
        display: block !important;
    }

    /* ── Page headers — scale down on small screens ── */
    h1, h2, h3 {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: -0.01em !important;
        color: #f4f4f4 !important;
    }
    h1 {
        font-size: 1.4rem !important;
        border-bottom: 2px solid #0f62fe;
        padding-bottom: 0.4rem;
        word-break: break-word;
    }
    h2 { font-size: 1.15rem !important; color: #c6c6c6 !important; }
    h3 { font-size: 1rem !important;    color: #a8a8a8 !important; }
    @media (min-width: 768px) {
        h1 { font-size: 2rem !important; }
        h2 { font-size: 1.4rem !important; }
        h3 { font-size: 1.1rem !important; }
    }

    /* ── Metric cards — compact on mobile ── */
    [data-testid="metric-container"] {
        background: #262626 !important;
        border: 1px solid #393939 !important;
        border-top: 3px solid #0f62fe !important;
        padding: 0.6rem 0.5rem !important;
        border-radius: 0 !important;
        min-width: 0 !important;
        overflow: hidden !important;
    }
    [data-testid="metric-container"] label {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.58rem !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        color: #a8a8a8 !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 1.15rem !important;
        font-weight: 600 !important;
        color: #f4f4f4 !important;
        white-space: nowrap !important;
    }
    [data-testid="metric-container"] [data-testid="stMetricDelta"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.62rem !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    @media (min-width: 768px) {
        [data-testid="metric-container"] { padding: 1rem !important; }
        [data-testid="metric-container"] label { font-size: 0.72rem !important; }
        [data-testid="metric-container"] [data-testid="stMetricValue"] { font-size: 1.8rem !important; }
        [data-testid="metric-container"] [data-testid="stMetricDelta"] { font-size: 0.78rem !important; }
    }

    /* ── Buttons — 44px min height for touch targets ── */
    .stButton > button {
        background: #0f62fe !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 0 !important;
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 500 !important;
        font-size: 0.875rem !important;
        letter-spacing: 0.01em !important;
        padding: 0.75rem 1rem !important;
        min-height: 44px !important;
        width: 100% !important;             /* full-width by default on mobile */
        transition: background 0.1s !important;
        -webkit-appearance: none !important;
        touch-action: manipulation !important;
    }
    .stButton > button:hover,
    .stButton > button:active { background: #0043ce !important; }
    .stButton > button[kind="secondary"] {
        background: #393939 !important;
        color: #f4f4f4 !important;
    }
    .stButton > button[kind="secondary"]:hover { background: #525252 !important; }
    .stButton > button:disabled {
        background: #262626 !important;
        color: #525252 !important;
        cursor: not-allowed !important;
    }

    /* ── Inputs — large enough to avoid iOS zoom (16px min) ── */
    .stTextInput input, .stNumberInput input, .stTextArea textarea,
    .stSelectbox > div > div, .stMultiselect > div > div {
        background: #262626 !important;
        border: 1px solid #525252 !important;
        border-radius: 0 !important;
        color: #f4f4f4 !important;
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 16px !important;          /* prevents iOS auto-zoom */
        min-height: 44px !important;
        -webkit-appearance: none !important;
    }
    @media (min-width: 768px) {
        .stTextInput input, .stNumberInput input, .stTextArea textarea,
        .stSelectbox > div > div, .stMultiselect > div > div {
            font-size: 0.875rem !important;
        }
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #0f62fe !important;
        box-shadow: inset 0 0 0 2px #0f62fe !important;
        outline: none !important;
    }
    label {
        color: #c6c6c6 !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
    }

    /* ── Dataframes — horizontal scroll on mobile ── */
    .stDataFrame {
        border: 1px solid #393939 !important;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
        display: block !important;
    }
    .stDataFrame thead tr th {
        background: #393939 !important;
        color: #c6c6c6 !important;
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.65rem !important;
        letter-spacing: 0.04em !important;
        text-transform: uppercase !important;
        border-bottom: 2px solid #525252 !important;
        white-space: nowrap !important;
    }
    .stDataFrame tbody tr td {
        background: #262626 !important;
        color: #f4f4f4 !important;
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.75rem !important;
        border-bottom: 1px solid #393939 !important;
        white-space: nowrap !important;
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
        padding: 0.9rem 1rem !important;     /* tall enough to tap comfortably */
        color: #c6c6c6 !important;
        background: #262626 !important;
        border-bottom: 1px solid #393939 !important;
        min-height: 44px !important;
        cursor: pointer !important;
    }

    /* ── Divider ── */
    hr { border-color: #393939 !important; margin: 1.25rem 0 !important; }

    /* ── Tabs — horizontally scrollable on mobile ── */
    .stTabs [data-baseweb="tab-list"] {
        background: #1e1e1e !important;
        border-bottom: 2px solid #393939 !important;
        gap: 0 !important;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
        scrollbar-width: none !important;
        flex-wrap: nowrap !important;
    }
    .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display: none !important; }
    .stTabs [data-baseweb="tab"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.72rem !important;
        letter-spacing: 0.03em !important;
        color: #a8a8a8 !important;
        background: transparent !important;
        border-radius: 0 !important;
        padding: 0.75rem 0.85rem !important;
        border-bottom: 3px solid transparent !important;
        white-space: nowrap !important;
        min-height: 44px !important;
        flex-shrink: 0 !important;
    }
    .stTabs [aria-selected="true"] {
        color: #f4f4f4 !important;
        border-bottom: 3px solid #0f62fe !important;
        background: transparent !important;
    }
    .stTabs [data-baseweb="tab-panel"] {
        background: #161616 !important;
        padding-top: 1rem !important;
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
    .stAlert {
        border-radius: 0 !important;
        border-left: 4px solid !important;
        padding: 0.75rem !important;
        font-size: 0.875rem !important;
    }
    .stSuccess { border-left-color: #24a148 !important; background: #0d2e1a !important; }
    .stError   { border-left-color: #da1e28 !important; background: #2d0a0e !important; }
    .stWarning { border-left-color: #f1c21b !important; background: #2c2200 !important; }
    .stInfo    { border-left-color: #0f62fe !important; background: #01162e !important; }

    /* ── Checkboxes / Radio ── */
    .stCheckbox label, .stRadio label {
        color: #c6c6c6 !important;
        font-size: 0.9rem !important;
        min-height: 36px !important;
        display: flex !important;
        align-items: center !important;
    }

    /* ── Slider — larger thumb for touch ── */
    .stSlider [data-testid="stThumbValue"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.78rem !important;
    }
    .stSlider [data-baseweb="slider"] [role="slider"] {
        width: 22px !important;
        height: 22px !important;
    }

    /* ── Select boxes dropdown ── */
    [data-baseweb="select"] * { background: #262626 !important; color: #f4f4f4 !important; }
    [data-baseweb="popover"]  { background: #262626 !important; border: 1px solid #525252 !important; }
    [data-baseweb="menu"] li  { min-height: 44px !important; }  /* tap-friendly dropdown rows */

    /* ── IBM tag styles ── */
    .ibm-tag {
        display: inline-block;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.65rem;
        letter-spacing: 0.04em;
        padding: 3px 7px;
        margin: 2px 2px;
        border: 1px solid;
        white-space: nowrap;
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
        padding: 1rem;
        margin-bottom: 1rem;
    }
    @media (min-width: 768px) {
        .carbon-card { padding: 1.25rem 1.5rem; }
    }
    .carbon-card-red    { border-top-color: #da1e28 !important; }
    .carbon-card-green  { border-top-color: #24a148 !important; }
    .carbon-card-yellow { border-top-color: #f1c21b !important; }

    /* ── Mono labels ── */
    .mono-label {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.65rem;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #a8a8a8;
        margin-bottom: 4px;
    }
    @media (min-width: 768px) {
        .mono-label { font-size: 0.7rem; }
    }
    .mono-value {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.2rem;
        font-weight: 600;
        color: #f4f4f4;
    }

    /* ── Risk matrix — horizontally scrollable on mobile ── */
    .risk-matrix-wrap {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
    }
    .risk-cell {
        display: inline-block;
        width: 44px; height: 44px;
        line-height: 44px;
        text-align: center;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.7rem;
        font-weight: 600;
        border: 1px solid #393939;
    }

    /* ── Feature header cards — full-width on mobile ── */
    .feature-header-card {
        background: #1e2a3a;
        border: 1px solid #0f62fe;
        border-top: 3px solid #0f62fe;
        padding: 0.875rem 1rem 0.5rem 1rem;
        margin-bottom: 0;
    }

    /* ── Streamlit column gap — reduce on mobile ── */
    [data-testid="column"] {
        padding-left: 0.25rem !important;
        padding-right: 0.25rem !important;
    }
    @media (min-width: 768px) {
        [data-testid="column"] {
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
    }

    /* ── Plotly charts — full width, no overflow ── */
    .js-plotly-plot, .plotly {
        max-width: 100% !important;
        overflow: hidden !important;
    }

    /* ── Scrollable code block ── */
    .stCodeBlock {
        border-radius: 0 !important;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
    }

    /* ── Form submit btn ── */
    .stForm [data-testid="stFormSubmitButton"] button {
        background: #24a148 !important;
        width: 100% !important;
        min-height: 48px !important;
        font-size: 1rem !important;
    }
    .stForm [data-testid="stFormSubmitButton"] button:hover { background: #198038 !important; }

    /* ── Number input spinners — bigger on mobile ── */
    .stNumberInput button {
        min-width: 36px !important;
        min-height: 44px !important;
    }

    /* ── Spinner text ── */
    .stSpinner > div { font-family: 'IBM Plex Mono', monospace !important; font-size: 0.8rem !important; }

    /* ── Hide streamlit branding ── */
    #MainMenu, footer, header { visibility: hidden !important; }

    /* ── Safe area inset ── */
    .main { padding-bottom: env(safe-area-inset-bottom, 0) !important; }



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

    # KPI row — 3 cols on mobile, 6 on desktop via two rows
    c1,c2,c3 = st.columns(3)
    c1.metric("VELOCITY",     f"{avg_velocity:.0f} pts", "Sprint avg")
    c2.metric("MORALE",       f"{avg_morale:.0f}/100",   f"{'↑ Good' if avg_morale>70 else '↓ Risk'}")
    c3.metric("WORKLOAD",     f"{avg_workload:.0f}%",    f"{'↑ High' if avg_workload>85 else 'OK'}",
              delta_color="inverse" if avg_workload>85 else "normal")
    c4,c5,c6 = st.columns(3)
    c4.metric("OPEN RISKS",   str(open_risks),           f"{'⚠ Review' if open_risks>3 else 'OK'}",
              delta_color="inverse" if open_risks>3 else "off")
    c5.metric("BUDGET",       f"{budget_pct:.0f}%",      f"${total_expense:,.0f} used")
    c6.metric("AI SPEND",     f"${monthly_cost:.4f}",    f"${budget-monthly_cost:.2f} left")

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
        run_health = st.button("▶  HEALTH ANALYSIS",   use_container_width=True, key="dash_health")
        run_sim    = st.button("▶  SCENARIO FORECAST", use_container_width=True, key="dash_sim")
        run_risk   = st.button("▶  RISK ANALYSIS",     use_container_width=True, key="dash_risk")

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

    tabs = st.tabs(["OVERVIEW","PLANNING","🔄 RETRO","📅 FORECAST"])

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

    c1,c2 = st.columns(2)
    c1.metric("TOTAL RISKS", len(risks))
    c2.metric("OPEN", len(open_r), delta=f"{len(critical_r)} critical", delta_color="inverse" if critical_r else "off")
    c3,c4 = st.columns(2)
    c3.metric("MITIGATED", len(mitig_r))
    c4.metric("CLOSED", len(closed_r))

    tabs = st.tabs(["REGISTER","MATRIX","ADD RISK","🤖 AI"])

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

    c1,c2 = st.columns(2)
    c1.metric("TOTAL BUDGET",  f"${budget:,.0f}")
    c2.metric("TOTAL SPEND",   f"${total_expense:,.0f}", f"{budget_pct:.1f}% used",
              delta_color="inverse" if budget_pct>90 else "off")
    c3,c4 = st.columns(2)
    c3.metric("INCOME",        f"${total_income:,.0f}")
    c4.metric("NET REMAINING", f"${remaining:,.0f}",
              delta_color="inverse" if remaining<0 else "normal")

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

        c1,c2,c3 = st.columns(3)
        c1.metric("HEADCOUNT",    len(team))
        c2.metric("AVG MORALE",   f"{avg_morale:.0f}/100",  f"{'↑ Good' if avg_morale>70 else '↓ Risk'}")
        c3.metric("AVG WORKLOAD", f"{avg_workload:.0f}%",   delta_color="inverse" if avg_workload>85 else "normal")
        c4,c5 = st.columns(2)
        c4.metric("AT RISK",      overloaded+low_morale_n,  f"{overloaded} overloaded · {low_morale_n} morale")
        c5.metric("DAILY COST",   f"${total_daily:,.0f}")

        tabs = st.tabs(["ROSTER","📊 CHART","✏️ EDIT","🤖 AI"])

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

    tabs = st.tabs(["PORTFOLIO","➕ CREATE","ACTIVITY"])

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
    section_header("SETTINGS", "AI configuration & system")

    cfg          = get_ai_config()
    monthly_cost = get_monthly_cost()
    budget       = cfg["monthly_budget"] if cfg else MONTHLY_BUDGET
    budget_pct   = min(100.0, monthly_cost / budget * 100) if budget else 0
    has_key      = bool(cfg and cfg.get("api_key"))

    # ── Section selector — radio always renders on mobile, tabs often don't ──
    section = st.radio(
        "Section",
        ["🔑  API CONFIG", "📊  USAGE", "💾  DATA"],
        horizontal=True,
        label_visibility="collapsed",
        key="settings_section",
    )
    st.markdown("---")

    # ══════════════════════════════════════════════════════════════
    # SECTION: API CONFIG
    # ══════════════════════════════════════════════════════════════
    if section == "🔑  API CONFIG":

        if not CRYPTO_AVAILABLE:
            st.warning("⚠  `cryptography` not installed — keys stored unencrypted.\n`pip install cryptography`")

        st.info(
            "Get a free key at [platform.deepseek.com](https://platform.deepseek.com) "
            "→ sign up → API Keys → Create key.",
            icon="🔑",
        )

        if has_key:
            st.markdown(f"""
            <div style="background:#071908;border:1px solid #24a148;border-left:4px solid #24a148;
                        padding:0.75rem 1rem;margin-bottom:1rem;
                        font-family:'IBM Plex Mono',monospace;font-size:0.8rem;word-break:break-all">
                ● AI ACTIVE &nbsp;·&nbsp; Key: {mask_key(cfg['api_key'])}
                &nbsp;·&nbsp; Model: {cfg.get('model','—')}
            </div>
            """, unsafe_allow_html=True)

        with st.form("ai_config_form"):
            st.markdown('<div class="mono-label">API KEY</div>', unsafe_allow_html=True)
            api_key = st.text_input(
                "API Key", type="password",
                placeholder="sk-... (blank = keep existing)" if has_key else "sk-xxxxxxxxxxxxxxxxxxxx",
                label_visibility="collapsed",
                autocomplete="off",
            )

            st.markdown('<div class="mono-label" style="margin-top:12px">MODEL</div>', unsafe_allow_html=True)
            model = st.selectbox(
                "Model",
                ["deepseek-chat", "deepseek-coder"],
                index=0 if not cfg else ["deepseek-chat","deepseek-coder"].index(
                    cfg.get("model", "deepseek-chat")),
                label_visibility="collapsed",
            )

            st.markdown('<div class="mono-label" style="margin-top:12px">BASE URL</div>', unsafe_allow_html=True)
            base_url = st.text_input(
                "Base URL",
                value=cfg.get("base_url", DEEPSEEK_URL) if cfg else DEEPSEEK_URL,
                label_visibility="collapsed",
            )

            st.markdown('<div class="mono-label" style="margin-top:12px">MONTHLY BUDGET (USD)</div>',
                        unsafe_allow_html=True)
            new_budget = st.number_input(
                "Budget", 1.0, 10000.0, float(budget), step=5.0,
                label_visibility="collapsed",
            )
            st.progress(
                budget_pct / 100,
                text=f"${monthly_cost:.4f} of ${budget:.2f} used ({budget_pct:.1f}%)",
            )

            st.markdown('<div class="mono-label" style="margin-top:12px">ENABLED FEATURES</div>',
                        unsafe_allow_html=True)
            feat_opts = {
                "therapy":   "Health Analysis",
                "simulator": "What-If Simulator",
                "insights":  "Portfolio Insights",
                "retro":     "Retrospective",
                "risk":      "Risk Analysis",
                "forecast":  "Delivery Forecast",
            }
            current  = cfg["features"] if cfg else list(feat_opts.keys())
            features = [k for k, v in feat_opts.items()
                        if st.checkbox(v, value=k in current, key=f"feat_{k}")]

            st.markdown("")
            if st.form_submit_button("SAVE CONFIGURATION", use_container_width=True):
                key_to_save = (api_key.strip() if api_key and api_key.strip()
                               else (cfg["api_key"] if cfg else ""))
                if not key_to_save:
                    st.error("API key is required.")
                elif not features:
                    st.error("Enable at least one feature.")
                else:
                    save_ai_config("deepseek", key_to_save, model, base_url, new_budget, features)
                    st.success("✅  Configuration saved.")
                    st.rerun()

        st.markdown("---")
        st.markdown('<div class="mono-label">TEST CONNECTION</div>', unsafe_allow_html=True)
        test_key = st.text_input(
            "Paste key to test", type="password", key="test_key_input",
            placeholder="sk-...", label_visibility="collapsed",
        )
        if st.button("▶  TEST CONNECTION", use_container_width=True):
            if not test_key:
                st.warning("Paste a key above first.")
            else:
                with st.spinner("Connecting..."):
                    ok, msg = test_api_key(
                        test_key.strip(),
                        cfg.get("base_url", DEEPSEEK_URL) if cfg else DEEPSEEK_URL,
                    )
                (st.success if ok else st.error)(msg)

    # ══════════════════════════════════════════════════════════════
    # SECTION: USAGE ANALYTICS
    # ══════════════════════════════════════════════════════════════
    elif section == "📊  USAGE":
        rows = db_rows("SELECT * FROM ai_usage_log ORDER BY created_at DESC LIMIT 100")
        if not rows:
            st.info("No AI usage yet. Run an analysis from ⬡ AI ASSISTANT.")
        else:
            df_u = pd.DataFrame(rows)
            df_u["created_at"] = pd.to_datetime(df_u["created_at"])

            total_cost   = df_u[df_u["success"] == 1]["cost_usd"].sum()
            total_calls  = len(df_u)
            success_rate = df_u["success"].mean() * 100

            c1, c2, c3 = st.columns(3)
            c1.metric("TOTAL COST",   f"${total_cost:.4f}")
            c2.metric("TOTAL CALLS",  total_calls)
            c3.metric("SUCCESS RATE", f"{success_rate:.1f}%")
            st.markdown("")

            by_feat = (df_u[df_u["success"] == 1]
                       .groupby("feature")["cost_usd"].sum().reset_index())
            if not by_feat.empty:
                fig = px.pie(
                    by_feat, values="cost_usd", names="feature",
                    title="COST BY FEATURE", hole=0.5,
                    color_discrete_sequence=[
                        "#0f62fe","#42be65","#ff832b","#f1c21b","#da1e28","#8a3ffc"],
                )
                fig.update_layout(**plotly_theme())
                st.plotly_chart(fig, use_container_width=True)

            daily = (df_u[df_u["success"] == 1]
                     .groupby(df_u["created_at"].dt.date)["cost_usd"].sum()
                     .reset_index())
            if not daily.empty:
                fig2 = px.bar(daily, x="created_at", y="cost_usd",
                              title="DAILY AI COST",
                              color_discrete_sequence=["#0f62fe"])
                fig2.update_layout(**plotly_theme(), xaxis_title="", yaxis_title="USD")
                st.plotly_chart(fig2, use_container_width=True)

            df_display = df_u[["created_at","feature","cost_usd","success"]].copy()
            df_display["success"] = df_display["success"].map({1: "✓", 0: "✗"})
            df_display["cost_usd"] = df_display["cost_usd"].apply(lambda x: f"${x:.6f}")
            df_display.columns = ["When", "Feature", "Cost", "OK"]
            st.dataframe(df_display.head(30), use_container_width=True, hide_index=True)

    # ══════════════════════════════════════════════════════════════
    # SECTION: DATA MANAGEMENT
    # ══════════════════════════════════════════════════════════════
    else:
        pid       = project["id"]
        team_d    = get_team(pid)
        sprints_d = get_sprints(pid)
        risks_d   = get_risks(pid)
        entries_d = get_budget_entries(pid)

        st.markdown('<div class="mono-label">EXPORT DATA</div>', unsafe_allow_html=True)
        st.markdown("")

        if team_d:
            st.download_button("↓  TEAM CSV", df_to_csv(pd.DataFrame(team_d)),
                               "team.csv", "text/csv", use_container_width=True)
        if sprints_d:
            df_s = pd.DataFrame([
                {k: v for k, v in s.items() if k not in ("blockers","retro_notes")}
                for s in sprints_d
            ])
            st.download_button("↓  SPRINTS CSV", df_to_csv(df_s),
                               "sprints.csv", "text/csv", use_container_width=True)
        if risks_d:
            st.download_button("↓  RISKS CSV", df_to_csv(pd.DataFrame(risks_d)),
                               "risks.csv", "text/csv", use_container_width=True)
        if entries_d:
            st.download_button("↓  BUDGET CSV", df_to_csv(pd.DataFrame(entries_d)),
                               "budget.csv", "text/csv", use_container_width=True)
        if not any([team_d, sprints_d, risks_d, entries_d]):
            st.info("No data to export yet.")

        st.markdown("---")
        st.markdown('<div class="mono-label" style="color:#da1e28">DANGER ZONE</div>',
                    unsafe_allow_html=True)
        with st.expander("⚠  DELETE PROJECT"):
            st.error(
                f"Permanently deletes ALL data for **{project['name']}** "
                "including team, sprints, risks and budget. Cannot be undone."
            )
            confirm = st.text_input("Type project name to confirm:", key="delete_confirm")
            if st.button("DELETE PROJECT", use_container_width=True):
                if confirm == project["name"]:
                    db_exec("DELETE FROM projects WHERE id=?", (pid,))
                    st.success("Deleted. Reloading...")
                    st.rerun()
                else:
                    st.error("Name doesn't match — try again.")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════
# PAGE: AI ASSISTANT
# ═════════════════════════════════════════════════════════════════════════════
def page_ai_assistant(project, projects):
    pid = project["id"]
    section_header("AI ASSISTANT", f"All AI features · {project['name']}")

    # ── Data ──────────────────────────────────────────────────
    cfg          = get_ai_config()
    ai_ready     = bool(cfg and cfg.get("api_key"))
    team         = get_team(pid)
    sprints      = get_sprints(pid)
    risks        = get_risks(pid)
    entries      = get_budget_entries(pid)
    avg_morale   = sum(m["morale"]   for m in team)/len(team) if team else 75.0
    avg_workload = sum(m["workload"] for m in team)/len(team) if team else 70.0
    completed_sp = [s for s in sprints if s["status"]=="completed"]
    avg_velocity = sum(s["completed_points"] for s in completed_sp)/len(completed_sp) if completed_sp else 30.0
    open_risks   = [r for r in risks if r["status"]=="open"]
    total_expense= sum(e["amount"] for e in entries if e["entry_type"]=="expense")
    remaining_pts= project.get("total_points",0) - project.get("completed_points",0)
    p_ctx        = {k: project[k] for k in ("name","status","team_size","velocity","budget")}
    velocities   = [s["completed_points"] for s in completed_sp]

    # ── Setup banner ──────────────────────────────────────────
    if not ai_ready:
        st.warning("⚡ AI not configured. Go to **SETTINGS → 🔑 API CONFIG** to add your DeepSeek key.")
        if st.button("→ GO TO SETTINGS", key="ai_goto_settings", use_container_width=True):
            st.session_state["sidebar_nav"] = "SETTINGS"
            st.rerun()
        st.markdown("---")

    # ── Card helper ───────────────────────────────────────────
    def card(icon, title, desc):
        st.markdown(
            f'''<div style="background:#1e2a3a;border:1px solid #0f62fe;border-top:3px solid #0f62fe;
                         padding:0.75rem 1rem 0.4rem 1rem">
                <span style="font-size:1.1rem">{icon}</span>
                <strong style="font-family:IBM Plex Mono,monospace;font-size:0.88rem;
                               color:#f4f4f4;margin-left:0.4rem">{title}</strong>
                <div style="font-family:IBM Plex Sans,monospace;font-size:0.77rem;
                            color:#a8a8a8;margin-top:0.3rem">{desc}</div>
            </div>''', unsafe_allow_html=True)

    # ══════════════════════════════════════════
    # 1. PROJECT HEALTH ANALYSIS
    # ══════════════════════════════════════════
    card("🧠", "PROJECT HEALTH ANALYSIS",
         "Score your project 1–10. Top 3 concerns + one action for this week.")
    with st.container(border=True):
        st.caption(f"Morale {avg_morale:.0f}/100  ·  Workload {avg_workload:.0f}%  ·  "
                   f"{len(open_risks)} open risks  ·  "
                   f"Budget {total_expense/max(project['budget'],1)*100:.0f}% used")
        run_health = st.button("▶  RUN HEALTH ANALYSIS", key="btn_health",
                               use_container_width=True, disabled=not ai_ready)
    if run_health:
        with st.spinner("Analysing project health..."):
            resp = call_ai(
                f"Project health for '{project['name']}'\n"
                f"Team: {len(team)} people, morale {avg_morale:.0f}/100, workload {avg_workload:.0f}%\n"
                f"Open risks: {len(open_risks)}, velocity {avg_velocity:.1f} pts/sprint\n"
                f"Budget: {total_expense/max(project['budget'],1)*100:.1f}% used\n\n"
                "Give:\n1. Health score 1-10 with rationale\n"
                "2. Top 3 concerns in priority order\n"
                "3. One immediate action the PM should take this week",
                "therapy", p_ctx)
        render_ai_result(resp, "🧠 PROJECT HEALTH ANALYSIS")

    st.markdown("---")

    # ══════════════════════════════════════════
    # 2. WHAT-IF SIMULATOR
    # ══════════════════════════════════════════
    card("🎲", "WHAT-IF SIMULATOR",
         "Model the impact of changes on schedule, cost and risk before committing.")
    with st.container(border=True):
        st.selectbox("Scenario", [
            "Add 1 senior developer",
            "Add 2 senior developers",
            "Remove 1 team member (attrition)",
            "Reduce scope by 20%",
            "Reduce scope by 30%",
            "Extend deadline by 4 weeks",
            "Cut budget by 15%",
            "Add contractor for 6 weeks",
            "Custom…",
        ], key="sim_scenario")
        if st.session_state.get("sim_scenario") == "Custom…":
            st.text_input("Describe your scenario",
                          placeholder="e.g. Swap frontend dev for a designer",
                          key="sim_custom")
        run_sim = st.button("▶  RUN SIMULATION", key="btn_sim",
                            use_container_width=True, disabled=not ai_ready)
    if run_sim:
        scenario = (st.session_state.get("sim_custom", "")
                    if st.session_state.get("sim_scenario") == "Custom…"
                    else st.session_state.get("sim_scenario", "Add 1 senior developer"))
        with st.spinner(f"Simulating: {scenario}..."):
            resp = call_ai(
                f"What-if simulation for '{project['name']}'\n"
                f"Team={len(team)}, velocity={avg_velocity:.1f} pts/sprint, "
                f"remaining={remaining_pts} pts, budget left=${project['budget']-total_expense:,.0f}\n"
                f"Scenario: {scenario}\n\n"
                "Give:\n1. Predicted outcome with probability (%)\n"
                "2. Impact on delivery date (weeks earlier/later)\n"
                "3. Impact on budget ($)\n"
                "4. Top risk introduced by this change\n"
                "5. Recommendation: proceed / caution / avoid",
                "simulator", p_ctx)
        render_ai_result(resp, f"🎲 SIMULATION: {scenario}")

    st.markdown("---")

    # ══════════════════════════════════════════
    # 3. SPRINT RETROSPECTIVE
    # ══════════════════════════════════════════
    card("🔄", "SPRINT RETROSPECTIVE",
         "AI-facilitated retro: went well, improve, action items, pattern insight.")
    completed_names = [f"Sprint {s['number']}: {s.get('goal','')[:45]}" for s in completed_sp]
    with st.container(border=True):
        if completed_names:
            st.selectbox("Select sprint", completed_names, key="retro_sprint")
        else:
            st.caption("No completed sprints yet.")
        run_retro = st.button("▶  RUN RETROSPECTIVE", key="btn_retro",
                              use_container_width=True,
                              disabled=(not ai_ready or not completed_names))
    if run_retro and completed_sp:
        retro_key = st.session_state.get("retro_sprint", completed_names[0] if completed_names else "")
        try:
            sel_num = int(retro_key.split(":")[0].replace("Sprint","").strip())
            sprint  = next((s for s in completed_sp if s["number"]==sel_num), completed_sp[-1])
        except Exception:
            sprint  = completed_sp[-1]
        notes = sprint.get("retro_notes", {})
        with st.spinner("Generating retrospective..."):
            resp = call_ai(
                f"Sprint retrospective for Sprint {sprint['number']} of '{project['name']}'\n"
                f"Goal: {sprint.get('goal','not set')}\n"
                f"Velocity: {sprint['completed_points']}/{sprint['planned_points']} pts "
                f"({sprint['completion_pct']:.0f}% complete)\n"
                f"Blockers: {', '.join(sprint['blockers']) or 'none'}\n"
                f"Went well: {notes.get('went_well','none')}\n"
                f"To improve: {notes.get('improve','none')}\n\n"
                "Structure as:\n**WENT WELL** (2-3 bullets)\n"
                "**TO IMPROVE** (2-3 bullets)\n"
                "**ACTION ITEMS** (3 specific tasks)\n"
                "**PATTERN** (one insight about project trend)",
                "retro", {"sprint": sprint["number"], "project": project["name"]})
        render_ai_result(resp, f"🔄 RETROSPECTIVE — SPRINT {sprint['number']}")

    st.markdown("---")

    # ══════════════════════════════════════════
    # 4. RISK ANALYSIS
    # ══════════════════════════════════════════
    card("⚠️", "RISK ANALYSIS",
         "Prioritised risk report with mitigations tailored to your chosen focus.")
    with st.container(border=True):
        if not risks:
            st.caption("No risks yet — add some in the Risk Register page.")
        st.selectbox("Focus area", [
            "Full risk register review",
            "Critical risks only (score ≥ 12)",
            "People & team risks",
            "Technical risks",
            "Financial risks",
            "Next sprint risk forecast",
        ], key="risk_focus")
        run_risk_ai = st.button("▶  RUN RISK ANALYSIS", key="btn_risk",
                                use_container_width=True,
                                disabled=(not ai_ready or not risks))
    if run_risk_ai and risks:
        risk_focus = st.session_state.get("risk_focus", "Full risk register review")
        all_rd = [{
            "title": r["title"], "category": r["category"],
            "probability": r["probability"], "impact": r["impact"],
            "score": r["probability"]*r["impact"], "status": r["status"],
            "owner": r.get("owner","?"), "mitigation": r.get("mitigation","none"),
        } for r in risks]
        CAT = {"People & team risks":["people"], "Technical risks":["technical"], "Financial risks":["financial"]}
        if risk_focus == "Critical risks only (score ≥ 12)":
            filtered = [r for r in all_rd if r["score"] >= 12]
            instr = "Critical risks only. For each: action required, owner, escalation needed?"
        elif risk_focus in CAT:
            filtered = [r for r in all_rd if r["category"] in CAT[risk_focus]]
            instr = f"{risk_focus} only. Assess landscape, top risk, gaps, actions this sprint."
        elif risk_focus == "Next sprint risk forecast":
            filtered = [r for r in all_rd if r["status"]=="open"]
            instr = "Which 2 risks will materialise next sprint? Early warnings + pre-emptive actions."
        else:
            filtered = all_rd
            instr = "Full review. Overall posture (R/A/G), top 3 actions, systemic pattern, underestimated risk."
        if not filtered:
            filtered = all_rd
        risk_txt = "\n".join(
            f"- [{r['category'].upper()}] {r['title']} P={r['probability']} I={r['impact']} "
            f"Score={r['score']} {r['status'].upper()} | {r['mitigation']}"
            for r in sorted(filtered, key=lambda x: -x["score"]))
        with st.spinner(f"Analysing: {risk_focus}..."):
            resp = call_ai(
                f"Risk analysis for '{project['name']}' — {risk_focus}\n"
                f"Register: {len(risks)} total, {len(open_risks)} open\n"
                f"Analysing {len(filtered)} risks:\n{risk_txt}\n\n{instr}",
                "risk", {"project": project["name"], "focus": risk_focus})
        render_ai_result(resp, f"⚠️ RISK: {risk_focus}")

    st.markdown("---")

    # ══════════════════════════════════════════
    # 5. DELIVERY FORECAST
    # ══════════════════════════════════════════
    card("📅", "DELIVERY FORECAST",
         "Confidence-interval delivery dates based on your actual sprint velocity history.")
    with st.container(border=True):
        st.caption(f"Remaining: {remaining_pts} pts  ·  "
                   f"Avg velocity: {avg_velocity:.1f} pts/sprint  ·  "
                   f"{len(completed_sp)} sprints done")
        st.selectbox("Scenario", [
            "Current pace (no changes)",
            "Add 1 developer next sprint",
            "Reduce scope by 20%",
            "Team velocity improves 10% (learning curve)",
            "Velocity drops 15% (team fatigue)",
        ], key="forecast_scenario")
        run_forecast = st.button("▶  RUN FORECAST", key="btn_forecast",
                                 use_container_width=True, disabled=not ai_ready)
    if run_forecast:
        fc_scenario = st.session_state.get("forecast_scenario", "Current pace (no changes)")
        with st.spinner("Calculating delivery forecast..."):
            resp = call_ai(
                f"Delivery forecast for '{project['name']}'\n"
                f"Remaining: {remaining_pts} pts, velocity history: {velocities}\n"
                f"Avg: {avg_velocity:.1f} pts/sprint (2-week sprints)\n"
                f"Target end date: {project.get('end_date','not set')}\n"
                f"Budget remaining: ${project['budget']-total_expense:,.0f}\n"
                f"Scenario: {fc_scenario}\n\n"
                "Give:\n1. Delivery date best/likely/worst case (80% CI)\n"
                "2. Probability of hitting original target (%)\n"
                "3. Sprints remaining\n"
                "4. Budget at completion\n"
                "5. Top factor that would change this forecast",
                "forecast", p_ctx)
        render_ai_result(resp, f"📅 FORECAST: {fc_scenario}")

    st.markdown("---")

    # ══════════════════════════════════════════
    # 6. CROSS-PROJECT INSIGHTS
    # ══════════════════════════════════════════
    card("🔗", "CROSS-PROJECT INSIGHTS",
         "Compare two projects to surface lessons, patterns and resource opportunities.")
    all_projects = get_projects()
    has_multiple = len(all_projects) >= 2
    with st.container(border=True):
        if not has_multiple:
            st.caption("Create a second project to enable comparison.")
        else:
            other_projs = [p for p in all_projects if p["id"] != pid]
            st.selectbox("Compare with", [p["name"] for p in other_projs], key="compare_proj")
            st.selectbox("Focus", [
                "Overall comparison",
                "Velocity & delivery performance",
                "Team & resource patterns",
                "Risk patterns",
                "Budget efficiency",
            ], key="insights_focus")
        run_insights = st.button("▶  RUN COMPARISON", key="btn_insights",
                                 use_container_width=True,
                                 disabled=(not ai_ready or not has_multiple))
    if run_insights and has_multiple:
        other_projs   = [p for p in all_projects if p["id"] != pid]
        compare_to    = st.session_state.get("compare_proj", other_projs[0]["name"])
        focus         = st.session_state.get("insights_focus", "Overall comparison")
        proj_b        = next((p for p in all_projects if p["name"]==compare_to), other_projs[0])
        team_b        = get_team(proj_b["id"])
        sprints_b     = get_sprints(proj_b["id"])
        completed_b   = [s for s in sprints_b if s["status"]=="completed"]
        vel_b         = sum(s["completed_points"] for s in completed_b)/len(completed_b) if completed_b else 0
        risks_b_open  = len([r for r in get_risks(proj_b["id"]) if r["status"]=="open"])
        with st.spinner("Comparing projects..."):
            resp = call_ai(
                f"Cross-project comparison. Focus: {focus}\n\n"
                f"Project A '{project['name']}': team={len(team)}, "
                f"velocity={avg_velocity:.1f} pts/sprint, "
                f"budget used={total_expense/max(project['budget'],1)*100:.0f}%, "
                f"open risks={len(open_risks)}\n"
                f"Project B '{proj_b['name']}': team={len(team_b)}, "
                f"velocity={vel_b:.1f} pts/sprint, "
                f"budget=${proj_b['budget']:,.0f}, open risks={risks_b_open}\n\n"
                "Give:\n1. Which project is performing better and why\n"
                "2. Most significant difference\n"
                "3. Lesson the weaker project should adopt\n"
                "4. Resource or process that could be shared",
                "insights")
        render_ai_result(resp, f"🔗 {project['name']} vs {compare_to}")


# ═════════════════════════════════════════════════════════════════════════════
# NAV BAR — always-visible compact row of st.buttons, works on all screens
# ═════════════════════════════════════════════════════════════════════════════
def render_nav_bar(current_page: str):
    NAV = [
        ("🏠", "DASHBOARD"),
        ("🤖", "⬡ AI ASSISTANT"),
        ("🏃", "SPRINT BOARD"),
        ("⚠️", "RISK REGISTER"),
        ("💰", "BUDGET"),
        ("👥", "TEAM"),
        ("📁", "PROJECTS"),
        ("⚙️", "SETTINGS"),
    ]
    cols = st.columns(len(NAV))
    for col, (icon, page_key) in zip(cols, NAV):
        is_active = current_page == page_key
        # Show active page with filled background via type
        if col.button(
            icon,
            key=f"nav_{page_key}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
            help=page_key,
        ):
            st.session_state["current_page"] = page_key
            st.rerun()


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

        NAV_PAGES = [
            "DASHBOARD",
            "⬡ AI ASSISTANT",
            "SPRINT BOARD",
            "RISK REGISTER",
            "BUDGET",
            "TEAM",
            "PROJECTS",
            "SETTINGS",
        ]

        # Persist page selection across sidebar collapse/expand on mobile.
        # st.radio resets to index 0 when the sidebar is toggled.
        # We store the real selection in session_state["current_page"] and
        # sync the radio to it — so collapsing the sidebar never loses your page.
        if "current_page" not in st.session_state:
            st.session_state["current_page"] = "DASHBOARD"

        # Another part of the app may have set sidebar_nav to request a page jump
        if "sidebar_nav" in st.session_state and st.session_state["sidebar_nav"] in NAV_PAGES:
            st.session_state["current_page"] = st.session_state["sidebar_nav"]
            del st.session_state["sidebar_nav"]

        current_idx = NAV_PAGES.index(st.session_state["current_page"])

        selected = st.radio(
            "",
            NAV_PAGES,
            index=current_idx,
            label_visibility="collapsed",
            key="nav_radio",
        )

        # Update persistent state when user changes selection
        if selected != st.session_state["current_page"]:
            st.session_state["current_page"] = selected

        page = st.session_state["current_page"]

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
    # ── Mobile nav bar — shown at top on mobile, hidden on desktop ──
    render_nav_bar(page)
    st.markdown("---")

    pages[page](project, projects)


if __name__ == "__main__":
    main()
