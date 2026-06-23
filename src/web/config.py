"""应用状态(LLM 配置等)—— SQLite(WAL)。机密不入库 git(data/app.db 已 gitignore)。

LLM 配置支持**多模型**(如 deepseek-v4-pro 强 / deepseek-v4-flash 轻量,逗号分隔)+ **思考模式**
开关(DeepSeek 思考模式支持工具调用,但不支持 temperature,改用 reasoning_effort)。
key 通过 web 表单传入,insight 的 OpenAICompatLLM 从这里读。
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
    """返回 {base_url, models:[...], api_key, temperature, thinking, reasoning_effort} 或 {}。"""
    with _conn() as c:
        row = c.execute("SELECT value FROM app_config WHERE key='llm'").fetchone()
    cfg = json.loads(row[0]) if row else {}
    if cfg.get("model") and not cfg.get("models"):     # 兼容旧单模型字段
        cfg["models"] = [cfg["model"]]
    cfg.setdefault("models", [])
    cfg.setdefault("thinking", False)
    cfg.setdefault("reasoning_effort", "high")
    return cfg


def set_llm_config(base_url: str, models, api_key: str, temperature: float = 0.3,
                   thinking: bool = False, reasoning_effort: str = "high") -> dict:
    """models 可传 list 或逗号分隔字符串。"""
    if isinstance(models, str):
        models = [m.strip() for m in models.split(",") if m.strip()]
    cfg = {"base_url": base_url.strip(), "models": models, "api_key": api_key.strip(),
           "temperature": temperature, "thinking": bool(thinking),
           "reasoning_effort": reasoning_effort}
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO app_config VALUES ('llm', ?)", [json.dumps(cfg)])
    return cfg


def llm_is_configured() -> bool:
    cfg = get_llm_config()
    return bool(cfg.get("api_key") and cfg.get("models"))
