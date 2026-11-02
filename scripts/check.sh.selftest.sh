#!/bin/sh
# check.sh 自测：在 mktemp -d fixture 上真跑，零浏览器依赖（run 模式直接调 fixture 里的假 run.sh）。
# 用法: sh check.sh.selftest.sh
# 输出: RESULT C<n> PASS|FAIL - 说明；任何 FAIL → 退出 1。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CHECK="$HERE/check.sh"

T=$(mktemp -d "${TMPDIR:-/tmp}/autopilot-selftest.XXXXXX") || { echo "mktemp 失败" >&2; exit 1; }
trap 'rm -rf "$T"' EXIT
REPO="$T/repo"
AP="$REPO/.autopilot"
CH="$AP/checks"
mkdir -p "$CH"

PASS=0; FAIL=0
ok()  { echo "RESULT C$1 PASS - $2"; PASS=$((PASS + 1)); }
bad() { echo "RESULT C$1 FAIL - $2"; FAIL=$((FAIL + 1)); }

runsh_v1='#!/bin/sh
echo "RESULT A1 PASS"
echo "RESULT A2 PASS"
exit 0
'
write_runsh() { printf '%s' "$1" > "$CH/run.sh"; }

# ---- fixture 初始：run.sh v1，冻结 ----
write_runsh "$runsh_v1"
chmod +x "$CH/run.sh"

# C1 freeze → verify 一致
if sh "$CHECK" freeze "$REPO" >/dev/null 2>&1 && sh "$CHECK" verify "$REPO" >/dev/null 2>&1; then
  ok 1 "freeze 后 verify 通过"
else
  bad 1 "freeze 后 verify 未通过"
fi

# C2 篡改 checks 内文件 → verify 退出 4
printf '# tampered\n' >> "$CH/run.sh"
rc=0; sh "$CHECK" verify "$REPO" >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 4 ]; then ok 2 "篡改后 verify 退出 4"; else bad 2 "篡改后 verify 退出 $rc（期望 4）"; fi

# C3 恢复后再过
write_runsh "$runsh_v1"
if sh "$CHECK" verify "$REPO" >/dev/null 2>&1; then ok 3 "恢复后 verify 通过"; else bad 3 "恢复后 verify 未通过"; fi

# C4 MANIFEST 行格式：./ 前缀 + 两个空格 + 64hex，全部行合规
if [ -s "$CH/MANIFEST.sha256" ] \
   && [ "$(grep -Ec '^[0-9a-f]{64}  \./' "$CH/MANIFEST.sha256")" = "$(wc -l < "$CH/MANIFEST.sha256" | tr -d ' ')" ] \
   && ! grep -Eq '	| $' "$CH/MANIFEST.sha256"; then
  ok 4 "MANIFEST 行格式合规（64hex+两空格+./相对路径）"
else
  bad 4 "MANIFEST 行格式不合规"
fi

# C5 三种产物文件不改变 MANIFEST
printf 'log\n' > "$CH/last.log"
printf '{}\n' > "$CH/last-result.json"
printf 'x' > "$CH/.DS_Store"
cp "$CH/MANIFEST.sha256" "$T/m.before"
if sh "$CHECK" verify "$REPO" >/dev/null 2>&1 && sh "$CHECK" freeze "$REPO" >/dev/null 2>&1 \
   && cmp -s "$T/m.before" "$CH/MANIFEST.sha256"; then
  ok 5 "last.log/last-result.json/.DS_Store 不进 MANIFEST"
else
  bad 5 "产物文件污染了 MANIFEST 或 verify 失败"
fi

# C6 .autopilot/environment.json 不在哈希范围
printf '{"schema_version":"0.9"}\n' > "$AP/environment.json"
if sh "$CHECK" freeze "$REPO" >/dev/null 2>&1 && cmp -s "$T/m.before" "$CH/MANIFEST.sha256"; then
  ok 6 "environment.json 不在哈希范围"
else
  bad 6 "environment.json 被 freeze 扫进 MANIFEST"
fi

# C7 并发 run：第二个排队等待后成功，且打印锁行为
write_runsh '#!/bin/sh
sleep 2
echo "RESULT A1 PASS"
exit 0
'
sh "$CHECK" freeze "$REPO" >/dev/null 2>&1
sh "$CHECK" run "$REPO" >"$T/run1.out" 2>&1 &
pid1=$!
sleep 0.5
AUTOPILOT_LOCK_TIMEOUT=30 sh "$CHECK" run "$REPO" >"$T/run2.out" 2>&1
rc2=$?
wait "$pid1"
if [ "$rc2" -eq 0 ] && grep -q '另一 run' "$T/run2.out" && grep -q 'RESULT A1 PASS' "$CH/last.log"; then
  ok 7 "并发 run：第二个排队等待后成功（锁行为已打印）"
