# CLAUDE.md — MonkeyBench

> 给 Claude Code 的项目开发上下文。配套:`RDP.md`(研究设计方案,讲"为什么/做什么")。本文件讲"怎么做、有哪些铁律、代码长什么样"。

## 项目概述

MonkeyBench 是一个**个人量化研究 / 验证工具**:让多套策略和一群随机"猴子"在同一套**虚拟撮合规则**下同台竞技,用排行榜回答"机器学习在股市里到底有没有用"。**所有订单和账户都是虚拟核算,绝不碰真钱。** 当前只做沪深 A 股(含科创板、ST)。可能小范围分享给朋友共同验证,但不是产品、不做 SaaS。

---

## ⛔ 不可违背的铁律(INVARIANTS)

开发中任何时候都不得违反以下任意一条:

1. **一切虚拟**:绝不接券商 / 真钱 / 支付 API。所有 order / account / PnL 都是虚拟核算。
2. **唯一真相**:所有成交只走 `src/arena/engine.py` 的 `MatchingEngine`。**排行榜数字只能来自竞技场引擎**,不得用 Qlib / backtrader 自带回测的数字上榜。
3. **无未来函数**:T 收盘决策 → T+1 开盘成交。**绝不用同一根 bar 的收盘价既决策又成交**。`Strategy.on_bar` 只能看到"截至当前收盘"的信息(由 `Context` 强制)。
4. **数据卫生**:复权价算收益;**含已退市股**;point-in-time 基本面;正确处理停牌。违反任一条 = 回测结果作废。
5. **API 合规**:所有数据源尊重限速 / ToS(Tushare 500 次/分);backfill **必须限速 + 可断点续传**。
6. **项目沟通** 使用 **中文**。

---

## 架构地图(三层)

- **研究层**(离线,Qlib / vectorbt):因子 + ML 训练 + 截面排序 → 产出**信号文件** `(date × symbol → 分数)`。
- **执行层 / 竞技场**(`src/arena/*`,已有骨架):策略 → 市场规则 + 成本 → 撮合。喂历史 = 回测,喂每日 = 纸面实盘。
- **排行榜 / 归因层**:吃 append-only 事件日志 → 指标 + 排名(含猴子)。
- **信号文件** = 研究层与执行层的唯一接口。Qlib 怎么折腾都**不碰引擎**。

---

## 技术栈(全栈,定稿)

> 原则:Python 单语言重心、引擎零依赖、少运维、单实例自用。

- **语言/包管理**:Python ≥ 3.13,uv。引擎核心保持零依赖。
- **数据库(双库,各司其职)**:
  - **DuckDB**(+ 可选 parquet 湖)—— 行情/因子/财务/回测产出/事件日志(OLAP);backfill·scheduler 单写,web·研究只读。
  - **SQLite(WAL)**—— 应用状态(LLM 洞见缓存/调度 jobstore/auth/运行元数据);经 SQLAlchemy 抽象,留 PG 升级路径。
  - **不上 PostgreSQL**:单实例自用是过度配置。触发 PG 的条件:多人并发写 / 应用状态高并发争用 / 多服务共享事务库。
- **后端**:FastAPI(异步,与引擎/数据/研究同栈;渲染页面 + SSE + 调度)。
- **前端**:**HTMX + Tailwind**(服务端渲染 HTML 片段;审美用 Tailwind 组件库自由掌控)。K线/高交互区 = lightweight-charts 的 JS 孤岛(web component)按需嵌入。**不用 Reflex/SvelteKit/Streamlit**。
- **LLM 洞见**:**agent + skill 工具链(非 NL2SQL)**。工具核心一份 Python 实现,多协议暴露(OpenAI function-calling + 可选 MCP)。模型走 OpenAI 兼容 API,可换(DeepSeek V4 / GLM-5.2 / MiniMax-3)。
- **调度**:APScheduler(每日增量 backfill + 纸面实盘)。
- **部署**:exe.dev 单 VPS + docker compose;域名 `monkey.operonsys.com`(根 = landing 单页,`/app` = 应用);TLS/公网分享由平台负责,app 层加简单 auth 挡公网(不审计、不做账号体系)。

---

## 仓库结构

```
src/arena/          # 【已有】竞技场引擎(零依赖),__init__.py 导出公共 API
  market.py portfolio.py engine.py strategy.py
  strategies.py datafeed.py arena.py leaderboard.py eventlog.py
src/data/           # 【M1,占位已建】数据底座(__init__.py 已列计划模块)
  router.py         #   SourceRouter:Tushare 优先 + fallback + provenance
  cache.py          #   DuckDB/parquet 本地缓存
  backfill.py       #   历史导入 ETL(限速 + 续传)
  feeds.py          #   TushareAFeed / AkShareAFeed(实现 DataFeed)
src/research/       # 【M3,占位已建】Qlib 胶水 + SignalStrategy
data/cache/         # 本地行情缓存(不入库 git,见 .gitignore)
run_demo.py         # 【已有】合成数据 demo(纯标准库;sys.path 注入 src/)
pyproject.toml      # uv 项目;wheel 打包 src/arena
.gitignore          # 忽略缓存 / Python 产物 / 机密
.env  TuShareMCP    # 【机密,已 gitignore】Tushare token / MCP 配置,绝不入库
RDP.md  CLAUDE.md
```

