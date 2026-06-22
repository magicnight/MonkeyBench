"""Tushare 接入 + A股 DataFeed。

- `TushareClient`:限速 + 退避重试封装。限速默认对硬顶 500/min 留弹性
  (`for_hard_limit` → ~400/min + 小突发);偶发触线/网络错时指数退避重试,不硬撞。
- `fetch_to_cache`:拉 daily + adj_factor,merge 后落 DuckDB。
- `TushareAFeed`:**缓存优先**(本地有就读,没有才拉)→ 前复权 → MarketData,喂给引擎。

复权:存原始价,这里算**前复权**(price × adj_factor / adj_factor_latest)。
prev_close 用前一交易日的复权收盘 → 复权序列连续,涨跌停与净值都正确。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from arena.datafeed import DataFeed, MarketData
from arena.market import Bar

from .cache import MarketCache
from .ratelimit import TokenBucket


def load_token(env_path: str | Path = ".env") -> str | None:
    p = Path(env_path)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line.startswith("TUSHARE_API_KEY") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("TUSHARE_API_KEY")


class TushareClient:
    """限速 + 退避重试的 Tushare Pro 封装。

    - 限速:默认对硬顶 500/min **留弹性**(只用 ~80%、突发受控),绝不顶格。
    - 韧性:偶发限速/网络错误指数退避重试;权限/积分/参数类错误直接抛(重试无意义)。
    """

    def __init__(self, token: str | None = None, bucket: TokenBucket | None = None,
                 max_retries: int = 3, timeout: int = 30):
        import socket
        import tushare as ts

        # 兜底:防止某次请求静默 hang(tushare 不总暴露 timeout)。超时 → 抛异常 → 触发退避重试。
        socket.setdefaulttimeout(timeout)
        try:
            self.pro = ts.pro_api(token or load_token(), timeout=timeout)
        except TypeError:                       # 旧版 pro_api 不接受 timeout 参数
            self.pro = ts.pro_api(token or load_token())
        self.bucket = bucket or TokenBucket.for_hard_limit(500)   # 硬顶 500 → 留弹性
        self.max_retries = max_retries

    def _call(self, fn, **kwargs):
        for attempt in range(self.max_retries + 1):
            self.bucket.acquire()
            try:
                return fn(**kwargs)
            except Exception as e:
                msg = str(e)
                permanent = any(k in msg for k in ("权限", "积分", "参数", "token", "没有"))
                if permanent or attempt == self.max_retries:
                    raise
                backoff = 3 * 2 ** attempt          # 3, 6, 12 秒
                print(f"  [retry] {getattr(fn, '__name__', fn)} 第 {attempt + 1} 次失败"
                      f"({msg[:40]}),{backoff}s 后重试")
                time.sleep(backoff)

    def fetch(self, api_name: str, **kwargs):
        """通用调用任意 Tushare 接口(限速 + 退避)。universe / 其他数据集用。"""
        return self._call(getattr(self.pro, api_name), **kwargs)

    def daily(self, ts_code: str):
        return self._call(self.pro.daily, ts_code=ts_code)

    def adj_factor(self, ts_code: str):
        return self._call(self.pro.adj_factor, ts_code=ts_code)


def fetch_to_cache(ts_code: str, client: TushareClient, cache: MarketCache) -> int:
    """拉 daily + adj_factor,merge,落库。返回落库行数。"""
    d = client.daily(ts_code)
    if d is None or len(d) == 0:
        return 0
    a = client.adj_factor(ts_code)
    merged = d.merge(a[["trade_date", "adj_factor"]], on="trade_date", how="left")
    return cache.upsert_daily(merged, source="tushare")


class TushareAFeed(DataFeed):
    """单票或多票 A 股 feed。缓存优先;build() 返回前复权 MarketData。"""

    def __init__(self, ts_codes, cache: MarketCache | None = None,
                 client: TushareClient | None = None, refresh: bool = False,
                 start: str | None = None):
        self.ts_codes = [ts_codes] if isinstance(ts_codes, str) else list(ts_codes)
        self.cache = cache or MarketCache()
        self.client = client
        self.refresh = refresh
        self.start = start   # 'YYYYMMDD':只保留 >= start 的 bar(限制回测窗口)

    def _ensure(self, ts_code: str) -> None:
        _, _, n = self.cache.coverage(ts_code)
        if n == 0 or self.refresh:
            if self.client is None:
                self.client = TushareClient()
            got = fetch_to_cache(ts_code, self.client, self.cache)
            print(f"  [fetch] {ts_code}: 落库 {got} 行")
        else:
            print(f"  [cache] {ts_code}: 命中 {n} 行,跳过 API")

    def build(self) -> MarketData:
        per_symbol = {}
        all_dates: set[str] = set()
        for code in self.ts_codes:
            self._ensure(code)
            df = self.cache.get_daily(code)
            if self.start:
                df = df[df["trade_date"] >= self.start]
            if len(df) == 0:
                continue
            f = df["adj_factor"].ffill().fillna(1.0)
            norm = f / f.iloc[-1]                      # 前复权:最新日因子归一
            df = df.assign(o=df["open"] * norm, h=df["high"] * norm,
                           l=df["low"] * norm, c=df["close"] * norm)
            per_symbol[code] = df
            all_dates.update(df["trade_date"].tolist())

        dates = sorted(all_dates)
        idx = {d: i for i, d in enumerate(dates)}
        bars = {code: [None] * len(dates) for code in per_symbol}
        for code, df in per_symbol.items():
            prev_c = None
            for row in df.itertuples():
                i = idx[row.trade_date]
                pc = prev_c if prev_c is not None else row.o   # 首日无前收,用开盘近似
                bars[code][i] = Bar(date=row.trade_date, symbol=code, open=row.o,
                                    high=row.h, low=row.l, close=row.c,
                                    volume=row.vol, prev_close=pc)
                prev_c = row.c
        return MarketData(symbols=list(per_symbol.keys()), dates=dates, bars=bars)
