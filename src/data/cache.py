"""DuckDB 持久行情缓存 —— 把付费数据永久落盘,缓存优先,绝不重复拉。

表:
- daily_bar     原始价 + adj_factor + provenance(主键 ts_code+trade_date,INSERT OR REPLACE 增量)
- stock_basic   股票列表(含退市),提供名称(供 ST 判定)与板块
- backfill_log  每票每数据集的拉取结果(ok/failed),供断点续传与审计

存原始价(不存复权价),复权留给 feed/回测层算,不锁死复权方式。
缓存文件默认 data/cache/market.duckdb(已 gitignore,不入库)。
"""
from __future__ import annotations

from pathlib import Path

import duckdb

DEFAULT_DB = Path("data/cache/market.duckdb")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_bar (
    ts_code     VARCHAR  NOT NULL,
    trade_date  DATE     NOT NULL,
    open        DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    pre_close   DOUBLE, vol  DOUBLE, amount DOUBLE,
    adj_factor  DOUBLE,
    source      VARCHAR,
    fetched_at  TIMESTAMP,
    PRIMARY KEY (ts_code, trade_date)
);
CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code     VARCHAR PRIMARY KEY,
    name        VARCHAR, market VARCHAR,
    list_date   VARCHAR, delist_date VARCHAR, list_status VARCHAR,
    fetched_at  TIMESTAMP
);
CREATE TABLE IF NOT EXISTS backfill_log (
    dataset  VARCHAR, ts_code VARCHAR, status VARCHAR, rows INTEGER,
    ts       TIMESTAMP,
    PRIMARY KEY (dataset, ts_code)
);
"""


class MarketCache:
    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.db_path))
        self.con.execute(_SCHEMA)

    def close(self) -> None:
        self.con.close()

    # --- daily 行情 ---
    def coverage(self, ts_code: str):
        """返回 (min_date, max_date, row_count);未缓存则 count=0。"""
        return self.con.execute(
            "SELECT min(trade_date), max(trade_date), count(*) FROM daily_bar WHERE ts_code = ?",
            [ts_code],
        ).fetchone()

    def upsert_daily(self, df, source: str = "tushare") -> int:
        """落库 daily(已 merge adj_factor)。trade_date 为 'YYYYMMDD' 字符串。"""
        if df is None or len(df) == 0:
            return 0
        self.con.register("incoming", df)
        self.con.execute(
            """
            INSERT OR REPLACE INTO daily_bar
            SELECT ts_code, strptime(trade_date, '%Y%m%d')::DATE,
                   open, high, low, close, pre_close, vol, amount, adj_factor,
                   ?, now()::TIMESTAMP
            FROM incoming
            """,
            [source],
        )
        self.con.unregister("incoming")
        return len(df)

    def get_daily(self, ts_code: str):
        """按 trade_date 升序返回缓存行(DataFrame),trade_date 为 'YYYYMMDD' 字符串。"""
        return self.con.execute(
            """
            SELECT ts_code, strftime(trade_date, '%Y%m%d') AS trade_date,
                   open, high, low, close, pre_close, vol, amount, adj_factor
            FROM daily_bar WHERE ts_code = ? ORDER BY trade_date
            """,
            [ts_code],
        ).df()

    # --- 基础数据 / 名称 ---
    def upsert_basic(self, df) -> int:
        """落库 stock_basic。df 含 ts_code,name,market,list_date,delist_date,list_status。"""
        if df is None or len(df) == 0:
            return 0
        self.con.register("b_in", df)
        self.con.execute(
            """
            INSERT OR REPLACE INTO stock_basic
            SELECT ts_code, name, market, list_date, delist_date, list_status, now()::TIMESTAMP
            FROM b_in
            """
        )
        self.con.unregister("b_in")
        return len(df)

    def get_names(self) -> dict:
        """ts_code → name(供 AShareRuleBook 判 ST)。"""
        return dict(self.con.execute(
            "SELECT ts_code, name FROM stock_basic WHERE name IS NOT NULL").fetchall())

    # --- backfill manifest(断点续传)---
    def log_backfill(self, dataset: str, ts_code: str, status: str, rows: int) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO backfill_log VALUES (?, ?, ?, ?, now()::TIMESTAMP)",
            [dataset, ts_code, status, int(rows)],
        )

    def done_codes(self, dataset: str) -> set:
        """某数据集已成功拉取的 ts_code 集合(续传时跳过)。"""
        return {r[0] for r in self.con.execute(
            "SELECT ts_code FROM backfill_log WHERE dataset = ? AND status = 'ok'",
            [dataset]).fetchall()}
