#!/bin/sh
# H36 外部触发接续自测：A-tr-01..12。全程在 mktemp -d 的假工作区里跑，不建任何会话。
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

# ---------------------------------------------------------------- 9-12 陈旧锁看门狗（release --if-stale）

reset_round() {
    put_goal on 12
    put_state 1 build
    put_tasks ready
    put_inbox none
    rm -f "$REPO/.autopilot/trigger.lock" "$REPO/.autopilot/ledger.jsonl"
}
age_lock() {  # $1=分钟：把锁的 claim 戳往前推，模拟会话跑了多久
    L="$REPO/.autopilot/trigger.lock" MIN="$1" $PY - <<'PY'
import json, os, time
p = os.environ["L"]
d = json.load(open(p, encoding="utf-8"))
d["ts"] = time.time() - int(os.environ["MIN"]) * 60
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, sort_keys=True)
PY
}
log_event() {  # 模拟 claim 之后会话真干了活留下的账本事件
    NOW="$($PY -c 'import datetime;print(datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))')" \
    D="$REPO/.autopilot/ledger.jsonl" $PY - <<'PY'
import os
open(os.environ["D"], "a", encoding="utf-8").write(
    '{"type":"worker","task":"T-01","ts":"%s"}\n' % os.environ["NOW"])
PY
}

reset_round
$PY "$TG" claim --repo "$REPO" --session s-quiet >/dev/null 2>&1
age_lock 25
out=$($PY "$TG" release --repo "$REPO" --if-stale 2>&1); rc=$?
if [ "$rc" = 0 ] && ! [ -f "$REPO/.autopilot/trigger.lock" ] \
   && grep -q '"type": "auto_round_released"' "$REPO/.autopilot/ledger.jsonl" \
   && printf '%s' "$out" | grep -q "零活动"; then
  pass 9 "claim 后超过一个节拍而账本零活动 → --if-stale 解锁并落一条 auto_round_released（占位就跑路的会话不再卡死整条链）"
else
  fail 9 "陈旧锁没被解开：rc=$rc $out"
fi

reset_round
$PY "$TG" claim --repo "$REPO" --session s-busy >/dev/null 2>&1
log_event
age_lock 25
out=$($PY "$TG" release --repo "$REPO" --if-stale 2>&1); rc=$?
if [ "$rc" = 20 ] && [ -f "$REPO/.autopilot/trigger.lock" ] && printf '%s' "$out" | grep -q "别抢正在干活的会话"; then
  pass 10 "账本里有活动 = 会话还在跑，--if-stale 退 20 不抢锁（看门狗不能变成第二个开跑的人）"
else
  fail 10 "把还在干活的会话的锁抢了：rc=$rc $out"
fi

reset_round
$PY "$TG" claim --repo "$REPO" --session s-old >/dev/null 2>&1
log_event
age_lock 61
out=$($PY "$TG" release --repo "$REPO" --if-stale 2>&1); rc=$?
if [ "$rc" = 20 ] && [ -f "$REPO/.autopilot/trigger.lock" ] && printf '%s' "$out" | grep -q "宁停不抢"; then
  pass 11 "超 TTL 但 claim 后有活动 → 仍不自动解锁：长轮次本来就可能跑很久，两个会话写同一轮的代价比链停下来等人高"
else
  fail 11 "有活动的锁被 TTL 抢了：rc=$rc $out"
fi

reset_round
$PY "$TG" claim --repo "$REPO" --session s-ttlidle >/dev/null 2>&1
age_lock 61
out=$($PY "$TG" release --repo "$REPO" --if-stale 2>&1); rc=$?
if [ "$rc" = 0 ] && ! [ -f "$REPO/.autopilot/trigger.lock" ] && printf '%s' "$out" | grep -q "TTL"; then
  pass 12 "超 TTL 且零活动 → TTL 路径解锁（既没在干活、又超时，没有任何理由继续等）"
else
  fail 12 "TTL 零活动路径没解锁：rc=$rc $out"
fi

reset_round
$PY "$TG" claim --repo "$REPO" --session s-d1 >/dev/null 2>&1
age_lock 25
out=$($PY "$TG" decide --repo "$REPO" 2>&1); rc=$?
idle_ok=0
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "release --if-stale"; then idle_ok=1; fi
$PY "$TG" claim --repo "$REPO" --session s-d2 >/dev/null 2>&1
log_event
age_lock 25
out2=$($PY "$TG" decide --repo "$REPO" 2>&1); rc2=$?
if [ "$idle_ok" = 1 ] && [ "$rc2" = 20 ] && ! printf '%s' "$out2" | grep -q "release --if-stale"; then
  pass 13 "decide 两面：零活动的陈旧锁 → 判 GO 并给出解锁口径；有活动 → BUSY 且不引诱你去抢"
