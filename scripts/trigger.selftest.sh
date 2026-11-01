#!/bin/sh
# H36 外部触发接续自测：A-tr-01..08。全程在 mktemp -d 的假工作区里跑，不建任何会话。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL=$(cd "$HERE/.." && pwd)
PY=${PYTHON:-python3}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

REPO="$TMP/repo"
mkdir -p "$REPO/.autopilot"
TG="$SKILL/scripts/trigger.py"

put_goal() {
    {
      printf '# GOAL — {REPO_ROOT}\n\n## 终结目标\n做 X\n'
      if [ "${1:-on}" = on ]; then
        printf '\n## TRIGGER\nenable = true\ninterval_min = 20\nmax_auto_sessions = %s\nstop_phase = report\n' "${2:-2}"
      fi
    } > "$REPO/.autopilot/GOAL.md"
}
put_state() {  # $1=rounds_used $2=phase
    printf '{"schema":2,"rounds_used":%s,"phase":"%s","budget":{"max_rounds":9,"max_calls":90}}\n' "$1" "$2" \
      > "$REPO/.autopilot/state.json"
}
put_tasks() {  # $1 = ready|none
    if [ "$1" = ready ]; then
      printf '{"epoch":0,"tasks":[{"id":"T-01","status":"ready","write_set":["src/a.py"]}]}\n' \
        > "$REPO/.autopilot/tasks.json"
    else
      printf '{"epoch":0,"tasks":[{"id":"T-01","status":"done","write_set":["src/a.py"]}]}\n' \
        > "$REPO/.autopilot/tasks.json"
    fi
}
put_inbox() {  # $1 = open|none
    if [ "$1" = open ]; then
      printf '{"id":"I-1","state":"open","kind":"irreversible","cmd":"git push"}\n' \
        > "$REPO/.autopilot/inbox.jsonl"
    else
      rm -f "$REPO/.autopilot/inbox.jsonl"
    fi
}

# ---------------------------------------------------------------- 1 关闭态

put_goal off; put_state 1 build; put_tasks ready; put_inbox none
rc_all=0
for c in decide claim status; do
    o=$($PY "$TG" $c --repo "$REPO" 2>&1); r=$?
    [ "$r" = 23 ] || rc_all=1
done
if [ "$rc_all" = 0 ] && ! [ -f "$REPO/.autopilot/trigger.lock" ] && ! [ -f "$REPO/.autopilot/ledger.jsonl" ]; then
  pass 1 "GOAL 没有 ## TRIGGER 时三个子命令都退 23，不加锁、不写账本（等同没装）"
else
  fail 1 "关闭态不干净（有锁或有账本）"
fi

# ---------------------------------------------------------------- 2 该接续就说该接续

put_goal on 3; put_state 1 build; put_tasks ready
out=$($PY "$TG" decide --repo "$REPO" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q GO \
   && printf '%s' "$out" | grep -q "本脚本不建会话、不发消息"; then
  pass 2 "有活、预算未满 → 退 0 判 GO，并写明开不开会话由宿主做"
else
  fail 2 "GO 分支不对：rc=$rc $out"
fi

# ---------------------------------------------------------------- 3 没活不空开

put_tasks none
out=$($PY "$TG" decide --repo "$REPO" 2>&1); rc=$?
if [ "$rc" = 10 ] && printf '%s' "$out" | grep -q HOLD; then
  pass 3 "没有 ready 卡时退 10 HOLD，不给定时器一个看起来正常的 0"
else
  fail 3 "无活分支不对：rc=$rc $out"
fi

# ---------------------------------------------------------------- 4 待批项优先于人也不自动

put_tasks ready; put_inbox open
out=$($PY "$TG" decide --repo "$REPO" 2>&1); rc=$?
if [ "$rc" = 24 ] && printf '%s' "$out" | grep -q "不可逆"; then
  pass 4 "有待批项时判 ASK-HUMAN（退 24）：自动接续不得代处理不可逆动作"
else
  fail 4 "待批项没拦住：rc=$rc $out"
fi

# ---------------------------------------------------------------- 5 锁与幂等

put_inbox none
$PY "$TG" claim --repo "$REPO" --session s-1 >/dev/null 2>&1
out=$($PY "$TG" decide --repo "$REPO" 2>&1); rc=$?
if [ "$rc" = 20 ] && printf '%s' "$out" | grep -q BUSY; then
  pass 5 "会话还在跑时判 BUSY（退 20），定时器重复敲不会开出第二个会话"
else
  fail 5 "锁没起作用：rc=$rc $out"
fi
$PY "$TG" release --repo "$REPO" >/dev/null 2>&1
$PY "$TG" release --repo "$REPO" >/dev/null 2>&1; rc2=$?
out=$($PY "$TG" decide --repo "$REPO" 2>&1); rc=$?
if [ "$rc2" = 0 ] && [ "$rc" = 0 ]; then
  pass 5 "release 幂等（重复调不报错），释放后又能接续"
else
  fail 5 "release 不幂等或释放后仍拦住：rc=$rc/$rc2"
fi

# ---------------------------------------------------------------- 6 自动接续次数上限

i=1
while [ $i -le 3 ]; do
    $PY "$TG" claim --repo "$REPO" --session "s-$i" >/dev/null 2>&1
    $PY "$TG" release --repo "$REPO" >/dev/null 2>&1
    i=$((i + 1))
done
out=$($PY "$TG" decide --repo "$REPO" 2>&1); rc=$?
if [ "$rc" = 21 ] && printf '%s' "$out" | grep -q "上限"; then
  pass 6 "自动接续到 max_auto_sessions 就 STOP（退 21），长跑不会无人值守地自己续到天亮"
else
  fail 6 "次数上限没生效：rc=$rc $out"
fi

# ---------------------------------------------------------------- 7 到阶段就交回人工

rm -f "$REPO/.autopilot/ledger.jsonl"   # 清掉第 6 用例攒下的自动接续计数，才能单独考察阶段规则
put_state 9 report
out=$($PY "$TG" decide --repo "$REPO" 2>&1); rc=$?
if [ "$rc" = 10 ] && printf '%s' "$out" | grep -q "交回人工"; then
  pass 7 "phase 到达 stop_phase 后不再自动接续"
else
  fail 7 "阶段停止不对：rc=$rc $out"
fi

# ---------------------------------------------------------------- 8 决策可机读

put_state 1 build
j=$($PY "$TG" decide --repo "$REPO" --json 2>&1)
if printf '%s' "$j" | "$PY" -c 'import json,sys; d=json.loads(sys.stdin.read().strip().splitlines()[-1]); assert d["decision"] in ("GO","HOLD","BUSY","STOP","ASK-HUMAN"); assert d["reasons"]' 2>/dev/null; then
  pass 8 "--json 输出可被机器解析，字段里有 decision 与 reasons（宿主的 cron 任务能直接判）"
else
  fail 8 "--json 不可解析：$j"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
