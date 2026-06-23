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


def _empty_svg(w: int, h: int) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"></svg>'


_PALETTE = ["#378ADD", "#E24B4A", "#1D9E75", "#EF9F27", "#7F77DD", "#888780"]


def line_svg(series, x_labels, title: str = "", width: int = 440, height: int = 240) -> str:
    """折线图(可多条线)。series: dict{名称:[值]} 或 [(名称,[值])];x_labels 与值对齐。"""
    items = list(series.items()) if isinstance(series, dict) else list(series)
    allv = [v for _, vals in items for v in vals if v is not None]
    if not items or not x_labels or not allv:
        return _empty_svg(width, height)
    lo, hi = min(allv), max(allv)
    if lo == hi:
        hi = lo + 1
    span = hi - lo
    lo, hi = lo - span * 0.1, hi + span * 0.1
    ml, mr, mt, mb = 50, 16, 30 if title else 12, 30
    pw, ph, n = width - ml - mr, height - mt - mb, len(x_labels)

    def fx(i):
        return ml + (pw * i / (n - 1) if n > 1 else pw / 2)

    def fy(v):
        return mt + ph * (1 - (v - lo) / (hi - lo))

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="sans-serif">']
    if title:
        out.append(f'<text x="{width/2}" y="16" text-anchor="middle" font-size="13" font-weight="bold">{title}</text>')
    for g in range(5):
        yv = lo + (hi - lo) * g / 4
        yy = fy(yv)
        out.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{width-mr}" y2="{yy:.1f}" stroke="#eee"/>')
        out.append(f'<text x="{ml-6}" y="{yy+3:.1f}" text-anchor="end" font-size="10" fill="#999">{yv:.1f}</text>')
    for i, lab in enumerate(x_labels):
        out.append(f'<text x="{fx(i):.1f}" y="{height-mb+16}" text-anchor="middle" font-size="10" fill="#999">{lab}</text>')
    for ci, (name, vals) in enumerate(items):
        c = _PALETTE[ci % len(_PALETTE)]
        pts = [(fx(i), fy(v)) for i, v in enumerate(vals) if v is not None]
        if pts:
            out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" '
                       f'fill="none" stroke="{c}" stroke-width="2"/>')
            out += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{c}"/>' for x, y in pts]
    lx = ml
    for ci, (name, _) in enumerate(items):
        c = _PALETTE[ci % len(_PALETTE)]
        out.append(f'<rect x="{lx}" y="{height-11}" width="9" height="9" rx="1" fill="{c}"/>')
        out.append(f'<text x="{lx+12}" y="{height-3}" font-size="10" fill="#555">{name}</text>')
        lx += 12 + len(name) * 13 + 14
    out.append("</svg>")
    return "\n".join(out)


def grouped_bar_svg(data, categories, title: str = "", width: int = 460, height: int = 260) -> str:
    """分组柱状图(对标对比)。data: dict{组名:[值 per category]};categories: x 轴类别。"""
    items = list(data.items()) if isinstance(data, dict) else list(data)
    allv = [v for _, vals in items for v in vals if v is not None]
    if not items or not categories or not allv:
        return _empty_svg(width, height)
    lo, hi = min(0, min(allv)), max(allv)
    if lo == hi:
        hi = lo + 1
    ml, mr, mt, mb = 44, 12, 30 if title else 12, 42
    pw, ph = width - ml - mr, height - mt - mb
    ng, nb = len(categories), len(items)
    gw = pw / ng
    bw = gw * 0.8 / nb

    def fy(v):
        return mt + ph * (1 - (v - lo) / (hi - lo))

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="sans-serif">']
    if title:
        out.append(f'<text x="{width/2}" y="16" text-anchor="middle" font-size="13" font-weight="bold">{title}</text>')
    y0 = fy(0)
    out.append(f'<line x1="{ml}" y1="{y0:.1f}" x2="{width-mr}" y2="{y0:.1f}" stroke="#ccc"/>')
    for gi, cat in enumerate(categories):
        gx = ml + gw * gi
        for bi, (name, vals) in enumerate(items):
            v = vals[gi] if gi < len(vals) and vals[gi] is not None else None
            if v is None:
                continue
            bx, by = gx + gw * 0.1 + bw * bi, fy(v)
            out.append(f'<rect x="{bx:.1f}" y="{min(by, y0):.1f}" width="{bw:.1f}" '
                       f'height="{abs(by-y0):.1f}" rx="1" fill="{_PALETTE[bi % len(_PALETTE)]}"/>')
        out.append(f'<text x="{gx+gw/2:.1f}" y="{height-mb+15}" text-anchor="middle" font-size="10" fill="#999">{cat}</text>')
    lx = ml
    for bi, (name, _) in enumerate(items):
        c = _PALETTE[bi % len(_PALETTE)]
        out.append(f'<rect x="{lx}" y="{height-11}" width="9" height="9" rx="1" fill="{c}"/>')
        out.append(f'<text x="{lx+12}" y="{height-3}" font-size="10" fill="#555">{name}</text>')
        lx += 12 + len(name) * 13 + 14
    out.append("</svg>")
    return "\n".join(out)


def pie_svg(slices, title: str = "", size: int = 240) -> str:
    """饼图(构成,如主营/股东)。slices: dict{名称:值} 或 [(名称,值)]。"""
    items = [(k, v) for k, v in (slices.items() if isinstance(slices, dict) else slices) if v and v > 0]
    total = sum(v for _, v in items)
    if not items or total <= 0:
        return _empty_svg(size, size)
    cx, cy, r = size / 2, size / 2 + (8 if title else 0), size * 0.30
    h = size + len(items) * 16
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{h}" '
           f'viewBox="0 0 {size} {h}" font-family="sans-serif">']
    if title:
        out.append(f'<text x="{cx}" y="16" text-anchor="middle" font-size="13" font-weight="bold">{title}</text>')
    a0 = -math.pi / 2
    for ci, (name, v) in enumerate(items):
        frac = v / total
        a1 = a0 + 2 * math.pi * frac
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        large = 1 if frac > 0.5 else 0
        out.append(f'<path d="M{cx:.1f},{cy:.1f} L{x0:.1f},{y0:.1f} '
                   f'A{r:.1f},{r:.1f} 0 {large},1 {x1:.1f},{y1:.1f} Z" fill="{_PALETTE[ci % len(_PALETTE)]}"/>')
        a0 = a1
    ly = size
    for ci, (name, v) in enumerate(items):
        c = _PALETTE[ci % len(_PALETTE)]
        out.append(f'<rect x="16" y="{ly}" width="9" height="9" rx="1" fill="{c}"/>')
        out.append(f'<text x="30" y="{ly+8}" font-size="10" fill="#555">{name} {100*v/total:.0f}%</text>')
        ly += 16
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
        md += [f'<div class="chart">{radar}</div>', ""]   # 包 div:markdown 对 div 块原样保留,不把 SVG 塞进 <p>/autolink xmlns
    md += ["## 综合评分", score_table_md(scores), ""]
    for title, body in sections.items():
        md += [f"## {title}", "", body, ""]
    return "\n".join(md)


def to_pdf(markdown: str, path: str) -> None:  # 占位
    """Markdown → PDF。落地用 weasyprint(md→html→pdf)或 pandoc;Web 端也可前端导出。"""
    raise NotImplementedError("PDF 导出待集成 weasyprint/pandoc")
