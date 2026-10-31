#!/bin/sh
# 完成测试：全新工作区端到端冒烟。
#
# 覆盖：init → 契约写入 → freeze/verify/run → 冻结后篡改被拦 → 收轮幂等 →
#       summary/metrics/phase → resume/round_prompt → flex 闸门（放行/拒绝/审计）→
#       inbox/queue/playbook。
# 判定：任一步失败退出 1；成功退出 0 并清理临时工作区，失败保留现场供排查。
# 依赖：POSIX sh + python3（与技能本体一致，零第三方包）。
set -u

SKILL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/autopilot-e2e-XXXXXX")
REPO="$TMP/repo"
mkdir -p "$REPO"
# 队列默认落在 $AUTOPILOT_HOME/queue；测试必须隔离，不能污染使用者的真实队列。
export AUTOPILOT_HOME="$TMP/home"
mkdir -p "$AUTOPILOT_HOME"
FAILS=0
CHECKS=0
cleanup() {
  if [ "$FAILS" -eq 0 ]; then rm -rf "$TMP"; else printf 'fixture 保留: %s\n' "$TMP"; fi
}
trap cleanup EXIT

step() { printf '\n== %s ==\n' "$*"; }
die() { printf 'E2E FAIL: %s\n' "$*"; FAILS=$((FAILS + 1)); }
ok() { CHECKS=$((CHECKS + 1)); printf 'E2E PASS: %s\n' "$*"; }

step "1. init"
if bash "$SKILL/scripts/init.sh" --goal "端到端冒烟：交付一个可验证的 hello 文件" --repo "$REPO" >"$TMP/init.log" 2>&1; then
  ok "init 成功"
else
  die "init 失败: $(tail -3 "$TMP/init.log")"
fi
[ -f "$REPO/.autopilot/state.json" ] && ok "state.json 已生成" || die "缺 state.json"
[ -f "$REPO/.autopilot/checks/run.sh" ] && ok "checks/run.sh 脚手架已生成" || die "缺 checks/run.sh"

step "2. 写入合法 DAG 与验收脚本"
cat >"$REPO/.autopilot/tasks.json" <<'EOF'
{"epoch":0,"contract":{"goal":"e2e"},"tasks":[
 {"id":"T-01","title":"写 hello.txt","role":"Builder","status":"done","deps":[],
  "write_set":["hello.txt"],"acceptance":["A1"],"card":".autopilot/tasks/T-01.md"}]}
EOF
mkdir -p "$REPO/.autopilot/tasks" "$REPO/.autopilot/rounds"
printf '# T-01\n写 hello.txt\n' >"$REPO/.autopilot/tasks/T-01.md"
printf 'hello e2e\n' >"$REPO/hello.txt"
cat >"$REPO/.autopilot/checks/run.sh" <<'EOF'
#!/bin/sh
REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ -f "$REPO/hello.txt" ] && [ -s "$REPO/hello.txt" ]; then
  printf 'RESULT A1 PASS hello.txt 存在且非空\n'
  printf 'RESULT A2 PASS 内容可读\n'
  exit 0
fi
printf 'RESULT A1 FAIL hello.txt 缺失或为空\n'
printf 'RESULT A2 SKIP 无文件可读\n'
exit 1
EOF
chmod +x "$REPO/.autopilot/checks/run.sh"
if python3 "$SKILL/schema/check.py" "$REPO/.autopilot/tasks.json" >"$TMP/schema.log" 2>&1; then
  ok "tasks.json 通过 schema"
else
  die "schema 校验失败: $(tail -3 "$TMP/schema.log")"
fi

step "3. freeze → verify → run"
if bash "$SKILL/scripts/check.sh" freeze "$REPO" >"$TMP/freeze.log" 2>&1; then ok "freeze 成功"; else die "freeze 失败: $(tail -3 "$TMP/freeze.log")"; fi
if bash "$SKILL/scripts/check.sh" verify "$REPO" >"$TMP/verify.log" 2>&1; then ok "verify: $(tail -1 "$TMP/verify.log")"; else die "verify 失败"; fi
if bash "$SKILL/scripts/check.sh" run "$REPO" >"$TMP/run.log" 2>&1; then
  grep -q 'RESULT A1 PASS' "$REPO/.autopilot/checks/last.log" && ok "run 落盘 A1 PASS" || die "last.log 缺少 A1 PASS"
else
  die "run 失败: $(tail -3 "$TMP/run.log")"
fi

step "4. 冻结后篡改必须被拦（MANIFEST 漂移）"
printf '\n# tamper\n' >>"$REPO/.autopilot/checks/run.sh"
if bash "$SKILL/scripts/check.sh" run "$REPO" >"$TMP/tamper.log" 2>&1; then
  die "篡改 checks 后 run 仍返回 0（护栏失效）"
else
  grep -qi 'MANIFEST' "$TMP/tamper.log" && ok "篡改被 MANIFEST 拦截" || die "返回非零但未提示 MANIFEST: $(tail -2 "$TMP/tamper.log")"
