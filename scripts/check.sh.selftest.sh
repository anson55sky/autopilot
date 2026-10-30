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

# C10 假 run.sh 输出 SKIP → 退出 0，skipped 含 A9，stdout 有警示行
write_runsh '#!/bin/sh
echo "RESULT A9 SKIP - 浏览器不可用"
exit 0
'
sh "$CHECK" freeze "$REPO" >/dev/null 2>&1
sh "$CHECK" run "$REPO" >"$T/run4.out" 2>&1
rc=$?
if [ "$rc" -eq 0 ] && grep -q '"A9"' "$CH/last-result.json" \
   && grep -q '>>> 存在 SKIP，不得宣称全绿' "$T/run4.out"; then
  ok 10 "SKIP：退出 0，skipped 含 A9，警示行在 stdout"
else
  bad 10 "SKIP 场景异常：rc=$rc（期望 0 + skipped[A9] + 警示行）"
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

echo "SELFTEST: $PASS 通过 / $FAIL 失败"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
