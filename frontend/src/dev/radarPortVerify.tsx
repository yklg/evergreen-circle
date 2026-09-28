/**
 * 雷达图移植 · 落地后复验出口（SSR 出可双击的单文件）
 *
 * 与预览闸的区别：预览闸要拍"要不要这么做"，所以画了现状/修复后两行；
 * 本文件只验**移植后的真实生产组件**在四档真实卡片宽度里是否仍零裁切、字号是否 ≥10.7。
 * 渲染体是 `components/lifecircle/MiniRadar` 本体，几何是 `lib/radarLayout` 本体 —— 无镜像副本。
 *
 * 跑法：`npx vite-node src/dev/radarPortVerify.tsx`
 * 产物写到仓库外的 workspace：`预览-雷达图移植-2026-09-28/雷达图移植后复验.html`
 */
import { writeFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { MiniRadar } from '../components/lifecircle/MiniRadar'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import type { LivingCircleReport } from '../types'

const OUT = '/Users/yilukaige/便民15分钟/预览-雷达图移植-2026-09-28/雷达图移植后复验.html'

const report = getLivingCircleReportMock('lc-kaili')?.living_circle as LivingCircleReport

/** 四档真实卡片内容区宽度：三处挂载点 × 各断点，内边距按生产 class 取值 */
const MOUNTS = [
  { contentW: 240, pad: 20, cap: '内容区 240px', note: 'ComparePage ≤360px 视口（最窄一档，小于派生宽 242）' },
  { contentW: 288, pad: 16, cap: '内容区 288px', note: 'LifeCirclePage lg · 右栏 320 − p-4×2' },
  { contentW: 312, pad: 20, cap: '内容区 312px', note: 'ComparePage md · 双卡 − p-5×2' },
  { contentW: 337, pad: 16, cap: '内容区 337px', note: '报告中心 LifeCircleReportView lg · 1fr 右栏' },
]

const rows = MOUNTS.map(
  (m) => {
    const outer = m.contentW + m.pad * 2 + 2
    return `<div style="width:${outer}px">
  <div style="font-size:11.5px;color:#6b7280;margin-bottom:6px;line-height:1.5">
    <b style="color:#2b333b;font-size:12px">${m.cap}</b><span style="display:block">${m.note}</span>
  </div>
  <div class="rounded-card border border-line bg-card shadow-card" style="width:${outer}px;padding:${m.pad}px">
    <div class="flex items-end justify-between">
      <div>
        <div class="text-aux font-semibold text-ink">${report.scene.name} · 体检单</div>
        <div class="text-tag text-ink-3">${report.scene.city}</div>
      </div>
      <div class="text-right"><div class="text-tag text-ink-3">综合评分</div></div>
    </div>
    <div class="radar-slot mt-3 border-t border-line pt-3">${renderToStaticMarkup(
      <MiniRadar report={report} />,
    )}</div>
  </div>
</div>`
  },
).join('\n')

const shim = `
*{box-sizing:border-box}
body{margin:0;padding:26px 28px 60px;background:#fafbf9;color:#3a413c;
     font:15px/1.7 'Inter','Noto Sans SC','PingFang SC',system-ui,sans-serif;-webkit-font-smoothing:antialiased}
h1{font-size:20px;font-weight:600;margin:0 0 6px}
h2{font-size:16px;margin:30px 0 6px;padding-left:10px;border-left:4px solid #5F7B69}
.rounded-card{border-radius:16px}
.border{border-width:1px;border-style:solid}
.border-t{border-top-width:1px;border-top-style:solid}
.border-line{border-color:#e3e8e3}
.bg-card{background:#fff}
.shadow-card{box-shadow:0 4px 24px rgba(124,152,133,.08)}
.flex{display:flex}.items-end{align-items:flex-end}.justify-between{justify-content:space-between}
.text-right{text-align:right}
.text-aux{font-size:13px;line-height:1.6}.text-tag{font-size:11px;line-height:1.4}
.font-semibold{font-weight:600}.text-ink{color:#3a413c}.text-ink-3{color:#9aa39c}
.mt-3{margin-top:12px}.pt-3{padding-top:12px}
.mx-auto{margin-left:auto;margin-right:auto}.block{display:block}.h-auto{height:auto}.w-full{width:100%}
table{border-collapse:collapse;font-size:12px;margin-top:10px;background:#fff}
th,td{border:1px solid #e3e8e3;padding:4px 9px;text-align:right}
th:first-child,td:first-child{text-align:left}
.bad{color:#b4232c;font-weight:600}.good{color:#1f7a45}
.lede{background:#fff;border:1px solid #e3e8e5;border-radius:10px;padding:14px 16px;margin:10px 0 0;font-size:13px;line-height:1.65}
.lede b{color:#8a6420}
code{background:#f1f5f2;border-radius:4px;padding:0 4px;font-size:12px}
.row{display:flex;flex-wrap:wrap;gap:18px;align-items:flex-start}
`

const audit = `
function auditRadar(){
  const rows=[];
  document.querySelectorAll('.radar-slot > svg').forEach(function(svg){
    const vb=svg.viewBox.baseVal, r=Number(svg.dataset.r||74), strokeHalf=1;
    const line=svg.querySelector('line');
    const ccx=line?Number(line.getAttribute('x1')):vb.width/2;
    const ccy=line?Number(line.getAttribute('y1')):vb.height/2;
    const host=svg.closest('.rounded-card');
    svg.querySelectorAll('text').forEach(function(t){
      const bb=t.getBBox(), rect=t.getBoundingClientRect();
      const scale=bb.width>0?rect.width/bb.width:1;
      const nx=Math.min(Math.max(ccx,bb.x),bb.x+bb.width);
      const ny=Math.min(Math.max(ccy,bb.y),bb.y+bb.height);
      rows.push({card:host?Math.round(host.clientWidth):-1,vbW:vb.width,vbH:vb.height,label:t.textContent,
        mL:+bb.x.toFixed(2),mT:+bb.y.toFixed(2),mR:+(vb.width-(bb.x+bb.width)).toFixed(2),
        mB:+(vb.height-(bb.y+bb.height)).toFixed(2),
        ring:+(Math.hypot(ccx-nx,ccy-ny)-(r+strokeHalf)).toFixed(2),
        cssFont:+(scale*Number(t.getAttribute('font-size'))).toFixed(2),
        clipped:bb.x<0||bb.y<0||bb.x+bb.width>vb.width||bb.y+bb.height>vb.height});
    });
  });
  return rows;
}
function renderAudit(){
  const rows=auditRadar(), box=document.getElementById('audit'), v=document.getElementById('verdict');
  let bad=0;
  let html='<table><tr><th>卡片实宽</th><th>viewBox</th><th>标签</th><th>左余量</th><th>上余量</th><th>右余量</th><th>下余量</th><th>到外环净空</th><th>实际CSS字号</th></tr>';
  rows.forEach(function(x){
    const neg=function(n){return n<0?'<td class="bad">'+n+'</td>':'<td>'+n+'</td>'};
    if(x.clipped||x.ring<0||x.cssFont<10.7) bad++;
    html+='<tr><td>'+x.card+'</td><td>'+x.vbW+'×'+x.vbH+'</td><td>'+x.label+'</td>'+
          neg(x.mL)+neg(x.mT)+neg(x.mR)+neg(x.mB)+neg(x.ring)+'<td>'+x.cssFont+'</td></tr>';
  });
  html+='</table>';
  box.innerHTML=html;
  v.textContent = bad===0
    ? '复验通过：真实生产组件在 4 档卡片里 8×4=32 个标签零裁切、到外环净空均 ≥ 0、实际 CSS 字号 ≥ 10.7'
    : '复验不合格：'+bad+' 项越界或字号跌破 10.7';
  v.className = bad===0?'good':'bad';
}
window.__auditRadar=auditRadar; window.__renderAudit=renderAudit;
window.addEventListener('load',function(){setTimeout(renderAudit,150)});
`

const html = `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>复验 · 雷达图移植后真实组件量尺</title>
<style>${shim}</style></head><body>
<h1>雷达图移植后复验 · 真实生产组件 × 四档卡片宽度</h1>
<div class="lede">
  渲染体是 <code>components/lifecircle/MiniRadar.tsx</code> 本体，几何由它内部的
  <code>lib/radarLayout.ts</code> 派生，<b>本探针不读分数、也不持有任何几何常量</b>
  （读分数会让 <code>visitorUnrated</code> 的消费点棘轮把探针登记成回归面，而它只是渲染出口）。
  数据为真实夹具 <code>kaili.json</code> 的 8 维（含 <code>养老 0.0</code> 塌到圆心）。
  页底表格由打开本页时的真实 Chrome
  <code>getBBox()</code> 现量：判据是「零裁切 + 到外环净空 ≥ 0 + 实际 CSS 字号 ≥ 10.7」。
  最窄一档（240px 内容区）预期字号 <b>10.91px</b> —— 已拍板接受的一档。
</div>
<h2>移植后（真实组件）</h2>
<div class="row">
${rows}
</div>
<div id="verdict" style="margin-top:28px;font-weight:600">自检尚未运行</div>
<div id="audit"></div>
<script>${audit}</script>
</body></html>
`

writeFileSync(OUT, html)
console.log(OUT)
console.log('量尺读数不在这里 —— 由页面内 getBBox 现量，见截图表格与 verdict 行')
