"""composite_signals(改进版综合分)测试 —— 内存库样本,验证 质量 + 估值惩罚 + 趋势 + 行业中性。

真实库已验证(德科立 64→45 分位、龙头 96→99);此处补 CI 防回归。3 票设计:
- AAA 优质(roe 高)+ 便宜(pe 低)+ 改善(roe 升)
- CCC 与 AAA 财务完全相同,仅 pe 贵 → 隔离出"估值惩罚"效果
- BBB 劣质(roe 低)+ 贵(pe 高)+ 恶化(roe 降)= 德科立式
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data.cache import MarketCache
from research.loaders import composite_signals


def make_cache():
    c = MarketCache(":memory:")
    fi = []
    for code, r0, r1, gm, nm in [("AAA.SH", 15.0, 20.0, 40.0, 25.0),
                                 ("CCC.SH", 15.0, 20.0, 40.0, 25.0),
                                 ("BBB.SH", 8.0, 3.0, 25.0, 7.0)]:
        for ed, ann, roe in [(20231231, 20240401, r0), (20241231, 20250401, r1)]:
            fi.append({"ts_code": code, "end_date": ed, "ann_date": ann, "roe": roe,
                       "roa": roe * 0.8, "grossprofit_margin": gm, "netprofit_margin": nm,
                       "current_ratio": 3.0, "debt_to_assets": 30.0, "assets_turn": 0.8})
    c.upsert_table("fina_indicator", pd.DataFrame(fi), "end_date", 20241231)
    c.upsert_table("daily_basic", pd.DataFrame([
        {"ts_code": "AAA.SH", "trade_date": "20250601", "pe_ttm": 20.0},     # 便宜
        {"ts_code": "CCC.SH", "trade_date": "20250601", "pe_ttm": 500.0},    # 同质量但贵
        {"ts_code": "BBB.SH", "trade_date": "20250601", "pe_ttm": 500.0},    # 劣质又贵
    ]), "trade_date", "20250601")
    c.upsert_table("index_member", pd.DataFrame([
        {"l1_code": "801080.SI", "ts_code": "AAA.SH", "in_date": 20200101, "out_date": None},
        {"l1_code": "801080.SI", "ts_code": "CCC.SH", "in_date": 20200101, "out_date": None},
        {"l1_code": "801080.SI", "ts_code": "BBB.SH", "in_date": 20200101, "out_date": None},
    ]))
    return c


def test_composite_overall_ranking():
    c = make_cache()
    comp = composite_signals(c, "20250601")
    assert set(comp) == {"AAA.SH", "CCC.SH", "BBB.SH"}
    assert comp["AAA.SH"] > comp["CCC.SH"] > comp["BBB.SH"]   # 便宜优质 > 贵优质 > 贵劣质
    c.close()


def test_composite_value_penalty_isolated():
    """AAA 与 CCC 财务完全相同,仅 CCC 贵 → 估值惩罚必须把 CCC 压到 AAA 之下。"""
    c = make_cache()
    comp = composite_signals(c, "20250601")
    assert comp["AAA.SH"] > comp["CCC.SH"]
    c.close()


def test_composite_global_mode():
    c = make_cache()
    comp = composite_signals(c, "20250601", industry_neutral=False)
    assert comp["AAA.SH"] > comp["BBB.SH"]
    c.close()


def test_composite_empty_before_any_report():
    """date 早于所有 ann_date → 无已公告财报 → 空(PIT 不前视)。"""
    c = make_cache()
    assert composite_signals(c, "20200101") == {}
    c.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}")
    print("✅ composite_signals 全部通过")
