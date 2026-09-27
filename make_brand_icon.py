#!/usr/bin/env python3
"""从 frontend/public/favicon.svg 单一源生成两样东西（避免手工复制漂移）：

1. frontend/public/apple-touch-icon.png —— 180x180 iOS 触屏图标（无头 Chrome 截图）；
2. preview-brand-icon.html —— 肉眼验收页（多尺寸 / 明暗底 / 浏览器标签模拟 / 与旧图标对比）。

内联 SVG 而非 <img src>：file:// 下 Chrome 对子资源 SVG 加载不可靠，
内联可保证预览与导出的渲染结果确定一致。
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
SVG = (ROOT / "frontend" / "public" / "favicon.svg").read_text(encoding="utf-8")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def inline(svg: str, size: int, extra: str = "") -> str:
    """把 svg 的 width/height 改写成目标像素（保留 viewBox，等比缩放）。"""
    out = re.sub(r'width="\d+"\s+height="\d+"', f'width="{size}" height="{size}"', svg, count=1)
    return out.replace("<svg ", f"<svg style=\"{extra}\" ", 1)


def main() -> int:
    cells = []
    for px in (16, 32, 48, 64, 180):
        cells.append(
            f'<figure><div class="slot">{inline(SVG, px)}</div>'
            f'<figcaption>{px}px</figcaption></figure>'
        )
    sizes_html = "\n".join(cells)

    # 标签页模拟：浅色 / 深色主题下图标在一排标签中的观感
    tab = inline(SVG, 16)
    tabs_light = "".join(
        f'<div class="tab{" active" if i == 1 else ""}">{tab}<span>常青圈 EvergreenCircle · 15 分钟生活圈智能体检与规划助手</span></div>'
        for i in range(4)
    )

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>品牌图标验收预览 · 常青圈 EvergreenCircle</title>
<style>
  :root {{
    --primary: #7c9885; --primary-deep: #5e7a66; --ink: #3a413c; --ink-2: #6b746c;
    --ink-3: #9aa39c; --line: #e3e8e3; --bg: #fafbf9; --card: #ffffff;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 32px; background: var(--bg); color: var(--ink);
         font-family: 'Inter','Noto Sans SC','PingFang SC',system-ui,sans-serif; font-size: 14px; }}
  h1 {{ font-size: 21px; margin: 0 0 4px; }}
  h2 {{ font-size: 15px; margin: 32px 0 12px; color: var(--ink-2); font-weight: 600; }}
  .sub {{ color: var(--ink-3); margin-bottom: 8px; }}
  .box {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 20px; }}
  .row {{ display: flex; gap: 28px; align-items: flex-end; flex-wrap: wrap; }}
  figure {{ margin: 0; text-align: center; }}
  figcaption {{ margin-top: 8px; color: var(--ink-3); font-size: 12px; font-variant-numeric: tabular-nums; }}
  .slot {{ display: grid; place-items: center; padding: 6px; }}
  .stage-dark {{ background: #1f2421; border-radius: 12px; padding: 20px; margin-top: 12px; }}
  .stage-dark figcaption {{ color: #8e9a92; }}
  .tabs {{ display: flex; gap: 6px; padding: 10px 10px 0; background: #dee1de; border-radius: 12px 12px 0 0; }}
  .tabs.dark {{ background: #2b302d; }}
  .tab {{ display: flex; align-items: center; gap: 8px; max-width: 260px; padding: 7px 12px;
          background: #f1f3f0; border-radius: 9px 9px 0 0; color: var(--ink-2); font-size: 12px;
          white-space: nowrap; overflow: hidden; }}
  .tab.active {{ background: #fff; color: var(--ink); }}
  .tabs.dark .tab {{ background: #383e3a; color: #9aa39c; }}
  .tabs.dark .tab.active {{ background: #464d48; color: #e6eae7; }}
  .cmp {{ display: flex; gap: 28px; align-items: flex-end; }}
  .bad {{ outline: 2px solid #ce9a92; outline-offset: 6px; border-radius: 4px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px;
            background: #ce9a9222; color: #a8625a; margin-bottom: 6px; }}
  .good {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px;
           background: #8ab58a22; color: #4f7a4f; margin-bottom: 6px; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px;
          background: #7c988518; padding: 1px 6px; border-radius: 5px; color: var(--primary-deep); }}
</style>
</head>
<body>
  <h1>品牌图标验收预览</h1>
  <p class="sub">源：<code>frontend/public/favicon.svg</code> · 取色 <code>#7c9885</code>（与侧边栏 logo 片同源）· 造型取自 <code>public/assets/brand/logo.png</code> 的嫩芽</p>

  <h2>1 · 多尺寸清晰度（浅底）</h2>
  <div class="box"><div class="row">{sizes_html}</div></div>

  <h2>2 · 深底适配（暗色主题浏览器）</h2>
  <div class="box"><div class="stage-dark"><div class="row">{sizes_html}</div></div></div>

  <h2>3 · 浏览器标签模拟</h2>
  <div class="box">
    <div class="tabs">{tabs_light}</div>
    <div style="height:14px;background:#f1f3f0"></div>
    <div class="tabs dark" style="margin-top:18px">{tabs_light}</div>
    <div style="height:14px;background:#383e3a"></div>
  </div>

  <h2>4 · 改动前后对比</h2>
  <div class="box">
    <div class="cmp">
      <figure>
        <div class="badge">改动前</div>
        <div class="slot bad">
          <svg width="64" height="64" viewBox="0 0 48 46"><path fill="#863bff" d="M25.946 44.938c-.664.845-2.021.375-2.021-.698V33.937a2.26 2.26 0 0 0-2.262-2.262H10.287c-.92 0-1.456-1.04-.92-1.788l7.48-10.471c1.07-1.497 0-3.578-1.842-3.578H1.237c-.92 0-1.456-1.04-.92-1.788L10.013.474c.214-.297.556-.474.92-.474h28.894c.92 0 1.456 1.04.92 1.788l-7.48 10.471c-1.07 1.498 0 3.579 1.842 3.579h11.377c.943 0 1.473 1.088.89 1.83L25.947 44.94z"/></svg>
        </div>
        <figcaption>紫色 #863bff 默认占位图<br>与品牌毫无关系</figcaption>
      </figure>
      <figure>
        <div class="good">改动后</div>
        <div class="slot">{inline(SVG, 64)}</div>
        <figcaption>品牌色嫩芽<br>与 logo / 侧边栏一致</figcaption>
      </figure>
      <figure>
        <div class="good">源品牌资源</div>
        <div class="slot"><img src="frontend/public/assets/brand/logo.png" width="64" height="64" alt="logo"></div>
        <figcaption>public/assets/brand/logo.png<br>（造型来源）</figcaption>
      </figure>
    </div>
  </div>
</body>
</html>
"""
    (ROOT / "preview-brand-icon.html").write_text(html, encoding="utf-8")
    print("已生成 preview-brand-icon.html")

    # 180x180 PNG：单独一页只放图，保证截图尺寸精确、无滚动条
    out = ROOT / "frontend" / "public" / "apple-touch-icon.png"
    with tempfile.TemporaryDirectory(prefix="verda-icon-") as tmp:
        render = pathlib.Path(tmp) / "render180.html"
        render.write_text(
            "<!doctype html><html><head><meta charset='utf-8'><style>"
            "html,body{margin:0;padding:0;width:180px;height:180px;overflow:hidden;background:transparent}"
            "</style></head><body>" + inline(SVG, 180) + "</body></html>",
            encoding="utf-8",
        )
        cmd = [
            CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--window-size=180,180",
            "--default-background-color=00000000",
            f"--screenshot={out}", render.as_uri(),
        ]
        subprocess.run(cmd, capture_output=True, text=True)

    if not out.exists():
        print(f"PNG 生成失败：未找到浏览器内核 {CHROME}（仅 macOS 本地需要）", file=sys.stderr)
        return 1
    print(f"已生成 {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
