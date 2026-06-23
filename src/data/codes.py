"""股票代码规范化 —— 支持带/不带市场后缀输入,统一成 tushare 格式(600519 → 600519.SH)。"""
from __future__ import annotations


def to_ts_code(code: str) -> str:
    """规范化为带市场后缀的 tushare 代码。

    - 已带后缀(含 ".") → 大写原样;
    - 纯数字按首位前缀补后缀:6/9→SH(沪主板/科创/B股)、0/2/3→SZ(深主板/B股/创业)、4/8→BJ(北交所);
    - 非纯数字(如名称)→ 原样返回,交由上层处理。
    """
    c = (code or "").strip().upper()
    if not c or "." in c:
        return c
    if not c.isdigit():
        return c
    if c[0] in "69":
        return f"{c}.SH"
    if c[0] in "023":
        return f"{c}.SZ"
    if c[0] in "48":
        return f"{c}.BJ"
    return c
