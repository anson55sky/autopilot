#!/usr/bin/env bash
# resume.py / round_prompt.sh 0.9 自检：mktemp fixture 真跑。
# 用法: bash resume-round.selftest.sh   （任何 FAIL 即退出 1）
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
RESUME="$HERE/resume.py"
RP="$HERE/round_prompt.sh"
FIX="$(mktemp -d)"
trap 'rm -rf "$FIX"' EXIT

FAILS=0
pass() { echo "RESULT R$1 PASS"; }
fail() { echo "RESULT R$1 FAIL: $2"; FAILS=$((FAILS + 1)); }

check_contains() { # n file label needle
  if grep -qF -- "$4" "$2"; then pass "$1"; else fail "$1" "$3 缺少「$4」"; fi
}
check_no_match() { # n file label pattern
  if grep -qE -- "$4" "$2"; then fail "$1" "$3 命中禁止模式"; else pass "$1"; fi
}

# 禁止模式（拼接构造，本文件自身不出现该字面串）：
ABS_PAT="$(printf '%sers/|~%s|[A-Za-z]:[\\\\/]' '/U' '/')"

# ---------- R1 空工作区：不崩 + 0.8 旧行齐全 ----------
mkdir -p "$FIX/empty/.autopilot"
if python3 "$RESUME" "$FIX/empty" >"$FIX/r1.out" 2>"$FIX/r1.err"; then
  ok=1
  for line in "== 接续包 ==" "仓库:" "目标:" "模式:" "预算:" "任务:" "停止:" "待决:" "下一步:" "边界:"; do
    grep -qF -- "$line" "$FIX/r1.out" || { ok=0; fail 1 "空工作区缺旧行「$line」"; }
  done
  [ "$ok" = 1 ] && pass 1
else
  fail 1 "空工作区 resume 非零退出：$(cat "$FIX/r1.err")"
fi

# ---------- R2 富 fixture：flex/epoch/SKIP/host 新视图出数字 ----------
mkdir -p "$FIX/rich/.autopilot/checks" "$FIX/rich/sandbox/.gate"
cat >"$FIX/rich/.autopilot/state.json" <<'EOF'
{"mode":"auto","phase":"build","rounds_used":2,"goal":"把登录修好","no_progress_streak":0,
 "budget":{"max_rounds":10},"started_at":"2026-10-20T09:00:00+08:00"}
EOF
cat >"$FIX/rich/.autopilot/tasks.json" <<'EOF'
{"epoch":3,"tasks":[{"id":"T-1","status":"done","deps":[]},{"id":"T-2","status":"pending","deps":["T-1"]}]}
EOF
printf '%s\n' "| A1 | 登录成功 |" >"$FIX/rich/.autopilot/GOAL.md"
printf '%s\n' "契约锁定：写集不含 checks/" >"$FIX/rich/.autopilot/contract-changelog.md"
cat >"$FIX/rich/.autopilot/checks/last-result.json" <<'EOF'
{"passed":["A1"],"failed":[],"skipped":3}
EOF
cat >"$FIX/rich/sandbox/.gate/state.json" <<'EOF'
{"round":3,"epoch":3,"light_used":1,"heavy_used":2,"flex_calls":4,"permits_issued":1,
 "permits":[{"permit_id":"P-7","used":false,"revoked":false}]}
EOF
cat >"$FIX/rich/.autopilot/host.json" <<'EOF'
{"host":"unknown-host"}
EOF
if python3 "$RESUME" "$FIX/rich" >"$FIX/r2.out" 2>"$FIX/r2.err"; then
  ok=1
  for needle in "Epoch:  3" "契约变更: 契约锁定" "闸门:" "light 1" "heavy 2" "flex_calls 4" \
                "P-7" "flexgate.py status" "跳过:   3" "不得宣称全绿" "宿主:" "降级形态" "距今"; do
    grep -qF -- "$needle" "$FIX/r2.out" || { ok=0; fail 2 "缺新视图「$needle」"; }
  done
  [ "$ok" = 1 ] && pass 2
else
  fail 2 "富 fixture resume 非零退出：$(cat "$FIX/r2.err")"
fi

# ---------- R3 --json 可解析且带新字段 ----------
if python3 "$RESUME" "$FIX/rich" --json >"$FIX/r3.out" 2>"$FIX/r3.err" \
   && python3 - "$FIX/r3.out" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d["epoch"] == 3, d
assert d["skipped"] == 3, d
assert d["gate"]["light_used"] == 1 and "P-7" in d["gate"]["active"], d
assert "降级形态" in d["host"], d
assert d["started_at"].endswith("+08:00"), d
PY
then pass 3; else fail 3 "--json 解析或字段不符：$(cat "$FIX/r3.err")"; fi

# ---------- R4/R5/R6 三种坏时间戳：不抛异常 ----------
mkdir -p "$FIX/ts/.autopilot"
printf '%s\n' '{"goal":"g"}' >"$FIX/ts/.autopilot/state.json"
stamp_case() { # n stamp needle
  printf '{"v":%s}' "$2" >"$FIX/ts/.stamp.json"
  python3 -c 'import json,sys; json.dump({"goal":"g","started_at":json.load(open(sys.argv[1]))["v"]}, open(sys.argv[2],"w"), ensure_ascii=False)' \
    "$FIX/ts/.stamp.json" "$FIX/ts/.autopilot/state.json"
  if python3 "$RESUME" "$FIX/ts" >"$FIX/r$1.out" 2>"$FIX/r$1.err"; then
    check_contains "$1" "$FIX/r$1.out" "坏时间戳($2)" "时间:   $3"
  else
    fail "$1" "坏时间戳($2) resume 抛异常：$(cat "$FIX/r$1.err")"
  fi
}
stamp_case 4 '"2026-01-01T08:00:00"' '2026-01-01 08:00'   # 无偏移 → 补本地，不崩
stamp_case 5 '"不是个时间戳"' 'unknown'                    # 乱码 → unknown
stamp_case 6 '""' 'unknown'                                # 空戳 → unknown