fi
# 重新生成同一份脚本并重冻，回到可判定状态
cat >"$REPO/.autopilot/checks/run.sh" <<'EOF'
#!/bin/sh
REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ -f "$REPO/hello.txt" ] && [ -s "$REPO/hello.txt" ]; then
  printf 'RESULT A1 PASS hello.txt 存在且非空\n'
  printf 'RESULT A2 PASS 内容可读\n'
  exit 0
fi
printf 'RESULT A1 FAIL hello.txt 缺失或为空\n'
printf 'RESULT A2 SKIP 无文件可读\n'
exit 1
EOF
chmod +x "$REPO/.autopilot/checks/run.sh"
bash "$SKILL/scripts/check.sh" freeze "$REPO" >/dev/null 2>&1
bash "$SKILL/scripts/check.sh" verify "$REPO" >/dev/null 2>&1 || die "还原后 verify 失败"

step "5. 收轮（第 1 轮 PASS）"
cat >"$REPO/.autopilot/rounds/r-01.json" <<'EOF'
{"round":1,"verdict":"pass","epoch":0,"passed":["A1","A2"],"failed":[],"skipped":[],
 "tasks_closed":1,"parallel_peak":1,
 "evidence":["checks/last-result.json"],"blind_spots":["未测目录权限"],"notes":"e2e smoke"}
EOF
if python3 "$SKILL/scripts/status.py" close-round "$REPO" "$REPO/.autopilot/rounds/r-01.json" >"$TMP/close.log" 2>&1; then
  ok "close-round 成功"
else
  die "close-round 失败: $(tail -3 "$TMP/close.log")"
fi
python3 "$SKILL/scripts/status.py" close-round "$REPO" "$REPO/.autopilot/rounds/r-01.json" >"$TMP/close2.log" 2>&1 || die "close-round 二次调用失败"
ok "二次收轮返回 0（幂等）"
[ -f "$REPO/.autopilot/rounds/r-01.metrics.json" ] && ok "r-01.metrics.json 已生成" || die "缺 r-01.metrics.json"

step "6. summary / metrics / phase / resume / round_prompt"
if python3 "$SKILL/scripts/status.py" summary "$REPO" >"$TMP/summary.log" 2>&1; then
  grep -q '通过' "$TMP/summary.log" && ok "summary 显示通过数" || die "summary 缺通过数"
else
  die "summary 失败"
fi
python3 "$SKILL/scripts/status.py" metrics "$REPO" 1 >"$TMP/metrics.log" 2>&1 && ok "metrics 正常" || die "metrics 失败"
grep -q 'report' "$TMP/summary.log" && ok "phase 已进入 report" || die "phase 未进入 report"
if python3 "$SKILL/scripts/resume.py" "$REPO" >"$TMP/resume.log" 2>&1; then
  grep -q '停止' "$TMP/resume.log" && ok "resume 识别到停止条件" || ok "resume 正常输出接续包"
else
  die "resume 失败: $(tail -3 "$TMP/resume.log")"
fi
bash "$SKILL/scripts/round_prompt.sh" "$REPO" 2 >"$TMP/prompt.log" 2>&1 && ok "round_prompt 正常" || die "round_prompt 失败"

step "7. flex 闸门基本闭环（strict 放行 → 越界拒绝）"
G="$SKILL/scripts/flex-gate.sh"
bash "$G" check --repo "$REPO" --task T-01 >"$TMP/g1.log" 2>&1
[ $? -eq 0 ] && ok "strict 单文件卡放行" || die "strict 单文件卡被拒: $(tail -2 "$TMP/g1.log")"
bash "$G" deny-list --repo "$REPO" --check "git push" >"$TMP/g2.log" 2>&1
[ $? -eq 24 ] && ok "不可逆命令被拒（24）" || die "deny-list 未返回 24"
bash "$G" audit --repo "$REPO" --round 1 >"$TMP/g3.log" 2>&1 && ok "audit 正常" || die "audit 失败"

step "8. inbox / queue / playbook 冒烟"
python3 "$SKILL/scripts/inbox.py" list "$REPO" >/dev/null 2>&1 && ok "inbox list 正常" || die "inbox 失败"
python3 "$SKILL/scripts/queue.py" add --repo "$REPO" --goal "下一个目标" >/dev/null 2>&1 && ok "queue add 正常" || die "queue 失败"
python3 "$SKILL/scripts/playbook.py" add "$REPO" --kind pitfall --text "e2e 冒烟结论" >/dev/null 2>&1 && ok "playbook add 正常" || die "playbook 失败"

printf '\n== 结果 ==\n'
if [ "$FAILS" -eq 0 ]; then
  echo "E2E SUMMARY checks=$CHECKS fail=0"
  exit 0
fi
echo "E2E SUMMARY checks=$CHECKS fail=$FAILS"
exit 1
