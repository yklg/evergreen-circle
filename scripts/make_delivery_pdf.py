#!/usr/bin/env python3
"""交付文档 Markdown → PDF 生成器（weasyprint）。

为什么要有这颗脚本：`docs/常青圈_作品介绍.md:16` 把「本文档（PDF）」列为提交物料，而 PDF 是
md 的**产物** —— 产物一旦落后于源，评审拿到的就是带着旧数字的那份，且没有任何判据会报警
（本仓文档层零守卫）。改 md 之后重跑本脚本即可。

依赖：weasyprint + markdown（本机用 `/opt/homebrew/bin/python3`，backend/.venv 里没有装）。

用法：
    /opt/homebrew/bin/python3 scripts/make_delivery_pdf.py docs/常青圈_作品介绍.md
    /opt/homebrew/bin/python3 scripts/make_delivery_pdf.py docs/*.md --dry-run   # 只报不落盘
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import markdown
    from weasyprint import HTML
except ImportError as exc:  # pragma: no cover - 环境缺依赖时的显式出口
    sys.exit(f"缺依赖 {exc.name}：请用带 weasyprint/markdown 的解释器跑（本机 /opt/homebrew/bin/python3）")

REPO_ROOT = Path(__file__).resolve().parent.parent

CSS = """
@page {
  size: A4;
  margin: 20mm 16mm 18mm 16mm;
  @bottom-center { content: counter(page) " / " counter(pages); font-size: 8.5pt; color: #666; }
}
body { font-family: "PingFang SC", "Hiragino Sans GB", sans-serif; font-size: 10pt; line-height: 1.62; color: #17201c; }
h1 { font-size: 17pt; margin: 0 0 6pt; }
h2 { font-size: 13.5pt; margin: 20pt 0 6pt; border-bottom: 1.2pt solid #0f6b4f; padding-bottom: 3pt; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 14pt 0 4pt; break-after: avoid; }
h4 { font-size: 10.5pt; margin: 10pt 0 3pt; break-after: avoid; }
p, ul, ol { margin: 0 0 6pt; }
code, pre { font-family: Menlo, "SF Mono", monospace; font-size: 8.8pt; }
pre { background: #f4f6f5; border: 0.5pt solid #d8dedb; border-radius: 3pt; padding: 6pt 8pt; white-space: pre-wrap; break-inside: avoid; }
code { background: #f4f6f5; padding: 0 2pt; }
pre code { background: none; padding: 0; }
table { width: 100%; border-collapse: collapse; margin: 4pt 0 10pt; font-size: 9.2pt; break-inside: auto; }
th, td { border: 0.5pt solid #cfd6d2; padding: 3.5pt 5pt; vertical-align: top; text-align: left; }
th { background: #eef2f0; font-weight: 600; }
/* 标签/取值型表格：让首列贴着自己的内容，别把「参赛赛道」这类短标签挤成竖排 */
td:first-child, th:first-child { width: 1%; white-space: nowrap; }
/* 但宽表（能力矩阵那种首列就是长句）不许被这条规则压垮 */
td.wrap-first, table.wide td:first-child, table.wide th:first-child { white-space: normal; width: auto; }
blockquote { margin: 0 0 8pt; padding: 4pt 10pt; border-left: 2.5pt solid #0f6b4f; background: #f6faf8; color: #33413b; }
a { color: #0f6b4f; text-decoration: none; }
hr { border: none; border-top: 0.5pt solid #d8dedb; margin: 12pt 0; }
"""


def render(md_path: Path) -> bytes:
    text = md_path.read_text(encoding="utf-8")
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
        output_format="html5",
    )
    doc = f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><style>{CSS}</style></head><body>{body}</body></html>"
    return HTML(string=doc, base_url=str(md_path.parent)).write_pdf()


def main() -> int:
    ap = argparse.ArgumentParser(description="把交付文档 md 重出成同名 PDF")
    ap.add_argument("targets", nargs="+", type=Path, help="要转换的 .md（可多个）")
    ap.add_argument("--out-dir", type=Path, default=None, help="输出目录，默认与源 md 同目录")
    ap.add_argument("--dry-run", action="store_true", help="只渲染并报告字节数，不落盘")
    args = ap.parse_args()

    for md in args.targets:
        if md.suffix.lower() != ".md" or not md.is_file():
            print(f"跳过（不是已存在的 .md）：{md}", file=sys.stderr)
            continue
        pdf_bytes = render(md)
        out = (args.out_dir or md.parent) / (md.stem + ".pdf")
        if args.dry_run:
            print(f"[dry-run] {md} → {out}（{len(pdf_bytes):,} 字节，未写盘）")
            continue
        out.write_bytes(pdf_bytes)
        print(f"{md} → {os.path.relpath(out, REPO_ROOT)}（{len(pdf_bytes):,} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
