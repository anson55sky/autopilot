// H33 视觉证据脚手架：DOM 浮层与 canvas HUD 的几何相交检查（零依赖，node stdlib）。
//
// 为什么需要它：ContraRunner v1 的实证 —— 冻结矩阵里 A13 走 getImageData（DOM 层不进画布缓冲），
// 截图只验字节数，A17 只 grep Uncaught，于是"最高分芯片压住 LIVES 面板"这类回归**结构上抓不到**，
// 全靠验证者人工 A/B 像素对照才发现。本脚本把这一整类冲突变成一条可冻结的机器判据。
//
// 项目侧要做两件事（都属"外部可观察"，不是自证）：
//   1) 页面里把 HUD 矩形与所有 DOM 浮层矩形换算到 **canvas 坐标**，
//      写进 <script> 标签的 JSON（id="autopilot-geometry"），或另存一个静态探针页；
//   2) 用无头浏览器 dump-dom 抓下来，交给本脚本：
//        node .autopilot/checks/probe-geometry.mjs <A#> <dump.html> [重叠面积阈值(px²)]
//      在 run.sh 里的写法：
//        check A26 "浮层不得压住 HUD" sh -c "chrome --headless=new --dump-dom $URL > .autopilot/checks/geom.html \
//                && node .autopilot/checks/probe-geometry.mjs A26 .autopilot/checks/geom.html"
//
// 判据：任何浮层与任一 HUD 矩形的相交面积 > 阈值 → FAIL；没提供几何数据 → 由调用方判 SKIP
// （本脚本退 3 并打印 NOGEOMETRY，**不算 PASS**）。
import fs from 'node:fs';

const [, , AID, file, threshArg] = process.argv;
const THRESH = Number(threshArg || 0);
const id = AID || 'A??';

function out(verdict, msg) {
  console.log(`RESULT ${id} ${verdict} ${msg}`);
}

function collectRects(root, key, acc) {
  // 兼容两种写法：[x,y,w,h] 直接数组，或 {rect:[x,y,w,h]}
  for (const item of root || []) {
    const rect = Array.isArray(item) ? item : (item && item.rect);
    if (Array.isArray(rect) && rect.length === 4 && rect.every((n) => Number.isFinite(n))) acc.push(rect);
  }
}

let doc;
try {
  doc = fs.readFileSync(file, 'utf8');
} catch (e) {
  out('FAIL', `读不到 dump 产物 ${file}（先跑无头浏览器 --dump-dom）`);
  process.exit(1);
}

const block = /<script[^>]+id=["']autopilot-geometry["'][^>]*>([\s\S]*?)<\/script>/i.exec(doc);
if (!block) {
  console.log('NOGEOMETRY 页面未暴露 id="autopilot-geometry" 的几何数据');
  process.exit(3);
}
let data;
try {
  data = JSON.parse(block[1]);
} catch (e) {
  out('FAIL', `几何数据不是合法 JSON：${e.message}`);
  process.exit(1);
}

const hud = [];
const overlays = [];
collectRects(data.hud, 'hud', hud);
collectRects(data.overlays, 'overlays', overlays);
if (!hud.length || !overlays.length) {
  console.log('NOGEOMETRY hud 或 overlays 为空，无法判定（不算通过）');
  process.exit(3);
}

function area(a, b) {
  const w = Math.min(a[0] + a[2], b[0] + b[2]) - Math.max(a[0], b[0]);
  const h = Math.min(a[1] + a[3], b[1] + b[3]) - Math.max(a[1], b[1]);
  return w > 0 && h > 0 ? w * h : 0;
}

const bad = [];
for (let i = 0; i < overlays.length; i += 1) {
  for (let j = 0; j < hud.length; j += 1) {
    const a = area(overlays[i], hud[j]);
    if (a > THRESH) bad.push(`浮层#${i}[${overlays[i]}] 压住 HUD#${j}[${hud[j]}] 重叠 ${a.toFixed(1)}px²`);
  }
}
if (bad.length) {
  out('FAIL', `${bad.length} 处浮层与 HUD 相交 :: ${bad.slice(0, 3).join(' | ')}`);
  process.exit(1);
}
out('PASS', `${overlays.length} 个浮层 × ${hud.length} 个 HUD 矩形，重叠均 ≤ ${THRESH}px²`);
