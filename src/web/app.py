"""MonkeyBench Web App —— 仪表盘(数据资产 + LLM 状态)、LLM 设置(传 key)、连接测试。

HTMX + Tailwind(CDN),服务端渲染。LLM key 经表单传入 → SQLite(config.py)。
经 tailscale 内网访问;app 层暂无鉴权(靠 tailscale 网络隔离),公网部署前需补 auth。
"""
from __future__ import annotations

import duckdb
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sse_starlette.sse import EventSourceResponse

from data.codes import to_ts_code

from .config import get_llm_config, llm_is_configured, set_llm_config

app = FastAPI(title="MonkeyBench")
JOBS: dict = {}   # 后台报告任务:job_id → {"events":[SSE事件dict], "done":bool}


@app.middleware("http")
async def _no_cache(request, call_next):
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"   # 防浏览器缓存旧页面/JS
    return resp
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
<style>.report{{line-height:1.78;color:#374151;font-size:15px}}.report h1{{font-size:1.6rem;font-weight:600;margin:.4rem 0 1.2rem;color:#111827}}.report h2{{font-size:1.2rem;font-weight:600;margin:2rem 0 .9rem;padding-bottom:.4rem;border-bottom:2px solid #6366f1;color:#111827}}.report p{{margin:.75rem 0}}.report strong{{color:#111827;font-weight:600}}.report ul,.report ol{{margin:.6rem 0;padding-left:1.4rem}}.report li{{margin:.3rem 0}}.report table{{border-collapse:collapse;margin:1rem 0;font-size:.88rem;width:100%}}.report th{{background:#f3f4f6;font-weight:600;text-align:left;color:#374151}}.report td,.report th{{border:1px solid #e5e7eb;padding:7px 12px}}.report tr:nth-child(even){{background:#fafafa}}.report .chart{{margin:1.8rem 0;text-align:center}}.report svg{{max-width:100%;height:auto}}.report blockquote{{color:#6b7280;border-left:3px solid #6366f1;background:#f8f8fc;padding:.7rem 1rem;margin:1.2rem 0;border-radius:0 6px 6px 0}}.htmx-indicator{{opacity:0;transition:opacity .2s}}.htmx-request .htmx-indicator{{opacity:1}}</style></head>
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
    thinking_checked = "checked" if cfg.get("thinking") else ""
    eff = cfg.get("reasoning_effort", "high")
    high_sel, max_sel = ("selected" if eff != "max" else ""), ("selected" if eff == "max" else "")
    models_str = ",".join(cfg.get("models", []))
    body = f"""<h1 class="text-2xl font-semibold mb-1">LLM 设置</h1>
<p class="text-gray-500 mb-6">配置 OpenAI 兼容 API(DeepSeek V4 / GLM / MiniMax 等),用于 DD 报告生成。
  key 存本机 SQLite,不入库 git、不外传。</p>
<form method="post" action="/settings" class="space-y-4 max-w-lg">
  <div><label class="block text-sm font-medium mb-1">Base URL</label>
    <input name="base_url" value="{cfg.get('base_url','')}" placeholder="https://api.deepseek.com/v1"
      class="w-full border border-gray-300 rounded-lg px-3 py-2" required></div>
  <div><label class="block text-sm font-medium mb-1">模型(逗号分隔多个,如 pro + 轻量)</label>
    <input name="models" value="{models_str}" placeholder="deepseek-v4-pro,deepseek-v4-flash"
      class="w-full border border-gray-300 rounded-lg px-3 py-2" required>
    <p class="text-xs text-gray-400 mt-1">分析时可选用哪个;第一个为默认。</p></div>
  <div><label class="block text-sm font-medium mb-1">API Key {key_note}</label>
    <input name="api_key" type="password" placeholder="{key_ph}"
      class="w-full border border-gray-300 rounded-lg px-3 py-2"></div>
  <div><label class="block text-sm font-medium mb-1">温度(非思考模式用)</label>
    <input name="temperature" type="number" step="0.1" min="0" max="2" value="{cfg.get('temperature',0.3)}"
      class="w-32 border border-gray-300 rounded-lg px-3 py-2"></div>
  <div class="flex items-center gap-4 flex-wrap">
    <label class="flex items-center gap-2 text-sm"><input type="checkbox" name="thinking" {thinking_checked}> 默认开启思考模式</label>
    <label class="text-sm">思考强度
      <select name="reasoning_effort" class="border border-gray-300 rounded-lg px-2 py-1 ml-1">
        <option value="high" {high_sel}>high</option><option value="max" {max_sel}>max</option></select></label>
  </div>
  <p class="text-xs text-gray-400">DeepSeek 思考模式支持工具调用,但不支持温度,改用强度控制。</p>
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
def settings_save(base_url: str = Form(...), models: str = Form(...),
                  api_key: str = Form(""), temperature: float = Form(0.3),
                  thinking: str = Form(""), reasoning_effort: str = Form("high")):
    cur = get_llm_config()
    key = api_key.strip() or cur.get("api_key", "")    # 留空 → 保留旧 key
    set_llm_config(base_url, models, key, temperature,
                   thinking=(thinking == "on"), reasoning_effort=reasoning_effort)
    return RedirectResponse("/?saved=1", status_code=303)


@app.post("/settings/test", response_class=HTMLResponse)
def settings_test():
    cfg = get_llm_config()
    if not cfg.get("api_key") or not cfg.get("models"):
        return '<span class="text-amber-600 text-sm">请先填模型和 key 并保存</span>'
    model = cfg["models"][0]                      # 用第一个模型测连通
    try:
        from openai import OpenAI
        client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=30)
        r = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "ping"}], max_tokens=64)
        txt = (r.choices[0].message.content or "").strip()[:20]
        return f'<span class="text-green-600 text-sm">✓ {model} 连接成功:{txt or "(空)"}</span>'
    except Exception as e:
        return f'<span class="text-red-600 text-sm">✗ {str(e)[:90]}</span>'


@app.get("/analyze", response_class=HTMLResponse)
def analyze_form():
    cfg = get_llm_config()
    models = cfg.get("models", [])
    if models:
        opts = "".join(f'<option value="{m}">{m}</option>' for m in models)
        tchk = "checked" if cfg.get("thinking") else ""
        model_row = (f'<div class="flex items-end gap-4 flex-wrap">'
                     f'<div><label class="block text-sm font-medium mb-1">模型</label>'
                     f'<select id="model" class="border border-gray-300 rounded-lg px-3 py-2">{opts}</select></div>'
                     f'<label class="flex items-center gap-2 text-sm pb-2"><input type="checkbox" id="thinking" {tchk}> 思考模式(更深·更慢)</label></div>')
    else:
        model_row = ('<p class="text-amber-600 text-sm bg-amber-50 rounded-lg p-3">未配 LLM key,'
                     '将出确定性模板版报告。<a href="/settings" class="underline">去设置 →</a></p>')
    body = f"""<h1 class="text-2xl font-semibold mb-1">公司多元分析</h1>
<p class="text-gray-500 mb-6">拉本地全量数据 → 综合质量分 + 财务画像 + 投入信号 + 自定义对标 → DD 报告。</p>
<form id="af" onsubmit="return startDD()" class="space-y-3 max-w-lg mb-6">
  <div><label class="block text-sm font-medium mb-1">股票代码</label>
    <input id="ts_code" placeholder="688205(带不带 .SH/.SZ 都行)" required
      class="w-full border border-gray-300 rounded-lg px-3 py-2"></div>
  <div><label class="block text-sm font-medium mb-1">对标(可选,逗号分隔)</label>
    <input id="peers" placeholder="300308.SZ,300502.SZ,300394.SZ"
      class="w-full border border-gray-300 rounded-lg px-3 py-2"></div>
  {model_row}
  <div class="flex items-center gap-3">
    <button id="gen" class="bg-indigo-600 text-white px-5 py-2 rounded-lg hover:bg-indigo-700">生成报告</button>
    <span id="status" class="text-gray-400 text-sm"></span>
  </div>
</form>
<div id="report"></div>
<script>
function cleanupES() {{ if (window._es) {{ try {{ window._es.close(); }} catch (e) {{}} window._es = null; }} }}
function attachHandlers(es) {{
  var status = document.getElementById('status'), report = document.getElementById('report');
  var gen = document.getElementById('gen');
  es.addEventListener('job', function(e) {{ window._jobId = e.data; connectJob(e.data); }});
  es.addEventListener('status', function(e) {{ status.textContent = e.data; }});
  es.addEventListener('progress', function(e) {{ status.textContent = '📊 ' + e.data; }});
  es.addEventListener('token', function(e) {{
    window._buf += e.data;
    var s = document.getElementById('stream');
    if (!s) {{ report.innerHTML = '<pre id="stream" style="white-space:pre-wrap;font-family:inherit;color:#444;font-size:14px"></pre>'; s = document.getElementById('stream'); }}
    s.textContent = window._buf;
  }});
  es.addEventListener('final', function(e) {{ report.innerHTML = e.data; status.textContent = '✓ 完成'; }});
  es.addEventListener('failed', function(e) {{ status.textContent = '✗ ' + e.data; window._jobDone = true; }});
  es.addEventListener('done', function(e) {{ cleanupES(); window._jobDone = true; gen.disabled = false; }});
  es.onerror = function() {{
    if (es.readyState === 2) {{
      window._es = null;
      if (!window._jobDone && window._jobId) {{
        status.textContent = '重连中…(后台任务不受影响)';
        setTimeout(function() {{ if (!window._jobDone && window._jobId) connectJob(window._jobId); }}, 1500);
      }}
    }}
  }};
}}
function startDD() {{
  var ts = document.getElementById('ts_code').value.trim();
  if (!ts) return false;
  var peers = document.getElementById('peers').value.trim();
  var mEl = document.getElementById('model'), tEl = document.getElementById('thinking');
  var model = mEl ? mEl.value : '', thinking = (tEl && tEl.checked) ? 'on' : '';
  cleanupES(); window._jobId = null; window._jobDone = false; window._buf = '';
  document.getElementById('gen').disabled = true;
  document.getElementById('status').textContent = '连接中…';
  document.getElementById('report').innerHTML = '<pre id="stream" style="white-space:pre-wrap;font-family:inherit;color:#444;font-size:14px"></pre>';
  var qs = 'ts_code=' + encodeURIComponent(ts) + '&peers=' + encodeURIComponent(peers)
         + '&model=' + encodeURIComponent(model) + '&thinking=' + thinking;
  var es = new EventSource('/analyze/start_stream?' + qs);   // 全 SSE,绕开不通的 fetch/XHR
  window._es = es;
  attachHandlers(es);
  return false;
}}
function connectJob(jobId) {{
  cleanupES(); window._buf = '';
  var es = new EventSource('/job/' + jobId + '/stream');
  window._es = es;
  attachHandlers(es);
}}
function _resume() {{
  if (window._jobId) {{   // 切回总重连读 buffer 续(含已完成的 final),不依赖 _es / _jobDone
    document.getElementById('status').textContent = '切回,重连续看…';
    connectJob(window._jobId);
  }}
}}
document.addEventListener('visibilitychange', function() {{ if (document.visibilityState === 'visible') _resume(); }});
window.addEventListener('focus', _resume);   // 双保险:visibilitychange 不触发时,focus 兜底
</script>"""
    return _page(body, "analyze")


@app.post("/analyze", response_class=HTMLResponse)
def analyze_run(ts_code: str = Form(...), peers: str = Form(""),
                model: str = Form(""), thinking: str = Form("")):
    from data.cache import MarketCache
    ts_code = ts_code.strip().upper()
    peer_list = [p.strip().upper() for p in peers.split(",") if p.strip()]
    cache = MarketCache(read_only=True)
    try:
        cfg = get_llm_config()
        if cfg.get("api_key") and cfg.get("models"):
            from insight.agent import OpenAICompatLLM
            from insight.report_agent import company_dd_report
            use_model = model or cfg["models"][0]
            use_think = (thinking == "on")
            llm = OpenAICompatLLM(use_model, cfg["base_url"], cfg["api_key"], cfg.get("temperature", 0.3),
                                  thinking=use_think, reasoning_effort=cfg.get("reasoning_effort", "high"))
            md = company_dd_report(cache, llm, ts_code, peer_list or None)
            engine = f"LLM · {use_model}{' · 思考' if use_think else ''}"
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


def _gen_report_events(cache, ts_code: str, peers: str, model: str, thinking: str):
    """报告事件流(generator,yield {event,data}):status/progress/token/final。
    SSE 直连与后台 job 共用。异常由调用方捕获。"""
    import markdown as md_lib
    from insight.report_agent import (_apply_charts, build_charts, build_dd_agent,
                                      dd_report_from_data)
    from insight.report_spec import DISCLAIMER
    ts = to_ts_code(ts_code.strip())
    peer_list = [to_ts_code(p.strip()) for p in peers.split(",") if p.strip()]
    cfg = get_llm_config()
    if cfg.get("api_key") and cfg.get("models"):
        from insight.agent import OpenAICompatLLM
        use_model = model or cfg["models"][0]
        use_think = (thinking == "on")
        llm = OpenAICompatLLM(use_model, cfg["base_url"], cfg["api_key"], cfg.get("temperature", 0.3),
                              thinking=use_think, reasoning_effort=cfg.get("reasoning_effort", "high"))
        agent = build_dd_agent(cache, llm)
        msg = f"请对 {ts} 撰写一份 DD 分析报告。"
        if peer_list:
            msg += f"并与以下标的对标:{', '.join(peer_list)}。"
        yield {"event": "status", "data": f"{use_model}{' · 思考' if use_think else ''} 生成中…"}
        buf = ""
        for ev in agent.run_stream(msg):
            if ev["type"] == "progress":
                yield {"event": "progress", "data": f"调用 {ev['text']}"}
            else:
                buf += ev["text"]
                yield {"event": "token", "data": ev["text"]}
        full = _apply_charts(buf, build_charts(cache, ts, peer_list)) + "\n\n" + DISCLAIMER
        yield {"event": "final", "data": md_lib.markdown(full, extensions=["tables"])}
    else:
        md = dd_report_from_data(cache, ts, peer_list or None)
        yield {"event": "status", "data": "确定性模板版(未配 LLM key)"}
        yield {"event": "final", "data": md_lib.markdown(md, extensions=["tables"])}


def _run_job(job_id: str, ts_code: str, peers: str, model: str, thinking: str):
    """后台线程:把报告事件写进 JOBS[job_id]['events'](前端断连不影响,可重连续看)。"""
    from data.cache import MarketCache
    job = JOBS[job_id]
    cache = MarketCache(read_only=True)
    try:
        for ev in _gen_report_events(cache, ts_code, peers, model, thinking):
            job["events"].append(ev)
    except Exception as e:
        job["events"].append({"event": "failed", "data": str(e)[:200]})
    finally:
        cache.close()
        job["done"] = True


@app.get("/analyze/start")
def analyze_start(ts_code: str, peers: str = "", model: str = "", thinking: str = ""):
    """启动后台报告任务,立即返回 job_id(用 GET:POST 经 tailscale serve 链路到不了,GET 稳)。"""
    import threading
    import uuid
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"events": [], "done": False}
    threading.Thread(target=_run_job, args=(job_id, ts_code, peers, model, thinking),
                     daemon=True).start()
    return {"job_id": job_id}


@app.get("/job/{job_id}/stream")
async def job_stream(job_id: str):
    """SSE 拉某 job 的事件(从头推 buffer + 实时新事件);断连重连会重推全 buffer 续看。"""
    import asyncio

    async def gen():
        job = JOBS.get(job_id)
        if not job:
            yield {"event": "failed", "data": "任务不存在或已过期"}
            yield {"event": "done", "data": ""}
            return
        i = 0
        while True:
            while i < len(job["events"]):
                yield job["events"][i]
                i += 1
            if job.get("done"):
                yield {"event": "done", "data": ""}
                return
            await asyncio.sleep(0.25)
    return EventSourceResponse(gen())


@app.get("/analyze/start_stream")
async def analyze_start_stream(ts_code: str, peers: str = "", model: str = "", thinking: str = ""):
    """EventSource 启动入口(全程 GET/SSE,绕开不通的 fetch):建 job + 后台线程 + 先推 job_id,再流式。"""
    import asyncio
    import threading
    import uuid
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"events": [], "done": False}
    threading.Thread(target=_run_job, args=(job_id, ts_code, peers, model, thinking),
                     daemon=True).start()

    async def gen():
        yield {"event": "job", "data": job_id}   # 先把 job_id 推给前端(重连用)
        i = 0
        while True:
            ev = JOBS[job_id]["events"]
            while i < len(ev):
                yield ev[i]
                i += 1
            if JOBS[job_id].get("done"):
                yield {"event": "done", "data": ""}
                return
            await asyncio.sleep(0.25)
    return EventSourceResponse(gen())


@app.get("/health")
def health():
    return {"ok": True, "llm": llm_is_configured()}
