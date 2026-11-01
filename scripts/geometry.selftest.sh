#!/bin/sh
# H33 视觉证据脚手架自测：A-vg-01..04。跑的是随包模板 templates/checks/probe-geometry.mjs。
# 需要本机有 node（判据本身依赖无头浏览器，这里只测几何判定逻辑）；没有 node 时整脚本按 SKIP 退出 0。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL=$(cd "$HERE/.." && pwd)
PROBE="$SKILL/templates/checks/probe-geometry.mjs"
TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPROOT"' EXIT INT TERM

if ! command -v node >/dev/null 2>&1; then
  printf 'SKIP 本测试需要 node（未安装），不宣称通过\n'
  exit 0
fi

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

dump() {  # $1=文件 $2=JSON
    printf '<html><body><script type="application/json" id="autopilot-geometry">%s</script></body></html>\n' \
        "$2" > "$1"
}

# 1) 重叠必须判 FAIL
f="$TMPROOT/overlap.html"
dump "$f" '{"hud":[{"rect":[8,8,122,24]}],"overlays":[{"rect":[10,10,80,20]}]}'
out=$(node "$PROBE" A99 "$f" 2>&1); rc=$?
if [ "$rc" = "1" ] && printf '%s' "$out" | grep -q "RESULT A99 FAIL"; then
  pass 1 "浮层压住 HUD 时判 FAIL（v1 报告 §4 那一类回归现在抓得到）"
else
  fail 1 "重叠没判红：rc=$rc $out"
fi

# 2) 不重叠判 PASS
f2="$TMPROOT/clear.html"
dump "$f2" '{"hud":[{"rect":[8,8,122,24]}],"overlays":[{"rect":[300,200,80,20]}]}'
out=$(node "$PROBE" A99 "$f2" 2>&1); rc=$?
if [ "$rc" = "0" ] && printf '%s' "$out" | grep -q "RESULT A99 PASS"; then
  pass 2 "无相交时判 PASS，并给出矩形数量"
else
  fail 2 "干净场景被误判：rc=$rc $out"
fi

# 3) 阈值可调：允许 100px² 以内的贴边
f3="$TMPROOT/tiny.html"
dump "$f3" '{"hud":[{"rect":[8,8,122,24]}],"overlays":[{"rect":[8,8,4,20]}]}'
node "$PROBE" A99 "$f3" 0 >/dev/null 2>&1; rc0=$?
node "$PROBE" A99 "$f3" 100 >/dev/null 2>&1; rc100=$?
if [ "$rc0" = "1" ] && [ "$rc100" = "0" ]; then
  pass 3 "重叠阈值生效（0 判红、100px² 容差放行）"
else
  fail 3 "阈值不起作用：rc0=$rc0 rc100=$rc100"
fi

# 4) 没有几何数据时绝不给 PASS（防"探针空转算绿"，A15 的老坑）
f4="$TMPROOT/nodata.html"
printf '<html><body>nothing</body></html>\n' > "$f4"
out=$(node "$PROBE" A99 "$f4" 2>&1); rc=$?
if [ "$rc" = "3" ] && printf '%s' "$out" | grep -q "NOGEOMETRY" \
   && ! printf '%s' "$out" | grep -q "RESULT A99 PASS"; then
  pass 4 "页面没暴露几何数据时退 3 并打 NOGEOMETRY，调用方须按 SKIP 处理"
else
  fail 4 "空数据被当成通过了：rc=$rc $out"
fi

# 5) 残缺数据也不能 PASS
f5="$TMPROOT/partial.html"
dump "$f5" '{"hud":[{"rect":[8,8,122,24]}],"overlays":[]}'
out=$(node "$PROBE" A99 "$f5" 2>&1); rc=$?
if [ "$rc" = "3" ]; then
  pass 1 "hud 有、overlays 为空同样不给结论（退 3）"
else
  fail 1 "半边数据被误判：rc=$rc $out"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
