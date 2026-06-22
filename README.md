# MonkeyBench 🐒

> 让多套策略和一群随机"猴子"在同一套**虚拟撮合规则**下同台竞技,用排行榜回答一个问题:**机器学习在股市里到底有没有用?**

个人量化**研究 / 验证**工具。所有订单、账户、盈亏都是**虚拟核算,绝不碰真钱、绝不接券商**。当前覆盖沪深 A 股(主板 / 创业板 / 科创板 / ST),日频。

🔗 项目站点(建设中):**[monkey.operonsys.com](https://monkey.operonsys.com)** — 首页 landing,应用在 `/app`。

---

## 核心问题

ML(尤其是**截面排序**模型)在**扣掉真实交易成本**后,能否稳定跑赢"运气基线"?

> **运气基线 = 一群随机交易猴子里最好的那只。** 这是内置的零假设:任何精心设计的策略,扣完成本干不过最好的猴子、也干不过买入持有,就判定它**没有真 edge**。

## 为什么结果可信(四条铁律)

1. **唯一撮合引擎** — 所有成交只走一个 `MatchingEngine`,排行榜数字**只能来自它**,杜绝"不同回测假设之间关公战秦琼"。
2. **无未来函数** — T 收盘决策 → T+1 开盘成交,由竞技场循环的时序**物理保证**;策略只能看到"截至当前收盘"的信息。
3. **数据卫生** — 复权价算收益、**含已退市股**(抗幸存者偏差)、point-in-time 基本面、正确处理停牌。
4. **市场规则真实** — A 股 T+1、分板块涨跌停(主板 ±10% / 创业·科创 ±20% / 主板 ST ±5%)、科创板最小买入 ≥200 股、佣金 / 印花税 / 滑点成本。

## 架构(三层)

```
研究层(离线,Qlib/vectorbt)   因子 + ML 训练 + 截面排序
        │  产出信号文件 (date × symbol → 分数)  ← 研究层与执行层的唯一接口
        ▼
执行层 / 竞技场(唯一引擎)      策略 → 市场规则 + 成本 → 撮合
        │  喂历史 = 回测 | 喂每日 = 纸面实盘(同一引擎)
        ▼
排行榜 / 归因层                吃 append-only 事件日志 → 指标 + 排名(含猴子基准)
```

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python ≥ 3.13 / uv;**引擎核心零依赖** |
| 数据源 | Tushare Pro(主,SDK)+ akshare / baostock(fallback) |
| 数据库 | **DuckDB**(行情 / 因子 / 回测产出,OLAP)+ **SQLite**(应用状态);不上 PG |
| 缓存 | DuckDB 持久落盘:**存原始价 + 复权因子 + provenance**,缓存优先、限速、断点续传 |
| 后端 / 前端 | FastAPI + HTMX + Tailwind(规划中) |
| LLM 洞见 | agent + skill 工具链(**非 NL2SQL**),OpenAI 兼容 API(模型可换) |
| 部署 | exe.dev 单 VPS + docker compose;`monkey.operonsys.com`(landing)+ `/app`(应用),规划中 |

## 目录结构

```
src/arena/      竞技场引擎(零依赖):market / engine / portfolio / strategy(ies) / arena / leaderboard / eventlog / datafeed
src/data/       数据底座:ratelimit(限速) / cache(DuckDB) / feeds(Tushare 接入) / universe(票池) / backfill(批量导入)
src/research/   研究层胶水(规划中):Qlib + SignalStrategy
tests/          单元测试
data/cache/     本地行情缓存(DuckDB,不入库)
run_demo.py     合成数据 demo(零依赖、零 token)
run_m1.py       真实数据最小闭环(拉一只票 → 落 DuckDB → 喂引擎 → 排行榜)
CLAUDE.md       给 AI 协作者的开发上下文      RDP.md  研究与设计方案
```

## 快速开始

```bash
# 1) 环境
uv venv --python 3.13
uv pip install -e ".[data]"          # 引擎本身零依赖;data 组装 tushare/duckdb

# 2) 合成数据 demo(无需任何 token,验证引擎)
uv run python run_demo.py

# 3) 真实数据(自备 Tushare token)
cp .env.example .env                 # 填入你自己的 TUSHARE_API_KEY
uv run python run_m1.py              # 拉 688205 → 落 DuckDB → 喂引擎 → 排行榜

# 4) 批量 backfill(科创板 + 沪深300 日线,限速 + 断点续传)
PYTHONPATH=src uv run python -m data.backfill
```

## 进展

- ✅ 竞技场引擎:T+1、分板块涨跌停拒单、成本 / 滑点、猴子基准、append-only 事件日志、自动判决
- ✅ A 股板块规则:按代码前缀 / 名称自动判定(主板 / 创业 / 科创 / ST),科创板 lot「≥200+1」
- ✅ 数据层:Tushare 限速接入(对 500/min 硬顶留弹性 + 退避)、DuckDB 持久缓存(复权 / provenance)、backfill(断点续传 / 增量)
- 🚧 多票竞技场、Qlib 信号集成、walk-forward + DSR/PBO、Web 看板(`/app`)+ LLM 洞见、landing page

## 数据与合规

- **仓库只含代码,不含任何行情 / 付费数据**(`data/cache/` 不入库)。
- **自备 Tushare token**(`.env`),尊重其 ToS 与每分钟调用上限;backfill 强制限速 + 可断点续传。
- 本项目基于 **Tushare Pro 8000 积分/年**档位(完整接口 + 500 次/分限速)。**免费 / 低积分版接口与限速受限,无法使用全部功能** —— 详见 [tushare.pro](https://tushare.pro) 积分说明。

## 非目标

不做:实盘 / 券商 / 真钱、SaaS / 多租户 / 计费、美股(当前)、北交所、高频 / 低延迟、原始数据再分发。

## 文档

- [`CLAUDE.md`](CLAUDE.md) — 开发上下文、铁律、代码约定
- [`RDP.md`](RDP.md) — 研究与设计方案(为什么 / 做什么)

---

*MonkeyBench 是个人研究工具,非投资建议。一切结果均为虚拟回测。*
