"""应用状态(LLM 配置等)—— SQLite(WAL)。机密不入库 git(data/app.db 已 gitignore)。

LLM key 通过 web 表单传入后存这里;insight 的 OpenAICompatLLM 从这里读,端到端跑 DD 报告。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path("data/app.db")


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS app_config (key TEXT PRIMARY KEY, value TEXT)")
    return c


def get_llm_config() -> dict:
    """返回 {base_url, model, api_key, temperature} 或 {}(未配)。"""
    with _conn() as c:
        row = c.execute("SELECT value FROM app_config WHERE key='llm'").fetchone()
    return json.loads(row[0]) if row else {}


def set_llm_config(base_url: str, model: str, api_key: str, temperature: float = 0.3) -> dict:
    cfg = {"base_url": base_url.strip(), "model": model.strip(),
           "api_key": api_key.strip(), "temperature": temperature}
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO app_config VALUES ('llm', ?)", [json.dumps(cfg)])
    return cfg


def llm_is_configured() -> bool:
    cfg = get_llm_config()
    return bool(cfg.get("api_key") and cfg.get("model"))
