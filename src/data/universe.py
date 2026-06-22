"""票池枚举:科创板 / 沪深300 / 全市场(含退市)。供 backfill 用。

依赖 TushareClient(限速)。北交所(项目非目标)排除。
"""
from __future__ import annotations

import pandas as pd

from .feeds import TushareClient

_BASIC_FIELDS = "ts_code,name,market,list_date,delist_date"


def fetch_basic(client: TushareClient, include_delisted: bool = True) -> pd.DataFrame:
    """stock_basic(上市 L + 可选退市 D / 暂停 P),手动标 list_status。"""
    statuses = ["L", "D", "P"] if include_delisted else ["L"]
    frames = []
    for s in statuses:
        try:
            df = client.fetch("stock_basic", list_status=s, fields=_BASIC_FIELDS).copy()
        except Exception as e:
            print(f"  stock_basic({s}) 跳过:{str(e)[:50]}")
            continue
        df["list_status"] = s
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def star_codes(basic: pd.DataFrame) -> list:
    """科创板(上市)。"""
    m = (basic["list_status"] == "L") & (basic["market"] == "科创板")
    return basic[m]["ts_code"].tolist()


def hs300_codes(client: TushareClient, start: str = "20260101", end: str = "20260622") -> list:
    """沪深 300 最近一期成分。"""
    iw = client.fetch("index_weight", index_code="000300.SH", start_date=start, end_date=end)
    if len(iw) == 0:
        return []
    latest = iw["trade_date"].max()
    return iw[iw["trade_date"] == latest]["con_code"].tolist()


def all_a_codes(basic: pd.DataFrame) -> list:
    """全市场(含退市),排除北交所(非目标)。"""
    return basic[basic["market"] != "北交所"]["ts_code"].tolist()