else
  bad 7 "并发 run 异常：rc2=$rc2（期望 0，且应打印等待锁信息）"
fi

# C8 持锁者活着 → 等待超时退出 5
sleep 5 & holder=$!
mkdir -p "$AP/locks/run.lock"
echo "$holder" > "$AP/locks/run.lock/pid"
rc=0; AUTOPILOT_LOCK_TIMEOUT=1 sh "$CHECK" run "$REPO" >/dev/null 2>&1 || rc=$?
kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null
rm -rf "$AP/locks/run.lock"
if [ "$rc" -eq 5 ]; then ok 8 "锁等待超时退出 5"; else bad 8 "锁超时退出 $rc（期望 5）"; fi

# C9 杀持有者后陈旧锁可抢占并打印警告
dead=0
sh -c 'exit 0' & dead=$!
wait "$dead"
mkdir -p "$AP/locks/run.lock"
echo "$dead" > "$AP/locks/run.lock/pid"
sh "$CHECK" run "$REPO" >"$T/run3.out" 2>&1
rc=$?
if [ "$rc" -eq 0 ] && grep -q '陈旧锁' "$T/run3.out"; then
  ok 9 "陈旧锁被抢占并打印警告"
else
  bad 9 "陈旧锁抢占异常：rc=$rc（期望 0 且打印警告）"
fi

# C10 混合结果：有真 PASS 也有 SKIP → 退出 0，skipped 含 A9，stdout 有警示行
write_runsh '#!/bin/sh
echo "RESULT A8 PASS - 有一条真过的"
echo "RESULT A9 SKIP - 浏览器不可用"
exit 0
'
sh "$CHECK" freeze "$REPO" >/dev/null 2>&1
sh "$CHECK" run "$REPO" >"$T/run4.out" 2>&1
rc=$?
if [ "$rc" -eq 0 ] && grep -q '"A9"' "$CH/last-result.json" \
   && grep -q '>>> 存在 SKIP，不得宣称全绿' "$T/run4.out"; then
  ok 10 "SKIP：有真 PASS 时退出 0，skipped 含 A9，警示行在 stdout"
else
  bad 10 "SKIP 场景异常：rc=$rc（期望 0 + skipped[A9] + 警示行）"
fi

# C17 0 条真 PASS（全是 SKIP）→ 退出 1 并明写未完成（H39：lite 起草不出判据时不许粉饰）
write_runsh '#!/bin/sh
echo "RESULT A9 SKIP - 自动起草时探测不到判定手段"
exit 0
'
sh "$CHECK" freeze "$REPO" >/dev/null 2>&1
sh "$CHECK" run "$REPO" >"$T/run4b.out" 2>&1
rc=$?
if [ "$rc" -eq 1 ] && grep -q '>>> 没有任何一条真 PASS' "$T/run4b.out" \
   && python3 -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); sys.exit(0 if not d["passed"] and d["skipped"] else 1)' "$CH/last-result.json"; then
  ok 17 "全 SKIP（0 条真 PASS）：退出 1 且明写「本轮未完成」，passed 里没有任何东西"
else
  bad 17 "全 SKIP 仍被当成成功：rc=$rc（期望 1 + 未完成行）"
fi

# C11 假 run.sh 输出 FAIL → 退出 1
write_runsh '#!/bin/sh
echo "RESULT B1 FAIL - 故意失败"
exit 0
'
sh "$CHECK" freeze "$REPO" >/dev/null 2>&1
rc=0; sh "$CHECK" run "$REPO" >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 1 ]; then ok 11 "FAIL：run 退出 1"; else bad 11 "FAIL 场景退出 $rc（期望 1）"; fi

# C12 freeze 拒绝含 TODO-check 的 run.sh（退出 2）
write_runsh '#!/bin/sh
# TODO-check: 未完成
exit 0
'
rc=0; sh "$CHECK" freeze "$REPO" >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 2 ]; then ok 12 "freeze 拒绝 TODO-check（退出 2）"; else bad 12 "TODO-check 拒绝退出 $rc（期望 2）"; fi

# C13 未知子命令 → 退出 2
rc=0; sh "$CHECK" bogus "$REPO" >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 2 ]; then ok 13 "未知子命令退出 2"; else bad 13 "未知子命令退出 $rc（期望 2）"; fi

