"""报告渲染层测试。运行:.venv/bin/python tests/test_report.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from research.report import assemble_report, radar_svg, score_table_md


def test_radar_svg():
    svg = radar_svg({"盈利": 0.8, "成长": 0.6, "安全": 0.9, "分红": 0.5}, title="质量")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "viewBox" in svg and "质量" in svg
    assert svg.count("<polygon") >= 5          # 4 网格圈 + 1 数据多边形
    assert "盈利" in svg and "分红" in svg       # 维度标签


def test_radar_too_few_dims():
    svg = radar_svg({"a": 0.5, "b": 0.5})       # <3 维 → 空图
    assert svg.startswith("<svg") and "<polygon" not in svg


def test_score_table():
    md = score_table_md({"F-Score": 8, "Z-Score": 5.2})
    assert "| F-Score | 8 |" in md and md.startswith("| 指标 |")


def test_assemble_report():
    md = assemble_report(
        "600519.SH", "贵州茅台",
        {"F-Score": 8, "Z-Score": 5.2},
        {"财务健康": "盈利能力强劲,现金流充裕。", "风险点": "估值处于历史高位。"},
        "2023-12-31",
        radar=radar_svg({"盈利": 0.9, "成长": 0.7, "安全": 0.95, "分红": 0.6}),
    )
    assert "# 贵州茅台" in md and "非投资建议" in md
    assert "## 财务健康" in md and "## 风险点" in md
    assert "F-Score" in md and "<svg" in md     # 评分表 + 内嵌雷达图


if __name__ == "__main__":
    for fn in [test_radar_svg, test_radar_too_few_dims, test_score_table, test_assemble_report]:
        fn(); print(f"  ✓ {fn.__name__}")
    print("✅ 报告渲染层 全部通过")
