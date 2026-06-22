"""综合质量评分单元测试。运行:.venv/bin/python tests/test_scores.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from research.scores import (altman_z_score, composite_score, cross_section_rank,
                             cross_section_zscore, piotroski_f_score)


def test_f_score_perfect():
    cur = dict(roa=0.10, cfo=100, net_profit=80, lt_debt_ratio=0.20,
               current_ratio=2.0, shares=1000, gross_margin=0.40, asset_turn=0.80)
    prev = dict(roa=0.08, cfo=90, net_profit=70, lt_debt_ratio=0.25,
                current_ratio=1.8, shares=1000, gross_margin=0.35, asset_turn=0.75)
    assert piotroski_f_score(cur, prev) == 9


def test_f_score_zero():
    cur = dict(roa=-0.10, cfo=-10, net_profit=5, lt_debt_ratio=0.30,
               current_ratio=1.0, shares=1200, gross_margin=0.20, asset_turn=0.50)
    prev = dict(roa=0.0, cfo=0, net_profit=0, lt_debt_ratio=0.25,
                current_ratio=1.2, shares=1000, gross_margin=0.25, asset_turn=0.60)
    assert piotroski_f_score(cur, prev) == 0


def test_altman_z():
    healthy = dict(working_capital=300, retained_earnings=400, ebit=200,
                   total_assets=1000, market_cap=2000, total_liab=400, sales=1500)
    assert altman_z_score(healthy) > 2.99
    distressed = dict(working_capital=-100, retained_earnings=-200, ebit=-50,
                      total_assets=1000, market_cap=100, total_liab=900, sales=300)
    assert altman_z_score(distressed) < 1.81


def test_cross_section_rank():
    assert cross_section_rank([10, 20, 30], ascending=True) == [0.0, 0.5, 1.0]
    assert cross_section_rank([10, 20, 30], ascending=False) == [1.0, 0.5, 0.0]
    assert cross_section_rank([10, None, 30])[1] is None      # 缺失保留 None


def test_cross_section_zscore():
    z = cross_section_zscore([1.0, 2.0, 3.0])
    assert abs(z[0] + z[2]) < 1e-9 and z[1] == 0.0           # 对称,中位为 0


def test_composite():
    assert composite_score([[0.0, 1.0], [1.0, 0.0]]) == [0.5, 0.5]   # 两因子相反 → 0.5
    assert composite_score([[1.0, 0.0], [None, 0.0]])[0] == 1.0      # 缺失项按现有权重归一


if __name__ == "__main__":
    for fn in [test_f_score_perfect, test_f_score_zero, test_altman_z,
               test_cross_section_rank, test_cross_section_zscore, test_composite]:
        fn()
        print(f"  ✓ {fn.__name__}")
    print("✅ 综合质量评分 全部通过")
