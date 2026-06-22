"""DD 报告渲染层 —— 评分 → 雷达图 SVG、Markdown 表、报告组装。

纯渲染:LLM(agent+skill)负责生成各节**文字**,这里负责把"评分数据 + 文字"
拼成结构化 Markdown(可内嵌雷达图 SVG)。PDF 导出见 to_pdf(待集成 weasyprint/pandoc)。
数字一律来自上游确定性工具,本层只排版。
"""
from __future__ import annotations

import math
from typing import Dict, Mapping, Optional


def radar_svg(dims: Mapping[str, float], size: int = 320, title: str = "") -> str:
    """雷达图 SVG。dims: {维度名: 分数 0–1}。维度 <3 返回空图。"""
    keys = list(dims.keys())
    n = len(keys)
    if n < 3:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}"></svg>'
    cx = cy = size / 2
    R = size * 0.34

    def pt(i: int, r: float):
        a = -math.pi / 2 + 2 * math.pi * i / n
        return cx + r * math.cos(a), cy + r * math.sin(a)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
           f'viewBox="0 0 {size} {size}" font-family="sans-serif">']
    if title:
        out.append(f'<text x="{cx}" y="16" text-anchor="middle" font-size="13" font-weight="bold">{title}</text>')
    # 网格圈
    for g in (0.25, 0.5, 0.75, 1.0):
        ring = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, R * g) for i in range(n)))
        out.append(f'<polygon points="{ring}" fill="none" stroke="#ddd" stroke-width="1"/>')
    # 轴 + 维度标签
    for i, k in enumerate(keys):
        ex, ey = pt(i, R)
        out.append(f'<line x1="{cx}" y1="{cy}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="#ccc"/>')
        lx, ly = pt(i, R * 1.14)
        anchor = "middle" if abs(lx - cx) < 1 else ("start" if lx > cx else "end")
        out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
                   f'font-size="11" dominant-baseline="middle">{k}</text>')
    # 数据多边形
    data = " ".join(f"{x:.1f},{y:.1f}"
                    for x, y in (pt(i, R * max(0.0, min(1.0, dims[k]))) for i, k in enumerate(keys)))
    out.append(f'<polygon points="{data}" fill="#4f86c6" fill-opacity="0.4" stroke="#4f86c6" stroke-width="2"/>')
    out.append("</svg>")
    return "\n".join(out)


def score_table_md(scores: Mapping[str, object]) -> str:
    """综合评分 → Markdown 表。"""
    rows = ["| 指标 | 值 |", "|---|---|"]
    rows += [f"| {k} | {v} |" for k, v in scores.items()]
    return "\n".join(rows)


def assemble_report(ts_code: str, name: str, scores: Mapping[str, object],
                    sections: Mapping[str, str], as_of: str,
                    radar: Optional[str] = None) -> str:
    """组装 DD 式 Markdown 报告。sections:{节标题: LLM 生成文字}(有序)。"""
    md = [f"# {name}({ts_code}) 多元分析报告",
          f"> 数据截至 {as_of} · 全为研究分析,**非投资建议**", ""]
    if radar:
        md += [radar, ""]
    md += ["## 综合评分", score_table_md(scores), ""]
    for title, body in sections.items():
        md += [f"## {title}", "", body, ""]
    return "\n".join(md)


def to_pdf(markdown: str, path: str) -> None:  # 占位
    """Markdown → PDF。落地用 weasyprint(md→html→pdf)或 pandoc;Web 端也可前端导出。"""
    raise NotImplementedError("PDF 导出待集成 weasyprint/pandoc")
