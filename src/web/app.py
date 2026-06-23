"""MonkeyBench Web App —— 仪表盘(数据资产 + LLM 状态)、LLM 设置(传 key)、连接测试。

HTMX + Tailwind(CDN),服务端渲染。LLM key 经表单传入 → SQLite(config.py)。
经 tailscale 内网访问;app 层暂无鉴权(靠 tailscale 网络隔离),公网部署前需补 auth。
"""
from __future__ import annotations

import duckdb
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import get_llm_config, llm_is_configured, set_llm_config

app = FastAPI(title="MonkeyBench")
DUCKDB = "data/cache/market.duckdb"
_LABELS = {"daily_bar": "日线", "daily_basic": "估值", "fina_indicator": "财务指标",
           "stk_factor_pro": "技术因子(261列)", "stk_limit": "涨跌停",
           "sw_daily": "行业日线", "index_member": "行业成分"}


def _data_stats() -> dict:
    try:
        c = duckdb.connect(DUCKDB, read_only=True)
        out = {}
        for t in _LABELS:
            try:
                out[t] = c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            except Exception:
                out[t] = None
        c.close()
        return out
    except Exception as e:
        return {"_error": str(e)[:90]}


def _page(body: str, active: str = "") -> str:
    def link(href, label, key):
        cls = "text-indigo-600 font-medium" if key == active else "text-gray-500 hover:text-gray-800"
        return f'<a href="{href}" class="{cls}">{label}</a>'
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>MonkeyBench</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
<style>.report h1{{font-size:1.5rem;font-weight:600;margin:.8rem 0}}.report h2{{font-size:1.15rem;font-weight:600;margin:1.2rem 0 .5rem;border-bottom:1px solid #eee;padding-bottom:.2rem}}.report table{{border-collapse:collapse;margin:.6rem 0;font-size:.9rem}}.report td,.report th{{border:1px solid #ddd;padding:4px 10px}}.report svg{{margin:1rem 0;max-width:100%;height:auto}}.report blockquote{{color:#666;border-left:3px solid #ddd;padding-left:1rem;margin:.6rem 0}}.htmx-indicator{{opacity:0;transition:opacity .2s}}.htmx-request .htmx-indicator{{opacity:1}}</style></head>
<body class="bg-gray-50 text-gray-900 min-h-screen">
<nav class="bg-white border-b border-gray-200"><div class="max-w-4xl mx-auto px-4 h-14 flex items-center gap-6">
  <span class="font-semibold text-lg">🐒 MonkeyBench</span>
  {link('/', '仪表盘', 'home')}{link('/analyze', '公司分析', 'analyze')}{link('/settings', 'LLM 设置', 'settings')}
</div></nav>
<main class="max-w-4xl mx-auto px-4 py-8">{body}</main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    stats = _data_stats()
    cfg = get_llm_config()
    if "_error" in stats:
        cards = f'<div class="text-red-600 bg-red-50 rounded-lg p-4">数据库读取失败:{stats["_error"]}<br><span class="text-sm text-gray-500">(竞技场/回测可能正占用 DuckDB 写锁,稍后刷新)</span></div>'
    else:
        cells = "".join(
            f'<div class="bg-white rounded-lg border border-gray-200 p-4">'
            f'<div class="text-sm text-gray-500">{_LABELS[k]}</div>'
            f'<div class="text-2xl font-semibold">{format(v, ",") if v is not None else "—"}</div></div>'
            for k, v in stats.items())
        cards = f'<div class="grid grid-cols-2 sm:grid-cols-3 gap-3">{cells}</div>'
    if llm_is_configured():
        badge = f'<span class="text-green-700 bg-green-50 px-3 py-1 rounded-full text-sm">已配置 · {cfg.get("model")}</span>'
    else:
        badge = '<span class="text-amber-700 bg-amber-50 px-3 py-1 rounded-full text-sm">未配置 LLM key</span>'
    body = f"""<h1 class="text-2xl font-semibold mb-1">仪表盘</h1>
<p class="text-gray-500 mb-6">数据资产与运行状态</p>
<div class="mb-8 flex items-center gap-3 flex-wrap"><span class="text-gray-600">LLM 洞见:</span>{badge}
  <a href="/settings" class="text-indigo-600 text-sm hover:underline">去设置 →</a></div>
<h2 class="text-lg font-medium mb-3">数据资产</h2>{cards}"""
    return _page(body, "home")


@app.get("/settings", response_class=HTMLResponse)
def settings_form():
    cfg = get_llm_config()
    has_key = bool(cfg.get("api_key"))
    key_note = '<span class="text-green-600 text-xs">已设置,留空则保留原 key</span>' if has_key else ''
    key_ph = "••••••••(已保存)" if has_key else "sk-..."
    body = f"""<h1 class="text-2xl font-semibold mb-1">LLM 设置</h1>
<p class="text-gray-500 mb-6">配置 OpenAI 兼容 API(DeepSeek V4 / GLM / MiniMax 等),用于 DD 报告生成。
  key 存本机 SQLite,不入库 git、不外传。</p>
<form method="post" action="/settings" class="space-y-4 max-w-lg">
  <div><label class="block text-sm font-medium mb-1">Base URL</label>
    <input name="base_url" value="{cfg.get('base_url','')}" placeholder="https://api.deepseek.com/v1"
      class="w-full border border-gray-300 rounded-lg px-3 py-2" required></div>
  <div><label class="block text-sm font-medium mb-1">模型</label>
    <input name="model" value="{cfg.get('model','')}" placeholder="deepseek-chat"
      class="w-full border border-gray-300 rounded-lg px-3 py-2" required></div>
  <div><label class="block text-sm font-medium mb-1">API Key {key_note}</label>
    <input name="api_key" type="password" placeholder="{key_ph}"
      class="w-full border border-gray-300 rounded-lg px-3 py-2"></div>
  <div><label class="block text-sm font-medium mb-1">温度</label>
    <input name="temperature" type="number" step="0.1" min="0" max="2" value="{cfg.get('temperature',0.3)}"
      class="w-32 border border-gray-300 rounded-lg px-3 py-2"></div>
  <div class="flex items-center gap-3 pt-2">
    <button type="submit" class="bg-indigo-600 text-white px-5 py-2 rounded-lg hover:bg-indigo-700">保存</button>
    <button type="button" class="border border-gray-300 px-5 py-2 rounded-lg hover:bg-gray-50"
      hx-post="/settings/test" hx-target="#test-result" hx-swap="innerHTML"
      hx-indicator="#test-spin">测试连接</button>
    <span id="test-spin" class="htmx-indicator text-gray-400 text-sm">测试中…</span>
    <span id="test-result"></span>
  </div>
</form>"""
    return _page(body, "settings")


@app.post("/settings")
def settings_save(base_url: str = Form(...), model: str = Form(...),
                  api_key: str = Form(""), temperature: float = Form(0.3)):
    cur = get_llm_config()
    key = api_key.strip() or cur.get("api_key", "")    # 留空 → 保留旧 key
    set_llm_config(base_url, model, key, temperature)
    return RedirectResponse("/?saved=1", status_code=303)


@app.post("/settings/test", response_class=HTMLResponse)
def settings_test():
    cfg = get_llm_config()
    if not cfg.get("api_key"):
        return '<span class="text-amber-600 text-sm">请先填 key 并保存</span>'
    try:
        from openai import OpenAI
        client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=20)
        r = client.chat.completions.create(
            model=cfg["model"], messages=[{"role": "user", "content": "ping, reply OK"}], max_tokens=5)
        return f'<span class="text-green-600 text-sm">✓ 连接成功:{(r.choices[0].message.content or "")[:20]}</span>'
    except Exception as e:
        return f'<span class="text-red-600 text-sm">✗ {str(e)[:70]}</span>'


@app.get("/analyze", response_class=HTMLResponse)
def analyze_form():
    body = """<h1 class="text-2xl font-semibold mb-1">公司多元分析</h1>
<p class="text-gray-500 mb-6">拉本地全量数据 → 综合质量分 + 财务画像 + 自定义对标 → DD 报告。
  配了 LLM key 走分析长报告,否则出确定性模板版。</p>
<form hx-post="/analyze" hx-target="#report" hx-swap="innerHTML" hx-indicator="#spin" class="space-y-3 max-w-lg mb-6">
  <div><label class="block text-sm font-medium mb-1">股票代码</label>
    <input name="ts_code" placeholder="688205.SH" required
      class="w-full border border-gray-300 rounded-lg px-3 py-2"></div>
  <div><label class="block text-sm font-medium mb-1">对标(可选,逗号分隔)</label>
    <input name="peers" placeholder="300308.SZ,300502.SZ,300394.SZ"
      class="w-full border border-gray-300 rounded-lg px-3 py-2"></div>
  <div class="flex items-center gap-3">
    <button class="bg-indigo-600 text-white px-5 py-2 rounded-lg hover:bg-indigo-700">生成报告</button>
    <span id="spin" class="htmx-indicator text-gray-400 text-sm">生成中…(LLM 版需 30–60 秒)</span>
  </div>
</form>
<div id="report"></div>"""
    return _page(body, "analyze")


@app.post("/analyze", response_class=HTMLResponse)
def analyze_run(ts_code: str = Form(...), peers: str = Form("")):
    from data.cache import MarketCache
    ts_code = ts_code.strip().upper()
    peer_list = [p.strip().upper() for p in peers.split(",") if p.strip()]
    cache = MarketCache(read_only=True)
    try:
        cfg = get_llm_config()
        if cfg.get("api_key"):
            from insight.agent import OpenAICompatLLM
            from insight.report_agent import company_dd_report
            llm = OpenAICompatLLM(cfg["model"], cfg["base_url"], cfg["api_key"], cfg.get("temperature", 0.3))
            md = company_dd_report(cache, llm, ts_code, peer_list or None)
            engine = f"LLM · {cfg['model']}"
        else:
            from insight.report_agent import dd_report_from_data
            md = dd_report_from_data(cache, ts_code, peer_list or None)
            engine = "确定性模板(未配 LLM key)"
    except Exception as e:
        return f'<div class="text-red-600 bg-red-50 rounded-lg p-4">生成失败:{str(e)[:200]}</div>'
    finally:
        cache.close()
    import markdown as md_lib
    html = md_lib.markdown(md, extensions=["tables"])
    return (f'<div class="text-xs text-gray-400 mb-2">引擎:{engine}</div>'
            f'<div class="report bg-white border border-gray-200 rounded-lg p-6">{html}</div>')


@app.get("/health")
def health():
    return {"ok": True, "llm": llm_is_configured()}
