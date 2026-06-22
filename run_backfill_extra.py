"""三批补充数据 backfill —— 走香港代理,断点续传(backfill_log 记账,重跑跳过)。

批次:
  pit    : stk_limit + suspend_d + stock_st(按日) + disclosure_date(按期) —— PIT 三剑客,服务数据卫生铁律
  index  : index_daily(6 宽基) + 申万 L1 分类/成分 + sw_daily(行业日线) —— 竞技场真实基准 + 行业中性化
  factor : stk_factor_pro(261 列技术因子,体量大,约 1500 万行)

用法:  PYTHONPATH=src .venv/bin/python run_backfill_extra.py [pit|index|factor|all]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from data.cache import MarketCache
from data.feeds import TushareClient
from data import backfill

START, END = "20150101", "20260623"

# 按交易日的 PIT 数据集:(dataset, api, table, text_cols)
PIT_BY_DATE = [
    ("stk_limit", "stk_limit", "stk_limit", None),
    ("suspend_d", "suspend_d", "suspend_d", ["suspend_type", "suspend_timing"]),
    ("stock_st",  "stock_st",  "stock_st",  ["name", "type_name"]),
]


def main():
    batch = sys.argv[1] if len(sys.argv) > 1 else "all"
    cache = MarketCache()
    client = TushareClient()
    days = backfill.trading_days(client, START, END)
    print(f"批次={batch} | {START}~{END} | 交易日 {len(days)}\n")

    if batch in ("pit", "all"):
        print("===== 批次1:PIT 三剑客 =====")
        for ds, api, tbl, tc in PIT_BY_DATE:
            backfill._by_date(cache, client, days, ds, api, table=tbl, by_col="trade_date", text_cols=tc)
        backfill.backfill_disclosure(cache, client, START, END)

    if batch in ("index", "all"):
        print("\n===== 批次2:指数/行业 =====")
        backfill.backfill_indices(cache, client, START, END)
        backfill._by_date(cache, client, days, "sw_daily", "sw_daily",
                          table="sw_daily", by_col="trade_date", text_cols=["name"])

    if batch in ("factor", "all"):
        print("\n===== 批次3:stk_factor_pro(261 列,大)=====")
        backfill._by_date(cache, client, days, "stk_factor_pro", "stk_factor_pro",
                          table="stk_factor_pro", by_col="trade_date")

    cache.close()
    print("\n[run_backfill_extra] 完成")


if __name__ == "__main__":
    main()
