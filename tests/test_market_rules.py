"""板块规则解析 + lot 对齐单元测试。运行:.venv/bin/python tests/test_market_rules.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from arena.market import (A_SHARE, A_SHARE_STAR, AShareRuleBook,
                          a_share_board, a_share_rules)


def test_board():
    assert a_share_board("688205.SH") == "star"
    assert a_share_board("300750.SZ") == "chinext"
    assert a_share_board("301001.SZ") == "chinext"
    assert a_share_board("600519.SH") == "main"
    assert a_share_board("000001.SZ") == "main"
    assert a_share_board("002594.SZ") == "main"          # 中小板并入主板
    # ST:仅主板降级到 ±5%
    assert a_share_board("600100.SH", "*ST某某") == "st"
    assert a_share_board("000400.SZ", "ST某某") == "st"
    # 科创/创业板即便 ST,涨跌停仍按板块(注册制,±20%)
    assert a_share_board("688001.SH", "*ST某科创") == "star"
    assert a_share_board("300999.SZ", "ST某创业") == "chinext"


def test_rules():
    star = a_share_rules("688205.SH")
    assert star.price_limit_pct == 0.20 and star.buy_min == 200 and star.buy_step == 1
    main = a_share_rules("600519.SH")
    assert main.price_limit_pct == 0.10 and main.buy_min == 100 and main.buy_step == 100
    assert a_share_rules("300750.SZ").price_limit_pct == 0.20
    assert a_share_rules("600100.SH", "*ST x").price_limit_pct == 0.05


def test_align_buy():
    assert A_SHARE.align_buy_qty(250) == 200             # 主板:100 整数倍
    assert A_SHARE.align_buy_qty(99) == 0
    assert A_SHARE.align_buy_qty(100) == 100
    assert A_SHARE_STAR.align_buy_qty(250) == 250        # 科创板:≥200,之上 +1
    assert A_SHARE_STAR.align_buy_qty(200) == 200
    assert A_SHARE_STAR.align_buy_qty(199) == 0
    assert A_SHARE_STAR.align_buy_qty(201) == 201


def test_align_sell():
    assert A_SHARE.align_sell_qty(120, 500) == 100       # 部分卖:100 整数倍
    assert A_SHARE.align_sell_qty(250, 250) == 250       # 清仓
    assert A_SHARE.align_sell_qty(300, 250) == 250       # 超持仓 → 清仓
    assert A_SHARE.align_sell_qty(50, 50) == 50          # 清仓零股一次卖出
    assert A_SHARE_STAR.align_sell_qty(130, 250) == 130  # 科创板 step 1


def test_rulebook():
    book = AShareRuleBook()
    assert book.for_symbol("688205.SH").price_limit_pct == 0.20
    assert book.for_symbol("600519.SH").buy_step == 100
    book2 = AShareRuleBook(names={"600100.SH": "*ST示例"})   # 带名称判 ST
    assert book2.for_symbol("600100.SH").price_limit_pct == 0.05


if __name__ == "__main__":
    for fn in [test_board, test_rules, test_align_buy, test_align_sell, test_rulebook]:
        fn()
        print(f"  ✓ {fn.__name__}")
    print("✅ market 板块规则 + lot 对齐 全部通过")