> 导入名:src 在 path 上时 `src/arena`→`arena`、`src/data`→`data`、`src/research`→`research`(三个平级包)。

---

## 数据源策略

- **优先级**:Tushare Pro(高级,**主**)→ akshare → baostock(fallback)。
- **Tushare 档位**:本项目基于 **8000 积分/年**版本(500 次/分限速 + 完整接口:日线 / 财务 / 宏观 / ST / 概念成分 / 资金流 / 筹码 / 量化因子等)。**免费 / 低积分版接口与限速受限,无法使用全部功能。**
- `SourceRouter` 按 `(symbol, field, range)` 取数,失败逐级降级,记录每条数据的 **provenance**。
- **缓存优先**:先查本地 DuckDB/parquet,miss 才打 API。
- backfill 目标 ≥10 年全市场(含退市),token-bucket 限速,checkpoint 可续。
- **Tushare 接入方式(M1 待定)**:仓库已存在 `TuShareMCP`(MCP 服务器配置)与 `.env`(`TUSHARE_API_KEY`)两条路 —— **MCP 服务器** vs **`tushare` Python SDK**。二者在限速/积分控制、backfill 断点、provenance 落地上差别较大,M1 开工前需二选一(或定清主次)。

---

## 市场规则速查(A 股)

| 板块 / 类型 | 涨跌停 | 最小买入 | 代码前缀 |
|---|---|---|---|
| 主板 | ±10% | 100 股整数倍 | 60 / 000 / 001 / 002 |
| 创业板 | ±20% | 100 股整数倍 | 300 / 301 |
| 科创板 | ±20% | **≥200 股,+1 递增** | 688 |
| ST / *ST | ±5% | 100 股整数倍 | 名称含 ST |

- 全 A 股 **T+1**(当日买入不可当日卖)。
- 成本(近似,落地核实):佣金约万 2.5 / 最低 5 元双边;印花税 0.05% 仅卖出;过户费约 0.001% 双边。
- 新股首日 / 前 5 日特例 → 先按常态,Phase 1.5 再补。

---

## 技术约定

- Python ≥ 3.13,**uv** 管理。引擎核心**保持零 / 少依赖**。
- 类型注解 + `dataclass`。注释**中英混排可**。
- **加新策略**:继承 `Strategy` 实现 `on_bar(ctx) -> list[Order]`,在配置 / `run_demo` 里注册,**不改引擎**。
- **加新数据源**:实现 `DataFeed.build() -> MarketData`,其余不动。
- **接 Qlib**:写 `SignalStrategy` 读信号文件,**不碰引擎**。
- 不引入 localStorage / 浏览器存储(本项目无前端持久化需求)。

---

## 常用命令

```bash
python run_demo.py                              # 跑合成数据 demo(已可用;无 python 则 python3 / uv run)
uv sync --extra data --extra research           # 装数据/研究依赖(待 deps 落地)
PYTHONPATH=src python -m data.backfill \        # 跑历史导入(待建;data 为 src 下平级包)
       --years 10 --source tushare --resume
```

---

## 给 Claude Code 的起手任务(按序)

1. ✅ **(已完成)补全 `market.py` 的 A 股规则**:创业板 / 科创板 ±20%、ST ±5%、科创板 lot(≥200 + 1 递增);按代码前缀 / 名称自动判定板块(`a_share_rules` + `RuleBook`,引擎 per-symbol;ST 仅主板降 5%)。
2. **填充 `src/data/`(占位已建)**:`SourceRouter`(Tushare 优先)+ DuckDB 缓存 + `backfill.py`(限速 + 续传 + provenance)。先定 Tushare 接入方式(MCP vs SDK)。
3. **写 `TushareAFeed` / `AkShareAFeed`**(实现 `DataFeed`):复权 + 含退市 + 停牌处理。
4. **`run_demo` 切到真实数据**,让猴子 + 动量在真实 A 股上跑。

---

## 非目标

不做:实盘 / 券商 / 真钱、SaaS / 多租户 / 计费、美股(当前)、北交所、高频 / 低延迟、原始数据再分发。

---

## 术语表

- **科创板 / STAR**:上交所 688,±20%,最小申报 200 股。
- **创业板 / ChiNext**:深交所 300/301,±20%。
- **ST / *ST**:风险警示股,±5%。
- **T+1**:当日买入次日才可卖。
- **复权(qfq / hfq)**:前复权 / 后复权,处理除权除息。
- **幸存者偏差**:只用存活股票回测导致结果虚高。
- **Point-in-time**:只用"当时已知"的数据版本。
- **walk-forward**:滚动前推,用过去拟合、未来检验。
- **purge / embargo**:训练-测试间的隔离带,防泄漏。
- **DSR / PBO**:Deflated Sharpe Ratio / 回测过拟合概率,按试验次数校正。
- **猴子(monkey)**:随机交易者,作为零假设 / 运气天花板。
