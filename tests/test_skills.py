"""insight 领域工具测试 —— 内存库小样本(德科立 + 茅台),验证查询/评分/对标 + 注册。

不碰主库(backfill 写锁期间也能跑);用 ':memory:' DuckDB 造最小样本,断言 SQL 逻辑正确。
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data.cache import MarketCache
from insight.skills import (company_profile, financial_history, peer_comparison,
                            price_performance, quality_score, register_company_tools)
from insight.tools import ToolRegistry


def make_cache():
    c = MarketCache(":memory:")
    c.upsert_basic(pd.DataFrame([
        {"ts_code": "688205.SH", "name": "德科立", "market": "科创板",
         "list_date": "20220809", "delist_date": None, "list_status": "L"},
        {"ts_code": "600519.SH", "name": "贵州茅台", "market": "主板",
         "list_date": "20010827", "delist_date": None, "list_status": "L"},
    ]))
    bars = []
    for code, base in [("688205.SH", 50.0), ("600519.SH", 1500.0)]:
        for i, d in enumerate(["20220809", "20250623", "20260622"]):
            bars.append({"ts_code": code, "trade_date": d, "open": base, "high": base,
                         "low": base, "close": base * (1 + i), "pre_close": base,
                         "vol": 1.0, "amount": 1.0, "adj_factor": 1.0})
    c.upsert_daily(pd.DataFrame(bars))
    c.upsert_table("daily_basic", pd.DataFrame([
        {"ts_code": "688205.SH", "trade_date": "20260622", "close": 245.0, "pe_ttm": 510.0,
         "pb": 16.7, "ps_ttm": 39.5, "dv_ttm": 0.04, "total_mv": 3913580.0},
        {"ts_code": "600519.SH", "trade_date": "20260622", "close": 1500.0, "pe_ttm": 25.0,
         "pb": 8.0, "ps_ttm": 10.0, "dv_ttm": 3.5, "total_mv": 18000000.0},
    ]), "trade_date", "20260622")
    c.upsert_table("fina_indicator", pd.DataFrame([
        {"ts_code": "688205.SH", "end_date": "20251231", "ann_date": "20260417", "roe": 3.14,
         "roa": 2.57, "grossprofit_margin": 27.6, "netprofit_margin": 7.66,
         "current_ratio": 4.15, "debt_to_assets": 18.76, "assets_turn": 0.34},
        {"ts_code": "600519.SH", "end_date": "20251231", "ann_date": "20260417", "roe": 34.46,
         "roa": 27.8, "grossprofit_margin": 91.18, "netprofit_margin": 50.5,
         "current_ratio": 5.09, "debt_to_assets": 16.42, "assets_turn": 0.57},
    ]), "end_date", "20251231")
    c.upsert_table("income", pd.DataFrame([
        {"ts_code": "688205.SH", "end_date": "20251231", "ann_date": "20260417",
         "total_revenue": 9.34e8, "n_income": 0.72e8, "operate_profit": 0.72e8},
        {"ts_code": "600519.SH", "end_date": "20251231", "ann_date": "20260417",
         "total_revenue": 1700e8, "n_income": 860e8, "operate_profit": 1100e8},
    ]), "end_date", "20251231")
    return c


def test_company_profile():
    c = make_cache()
    p = company_profile(c, "688205.SH")
    assert p["name"] == "德科立" and p["market"] == "科创板"
    assert p["latest"]["pe_ttm"] == 510.0
    assert p["latest"]["total_mv_yi"] == 391.4          # 3913580 万 → 亿
    assert company_profile(c, "000000.SZ")["error"]      # 不存在
    c.close()


def test_financial_history():
    c = make_cache()
    f = financial_history(c, "688205.SH")
    assert f["annual"][0]["year"] == "2025"
    assert f["annual"][0]["revenue_yi"] == 9.34
    assert f["annual"][0]["net_profit_yi"] == 0.72
    assert f["annual"][0]["roe"] == 3.14
    c.close()


def test_price_performance():
    c = make_cache()
    pp = price_performance(c, "688205.SH")
    assert abs(pp["since_listing"] - 2.0) < 1e-6        # 50 → 150,+200%
    assert pp["past_year"] is None                       # 样本不足 250 日
    c.close()


def test_quality_score_and_peer():
    c = make_cache()
    qd = quality_score(c, "688205.SH", "20260622")
    qm = quality_score(c, "600519.SH", "20260622")
    assert qd["quality_score"] is not None and qm["quality_score"] is not None
    assert qm["quality_score"] > qd["quality_score"]     # 茅台质量明显优于德科立
    assert qm["percentile"] >= qd["percentile"]
    peer = peer_comparison(c, ["688205.SH", "600519.SH"], "20260622")
    assert len(peer["peers"]) == 2
    assert peer["peers"][0]["name"] == "德科立"
    assert peer["peers"][1]["pe_ttm"] == 25.0
    c.close()


def test_registration():
    c = make_cache()
    reg = ToolRegistry()
    register_company_tools(reg, c)
    for name in ("company_profile", "financial_history", "price_performance",
                 "quality_score", "peer_comparison"):
        assert name in reg.names()
    out = reg.call("company_profile", {"ts_code": "688205.SH"})
    assert out["name"] == "德科立"
    out2 = reg.call("peer_comparison", {"ts_codes": ["688205.SH", "600519.SH"]})
    assert len(out2["peers"]) == 2
    assert len(reg.openai_tools()) == 5                  # schema 可导出给 LLM
    c.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}")
    print("✅ insight skills 全部通过")
