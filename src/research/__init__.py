"""研究层 —— 因子 / 综合评分 + 信号策略。

- `scores`:Piotroski F-Score、Altman Z-Score、截面工具(rank/zscore/composite)。
- `signal_strategy`:`SignalStrategy`(读信号文件 date×symbol→分数 → 竞技场;
  信号是研究层与执行层的唯一接口,不碰引擎)。

后续(M3):Qlib 工作流封装(walk-forward / purge+embargo / DSR/PBO)产出信号文件。
"""
from .scores import (altman_z_score, composite_score, cross_section_rank,
                     cross_section_zscore, piotroski_f_score)
from .signal_strategy import SignalStrategy

__all__ = [
    "piotroski_f_score", "altman_z_score",
    "cross_section_rank", "cross_section_zscore", "composite_score",
    "SignalStrategy",
]
