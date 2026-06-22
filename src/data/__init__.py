"""数据底座(M1,待建)。

职责:为竞技场提供"干净、含退市、point-in-time"的行情,并与厂商数据解耦。

计划模块(见 RDP.md §5、CLAUDE.md「数据源策略」):
  router.py    # SourceRouter:Tushare 优先 + akshare/baostock fallback + provenance
  cache.py     # DuckDB/parquet 本地缓存(先查缓存,miss 才打 API)
  backfill.py  # 历史导入 ETL(token-bucket 限速 + checkpoint 断点续传)
  feeds.py     # TushareAFeed / AkShareAFeed(实现 arena.DataFeed,复权+退市+停牌)

铁律:不分发原始厂商数据(朋友自带 token);所有源尊重限速 / ToS。
"""