else
  fail 13 "decide 的看门狗口径不对：idle rc=$rc(ok=$idle_ok) busy rc=$rc2"
fi

reset_round
$PY "$TG" claim --repo "$REPO" --session s-c1 >/dev/null 2>&1
log_event
age_lock 61
out=$($PY "$TG" claim --repo "$REPO" --session s-c2 2>&1); rc=$?
busy_refused=0
[ "$rc" = 20 ] && busy_refused=1
if [ "$busy_refused" = 1 ]; then
  pass 14 "claim 用的是同一个看门狗判据：锁超 TTL 但 claim 后有活动 → 退 20 不抢占（与 decide/release 三处一致，不存在第二个开跑的人）"
else
  fail 14 "claim 的看门狗口径不对：busy_refused=$busy_refused rc2=$rc2 out=$out2"
fi

reset_round
$PY "$TG" claim --repo "$REPO" --session s-c6 >/dev/null 2>&1
age_lock 61
out3=$($PY "$TG" claim --repo "$REPO" --session s-c7 2>&1); rc3=$?
if [ "$rc3" = 0 ] && printf '%s' "$out3" | grep -q "陈旧"; then
  pass 15 "超 TTL 且零活动的锁允许直接改占（不必先跑一次 release），无人值守链条不会因此停摆"
else
  fail 15 "陈旧锁改占不通：rc=$rc3 $out3"
fi

# ---------------------------------------------------------------- 16 待批计数按条目折叠（H45）
# inbox.jsonl 是追加式事件流：一条待批会产生 open/present/answer 多行，且 present、answer 行
# 没有 state 字段。旧实现数「state==open 的行」并把缺 state 的也当 open → 一条已答复的待批
# 会被数成好几条，decide 永久 ASK-HUMAN。ContraRunner 实测真待批 1 条、它报 13 条。
put_inbox none
cat > "$REPO/.autopilot/inbox.jsonl" <<'EOF'
{"id":"I-1","type":"open","kind":"approval","state":"open"}
{"id":"I-1","type":"present"}
{"id":"I-1","type":"answer","answered_by":"human","ref":"chat-session:x","answer":"批准"}
{"id":"I-2","type":"open","kind":"approval","state":"open"}
{"id":"I-2","type":"present"}
{"id":"I-3","type":"open","kind":"approval","state":"open"}
{"id":"I-3","type":"present"}
{"id":"I-3","type":"answer","answered_by":"human","ref":"chat-session:y","answer":"批准"}
{"id":"I-4","type":"open","kind":"approval","state":"open"}
{"id":"I-4","type":"present"}
{"id":"I-4","type":"answer","answered_by":"supervisor","note":"控制器代判","answer":"批准"}
EOF
CNT16=$(python3 -c "
import sys; sys.path.insert(0, '$HERE')
import trigger
print(trigger.open_inbox_count('$REPO'))
" 2>/dev/null)
if [ "$CNT16" = "1" ]; then
    pass 16 "待批计数按 id 折叠：11 个事件行 / 5 条条目里只有 I-2 未答复 → 1（旧实现会数出 8~11）"
else
    fail 16 "待批计数不对：得到 $CNT16，期望 1"
fi
# 全部答复完 → 必须归零，否则自动接续永久停摆
put_inbox none
cat > "$REPO/.autopilot/inbox.jsonl" <<'EOF'
{"id":"I-1","type":"open","kind":"approval","state":"open"}
{"id":"I-1","type":"present"}
{"id":"I-1","type":"answer","answered_by":"human","ref":"chat-session:x","answer":"批准"}
{"id":"I-2","type":"open","kind":"approval","state":"open"}
{"id":"I-2","type":"answer","answered_by":"human","ref":"chat-session:z","answer":"批准"}
EOF
CNT16B=$(python3 -c "
import sys; sys.path.insert(0, '$HERE')
import trigger
print(trigger.open_inbox_count('$REPO'))
" 2>/dev/null)
if [ "$CNT16B" = "0" ]; then
    pass 16 "全部已答复时计数归零，decide 不再被幽灵待批卡住"
else
    fail 16 "已答复的待批仍在计数：得到 $CNT16B，期望 0"
fi
put_inbox none

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
