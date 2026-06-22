"""研究层胶水(M3,待建)。

职责:因子工程 + ML 训练 + 截面排序 → 产出"信号文件"(date × symbol → 分数)。

计划内容(见 RDP.md §4/§8、CLAUDE.md「接 Qlib」):
  Qlib 工作流封装(walk-forward / purge+embargo / DSR/PBO)
  SignalStrategy:读信号文件并映射成订单,实现 arena.Strategy

铁律:信号文件是研究层与执行层的唯一接口,本层不碰引擎。
排行榜数字只能来自竞技场引擎,不得用 Qlib 自带回测数字上榜。
"""