# ---------- R7 生成的提示词：无绝对路径 + 含关键要素 ----------
"$RP" "$FIX/rich" >"$FIX/prompt.txt" 2>"$FIX/prompt.err" || fail 7 "round_prompt.sh 退出非零：$(cat "$FIX/prompt.err")"
check_no_match 7 "$FIX/prompt.txt" "提示词绝对路径" "$ABS_PAT"
ok=1
for needle in '{SKILL_ROOT}' '{REPO_ROOT}' '--mute-audio' '闸门四调用' 'C1 中断恢复' \
              'flexgate.py' 'check --task' 'permit --task' 'spend --task' 'revoke --permit-id' \
              '全量验收一轮只跑一次' '转待批' '占位符'; do
  grep -qF -- "$needle" "$FIX/prompt.txt" || { ok=0; fail 7 "提示词缺「$needle」"; }
done
last="$(tail -n 1 "$FIX/prompt.txt")"
case "$last" in "最后一行只输出：ROUND "*" DONE 或 ROUND "*" BLOCKED"*) ;; *) ok=0; fail 7 "末行不是收尾句式：$last";; esac
[ "$ok" = 1 ] && pass 7

# ---------- R8 同 fixture 两次生成：只有轮次号差异（此处应为逐字节一致） ----------
"$RP" "$FIX/rich" >"$FIX/gen1.txt" 2>/dev/null
"$RP" "$FIX/rich" 3 >"$FIX/gen2.txt" 2>/dev/null
if diff -q "$FIX/gen1.txt" "$FIX/gen2.txt" >/dev/null 2>&1; then pass 8
else fail 8 "两次生成不稳定：$(diff "$FIX/gen1.txt" "$FIX/gen2.txt" | head -5)"; fi

# ---------- R9 语法检查 ----------
if sh -n "$RP" && python3 -m py_compile "$RESUME"; then pass 9; else fail 9 "语法检查未过"; fi

# ---------- R10 env.json 存在时，提示词仍不得展开成绝对路径 ----------
# 这是真实踩过的坑：旧实现读 env.json 后把占位符替换成本机绝对路径，
# 提示词一旦进历史产物就换机即断，且违反 M6。
mkdir -p "$FIX/withenv/.autopilot"
cat >"$FIX/withenv/.autopilot/env.json" <<EOF
{"skill_root":"$FIX/withenv/skill-dir","repo_root":"$FIX/withenv","rounds_used":4}
EOF
printf '%s\n' '{"rounds_used":4}' >"$FIX/withenv/.autopilot/state.json"
if sh "$RP" "$FIX/withenv" >"$FIX/prompt2.txt" 2>"$FIX/prompt2.err"; then
  ok=1
  grep -qE -- "$ABS_PAT" "$FIX/prompt2.txt" && { ok=0; fail 10 "env.json 存在时提示词仍展开了绝对路径"; }
  grep -qF -- '{SKILL_ROOT}' "$FIX/prompt2.txt" || { ok=0; fail 10 "提示词丢了 {SKILL_ROOT} 占位符"; }
  grep -qF -- '{REPO_ROOT}' "$FIX/prompt2.txt" || { ok=0; fail 10 "提示词丢了 {REPO_ROOT} 占位符"; }
  grep -qF -- '第 5 轮' "$FIX/prompt2.txt" || { ok=0; fail 10 "提示词轮次号没按 state.json 推算"; }
  [ "$ok" = 1 ] && pass 10
else
  fail 10 "round_prompt.sh 退出非零：$(cat "$FIX/prompt2.err")"
fi

# ---------- R11 状态数字被手改坏：不崩，停止条件按 0 处理 ----------
mkdir -p "$FIX/corrupt/.autopilot/checks"
cat >"$FIX/corrupt/.autopilot/state.json" <<'EOF'
{"goal":123,"rounds_used":"two","no_progress_streak":"x","budget":{"max_rounds":"many"}}
EOF
printf '[1,2]\n' >"$FIX/corrupt/.autopilot/tasks.json"
printf '[1,2]\n' >"$FIX/corrupt/.autopilot/checks/last-result.json"
if python3 "$RESUME" "$FIX/corrupt" >"$FIX/r11.out" 2>"$FIX/r11.err"; then
  if grep -qE 'Traceback' "$FIX/r11.out" "$FIX/r11.err"; then
    fail 11 "坏数字/异形 JSON 仍出 traceback"
  elif grep -qF '目标:' "$FIX/r11.out"; then
    pass 11
  else
    fail 11 "坏输入下没输出接续包"
  fi
else
  fail 11 "坏数字导致 resume 非零退出：$(cat "$FIX/r11.err")"
fi

echo "----"
if [ "$FAILS" -gt 0 ]; then echo "SELFTEST FAIL（$FAILS 例失败）"; exit 1; fi
echo "SELFTEST PASS"