# ---- H38：冻结前覆盖闸门（GOAL 矩阵 vs checks 判定源）
write_runsh '#!/bin/sh
NODE_IDS=(A1)
echo "RESULT A1 PASS"
echo "RESULT A2 PASS"
exit 0
'
chmod +x "$CH/run.sh"
printf '%s\n' '# GOAL' '' '## 验收矩阵' '' '| A# | 条目 | 判定 |' '| --- | --- | --- |' \
  '| A1 | x | y |' '| A2 | x | y |' '| A3 | 还没有判定源 | z |' > "$AP/GOAL.md"

# C14 有条目查无判定源 → freeze 退 24，且不写 MANIFEST
rm -f "$CH/MANIFEST.sha256"
rc=0; out=$(sh "$CHECK" freeze "$REPO" 2>&1) || rc=$?
if [ "$rc" -eq 24 ] && ! [ -f "$CH/MANIFEST.sha256" ] && printf '%s' "$out" | grep -q "A3"; then
  ok 14 "freeze 拒绝把「契约有、checks 里没有判定源」的条目冻进 MANIFEST（退 24 且零写盘）"
else
  bad 14 "覆盖闸门未生效：rc=$rc manifest=$([ -f "$CH/MANIFEST.sha256" ] && echo 有 || echo 无)"
fi

# C15 短理由不放行；带 AUTOPILOT_FREEZE_ALLOW_PARTIAL 的长理由才放行，并落账本
rc=0; AUTOPILOT_FREEZE_ALLOW_PARTIAL="理由太短" sh "$CHECK" freeze "$REPO" >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 24 ]; then ok 16 "分批冻结的短理由被拒（空话挡不住闸门）"; else bad 16 "短理由却放行：rc=$rc"; fi
rc=0
AUTOPILOT_FREEZE_ALLOW_PARTIAL="A3 需要手柄探针页，本轮先冻结已实现的工装范围，下一轮补" \
  sh "$CHECK" freeze "$REPO" >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 0 ] && [ -f "$CH/MANIFEST.sha256" ] && grep -q '"coverage_partial"' "$AP/ledger.jsonl"; then
  ok 15 "AUTOPILOT_FREEZE_ALLOW_PARTIAL 放行分批冻结：MANIFEST 落盘且理由进账本（可审计）"
else
  bad 15 "分批冻结路径不通：rc=$rc manifest=$([ -f "$CH/MANIFEST.sha256" ] && echo 有 || echo 无)"
fi

# C18 冻结内容快照落盘（H42：只存哈希证明不了「只更严」，必须能逐行对账）
if [ -f "$AP/frozen-checks.tar" ] && tar -tf "$AP/frozen-checks.tar" 2>/dev/null | grep -q '^\./run\.sh$'; then
  ok 18 "freeze 同时存下内容快照 frozen-checks.tar，且含判定文件"
else
  bad 18 "冻结内容快照缺失或不含 run.sh"
fi

# C19 快照不进 checks/（否则会自己触发漂移），且 MANIFEST 里没有它
if [ ! -e "$CH/frozen-checks.tar" ] && ! grep -q 'frozen-checks' "$CH/MANIFEST.sha256"; then
  ok 19 "快照落在 .autopilot/ 下且不进哈希范围（不会自己触发漂移）"
else
  bad 19 "快照位置不对：混进了冻结范围"
fi

# C20 漂移时 verify 直接给出逐行对账命令（让「尺子有没有被放宽」变成可查事实）
cp "$CH/run.sh" "$AP/run.sh.bak"
printf '# tampered again\n' >> "$CH/run.sh"
rc=0; out=$(sh "$CHECK" verify "$REPO" 2>&1) || rc=$?
if [ "$rc" -eq 4 ] && printf '%s\n' "$out" | grep -q 'diff -u' && printf '%s\n' "$out" | grep -q 'run.sh'; then
  ok 20 "漂移输出附带可执行的 diff -u 对账命令，并点名漂移文件"
else
  bad 20 "漂移没给出对账命令：rc=$rc"
fi

# C21 快照里的内容确实等于冻结态（用它还原即可复绿）
cp "$AP/run.sh.bak" "$CH/run.sh"
if sh "$CHECK" verify "$REPO" >/dev/null 2>&1; then
  ok 21 "还原后 verify 复绿（快照与盘上内容同源，可作恢复依据）"
else
  bad 21 "还原后 verify 仍红，快照与哈希不同源"
fi

echo "SELFTEST: $PASS 通过 / $FAIL 失败"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
