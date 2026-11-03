#!/bin/sh
# P2 并发调度自测：A-conc-01..16（11 kill/上限来源，12 非幂等闸，13 H30 可重放，
# 14 判定文件写集闸 H40，15 尺子冻结态闸 H42）。
# 只在 mktemp -d 造临时工作区，不碰真实仓库、不碰线上 skill。
# 判定口径：每例一行 PASS/FAIL；任何 FAIL 退出 1。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SCHED="$HERE/dag_scheduler.py"
STATUS="$HERE/status.py"
GOLDEN="$HERE/fixtures/round_prompt.round05.serial.golden"
PY=${PYTHON:-python3}

TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPROOT"' EXIT INT TERM

PASSED=0
FAILED=0

pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

# ---------------------------------------------------------------- 脚手架

new_repo() {
    d="$TMPROOT/$1"
    mkdir -p "$d/.autopilot"
    printf '# GOAL\n\n（本工作区没有 CONCURRENT 区块）\n' > "$d/.autopilot/GOAL.md"
    cat > "$d/.autopilot/state.json" <<'EOF'
{"started_at": "2026-01-01T00:00:00+00:00", "phase": "execute", "rounds_used": 0,
 "budget": {"max_rounds": 10, "max_tasks_per_round": 0, "parallel": 4, "max_minutes": 600, "max_calls": 100}}
EOF
    printf '%s\n' "$d"
}

goal_on() {
    # 函数内变量全部加前缀：POSIX sh 没有局部变量，别把调用方的 $repo 覆盖掉
    _g_repo="$1"; _g_conc="${2:-3}"; _g_timeout="${3:-30}"; _g_halt="${4:-wait-running}"
    cat > "$_g_repo/.autopilot/GOAL.md" <<EOF
# GOAL

## CONCURRENT

enable                = true
max_concurrent_builder = $_g_conc
halt_policy           = $_g_halt
task_timeout_min      = $_g_timeout
EOF
}

set_budget() {
    _b_repo="$1"; _b_parallel="$2"; _b_max_tasks="$3"
    cat > "$_b_repo/.autopilot/state.json" <<EOF
{"started_at": "2026-01-01T00:00:00+00:00", "phase": "execute", "rounds_used": 0,
 "budget": {"max_rounds": 10, "max_tasks_per_round": $_b_max_tasks, "parallel": $_b_parallel,
            "max_minutes": 600, "max_calls": 100}}
EOF
}

write_tasks() { cat > "$1/.autopilot/tasks.json"; }

task_json() {
    # id deps write_set [status] [extra_json]：mode/premise_tag 等走 extra_json
    printf '{"id": "%s", "title": "%s", "role": "Builder", "status": "%s", "deps": %s, "write_set": %s, "acceptance": ["A1"], "card": ".autopilot/tasks/%s.md"%s}' \
        "$1" "$1" "${4:-pending}" "$2" "$3" "$1" "${5:-}"
}

expect_rc() {
    # 例号 期望 实际 说明
    if [ "$3" -eq "$2" ]; then pass "$1" "$4"; else fail "$1" "$4（退出码 want=$2 got=$3）"; fi
}

expect_contains() {
    # 例号 文件 模式 说明
    if grep -q -- "$3" "$2"; then pass "$1" "$4"; else
        fail "$1" "$4（输出里没有: $3）"
        sed 's/^/    | /' "$2" | head -12
    fi
}

expect_not_contains() {
    if grep -q -- "$3" "$2"; then
        fail "$1" "$4（输出里不该出现: $3）"
    else pass "$1" "$4"; fi
}

# ---------------------------------------------------------------- A-conc-01 关闭态等价

# A-conc-13 H30 派发决策可重放：同一 tasks.json 连跑 5 次，退出码与输出逐字节一致
case_replay_determinism() {
    # H30：派发决策必须是纯函数 —— 同一 tasks.json 连跑 5 次，输出逐字节相同
    repo=$(new_repo a13)
    goal_on "$repo" 3
    write_tasks "$repo" <<EOF
{"tasks": [
 $(task_json T-61 '[]' '["src/a.js"]'),
 $(task_json T-62 '["T-61"]' '["src/b.js"]'),
 $(task_json T-63 '[]' '["src/c.js"]' pending ',"premise_tag": "p1"'),
 {"id": "T-64", "title": "T-64", "role": "Builder", "status": "failed", "deps": [],
  "write_set": ["src/d.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-64.md",
  "premise_tag": "p1"},
 {"id": "T-65", "title": "T-65", "role": "Builder", "status": "failed", "deps": [],
  "write_set": ["src/e.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-65.md",
  "premise_tag": "p1"},
 {"id": "T-66", "title": "T-66", "role": "Builder", "status": "pending", "deps": [],
  "write_set": ["sandbox/x.js"], "acceptance": [], "card": ".autopilot/tasks/T-66.md",
  "mode": "flex-light", "sandbox_target": "sandbox"}
], "epoch": 0}
EOF
    first="$TMPROOT/a13.plan.1"
    $PY "$SCHED" plan --repo "$repo" >"$first" 2>&1
    rc_first=$?
    same=1
    i=2
    while [ "$i" -le 5 ]; do
        $PY "$SCHED" plan --repo "$repo" >"$TMPROOT/a13.plan.$i" 2>&1
        rc_i=$?
        [ "$rc_i" -eq "$rc_first" ] || same=0
        cmp -s "$first" "$TMPROOT/a13.plan.$i" || same=0
        i=$((i + 1))
    done
    if [ "$rc_first" -ne 0 ]; then
        fail 13 "夹具本身没跑通（rc=$rc_first），先修夹具再谈重放"
        sed 's/^/    | /' "$first" | head -6
    elif [ "$same" = "1" ]; then
        pass 13 "同一份 tasks.json 连跑 5 次 plan，退出码与输出逐字节一致"
    else
        fail 13 "派发顺序不确定（H30 要求可重放）"
        diff "$first" "$TMPROOT/a13.plan.5" | head -6 | sed 's/^/    | /'
    fi
    if grep -q "TRIAGE-HALT p1" "$first"; then
        pass 13 "Triage 聚合同样出现在可重放输出里"
    else
        fail 13 "TRIAGE-HALT 没出现在 plan 输出里"
    fi
    if grep -q "^import random" "$SCHED"; then
        fail 13 "调度器里出现了 random —— 派发决策不再可重放"
    else
        pass 13 "调度器不引入随机源"
    fi
    uses_time=$(grep -c "datetime\.now\|time\.time\|utc_now()" "$SCHED")
    if [ "${uses_time:-0}" -le 12 ]; then
        pass 13 "时钟调用点受限且只用于时间戳与超时（共 $uses_time 处）"
    else
        fail 13 "时钟调用点过多（$uses_time 处），重放语义存疑"
    fi
}

# A-conc-15 尺子冻结态闸门（H42：判定面不在冻结态就不许派工）
freeze_manifest_sh() {
    $PY - "$1/.autopilot/checks" <<'PY'
import hashlib, os, sys
cdir = sys.argv[1]
lines = []
for cur, dirs, files in os.walk(cdir):
    dirs.sort()
    for f in sorted(files):
        if f in ("MANIFEST.sha256", "last.log", "last-result.json", ".DS_Store"):
            continue
        full = os.path.join(cur, f)
        rel = os.path.relpath(full, cdir).replace(os.sep, "/")
        h = hashlib.sha256(open(full, "rb").read()).hexdigest()
        lines.append("%s  ./%s" % (h, rel))
open(os.path.join(cdir, "MANIFEST.sha256"), "w", encoding="utf-8").write(
    "\n".join(sorted(lines)) + "\n")
PY
}

case_ruler_drift_gate() {
    repo=$(new_repo a15)
    goal_on "$repo"
    mkdir -p "$repo/.autopilot/checks"
    printf '#!/bin/sh\necho "RESULT A1 PASS ok"\n' > "$repo/.autopilot/checks/run.sh"
    printf '<html>RESULT A2 PASS</html>\n' > "$repo/.autopilot/checks/probe-x.html"
    freeze_manifest_sh "$repo"
    write_tasks "$repo" <<EOF
{"tasks": [
 {"id": "T-71", "title": "T-71", "role": "Builder", "status": "pending", "deps": [],
  "write_set": ["src/a.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-71.md"},
 {"id": "T-72", "title": "T-72", "role": "Builder", "status": "pending", "deps": [],
  "write_set": ["src/b.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-72.md"}
], "epoch": 0}
EOF

    # 干净冻结态：正常可派，闸门不得碍事
    $PY "$SCHED" start --repo "$repo" --task T-71 >"$TMPROOT/a15.clean" 2>&1
    expect_rc 15 0 "$?" "MANIFEST 一致时正常派工不受影响"

    # ① 在册文件被改 = drift
    printf 'relaxed\n' >> "$repo/.autopilot/checks/probe-x.html"
    $PY "$SCHED" start --repo "$repo" --task T-72 >"$TMPROOT/a15.drift" 2>&1
    expect_rc 15 24 "$?" "冻结后改了在册判定文件 → 拒绝派工"
    expect_contains 15 "$TMPROOT/a15.drift" "不在冻结态" "拒绝理由写明尺子状态"

    $PY "$SCHED" start --repo "$repo" --task T-72 --allow-ruler-drift >"$TMPROOT/a15.noflag" 2>&1
    expect_rc 15 2 "$?" "漂移态放行必须配 --note 理由"

    $PY "$SCHED" start --repo "$repo" --task T-72 --allow-ruler-drift \
        --note "控制器 2026-11-02 已逐行 diff 确认只更严" >"$TMPROOT/a15.rel" 2>&1
    expect_rc 15 0 "$?" "带理由的显式放行可以派"
    if $PY - "$repo/.autopilot/ledger.jsonl" <<'PY'
import json, sys
ev = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
hit = [e for e in ev if e.get("task") == "T-72" and e.get("ruler_drift")]
clean = [e for e in ev if e.get("task") == "T-71" and e.get("ruler_drift")]
sys.exit(0 if len(hit) == 1 and hit[0]["ruler_drift"]["status"] == "drift"
         and not clean else 1)
PY
    then pass 15 "漂移态放行进账本（可审计谁在哪种尺子状态下放的行），干净态不污染该字段"
    else fail 15 "ruler_drift 留痕不对"; fi

    # ② 未登记的新判定文件：shasum -c 对它永远绿，必须单独抓
    repo2=$(new_repo a15b)
    goal_on "$repo2"
    mkdir -p "$repo2/.autopilot/checks"
    printf '#!/bin/sh\necho "RESULT A1 PASS ok"\n' > "$repo2/.autopilot/checks/run.sh"
    freeze_manifest_sh "$repo2"
    write_tasks "$repo2" <<EOF
{"tasks": [
 {"id": "T-81", "title": "T-81", "role": "Builder", "status": "pending", "deps": [],
  "write_set": ["src/a.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-81.md"}
], "epoch": 0}
EOF
    printf '<html>RESULT A9 PASS</html>\n' > "$repo2/.autopilot/checks/probe-late.html"
    $PY "$SCHED" start --repo "$repo2" --task T-81 >"$TMPROOT/a15b.unreg" 2>&1
    expect_rc 15 24 "$?" "冻结后新增的判定文件不在 MANIFEST → 拒绝派工"
    expect_contains 15 "$TMPROOT/a15b.unreg" "probe-late.html" "点名是哪份文件游离在冻结外"

    # ③ 没有 checks/ 的串行/早期工作区：不得被误拦
    repo3=$(new_repo a15c)
    goal_on "$repo3"
    write_tasks "$repo3" <<EOF
{"tasks": [
 {"id": "T-91", "title": "T-91", "role": "Builder", "status": "pending", "deps": [],
  "write_set": ["src/a.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-91.md"}
], "epoch": 0}
EOF
    $PY "$SCHED" start --repo "$repo3" --task T-91 >"$TMPROOT/a15c.nochecks" 2>&1
    expect_rc 15 0 "$?" "没有判定面的工作区不误拦"

    # ④ 有 checks/ 但从未冻结：违反前置，拦
    repo4=$(new_repo a15d)
    goal_on "$repo4"
    mkdir -p "$repo4/.autopilot/checks"
    printf '#!/bin/sh\necho "RESULT A1 PASS ok"\n' > "$repo4/.autopilot/checks/run.sh"
    write_tasks "$repo4" <<EOF
{"tasks": [
 {"id": "T-95", "title": "T-95", "role": "Builder", "status": "pending", "deps": [],
  "write_set": ["src/a.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-95.md"}
], "epoch": 0}
EOF
    $PY "$SCHED" start --repo "$repo4" --task T-95 >"$TMPROOT/a15d.noman" 2>&1
    expect_rc 15 24 "$?" "checks/ 存在但从未冻结 → 拒绝派工"
}

case_disabled_equivalence() {
    repo=$(new_repo a01)
    out="$TMPROOT/a01.prompt"
    sh "$HERE/round_prompt.sh" "$repo" 5 >"$out" 2>/dev/null
    if cmp -s "$out" "$GOLDEN"; then
        pass 1 "关闭 CONCURRENT 时 round_prompt 与串行 golden 逐字节一致"
    else
        fail 1 "关闭 CONCURRENT 时 round_prompt 输出漂移"
        diff -u "$GOLDEN" "$out" | head -20 | sed 's/^/    | /'
    fi

    got=$("$PY" "$SCHED" config --repo "$repo" --enabled 2>&1); rc=$?
    expect_rc 1 0 "$rc" "关闭态 config --enabled 可用"
    if [ "$got" = "0" ]; then pass 1 "关闭态 config --enabled 输出 0"; else fail 1 "config --enabled 输出 $got（应为 0）"; fi

    for sub in plan status recover; do
        "$PY" "$SCHED" "$sub" --repo "$repo" >"$TMPROOT/a01.$sub.log" 2>&1
        expect_rc 1 23 "$?" "关闭态 $sub 退出码 23"
    done
    "$PY" "$SCHED" start --repo "$repo" --task T-01 >/dev/null 2>&1
    expect_rc 1 23 "$?" "关闭态 start 退出码 23"
    "$PY" "$SCHED" finish --repo "$repo" --task T-01 --status done >/dev/null 2>&1
    expect_rc 1 23 "$?" "关闭态 finish 退出码 23"

    goal_on "$repo"
    out_on="$TMPROOT/a01.prompt.on"
    sh "$HERE/round_prompt.sh" "$repo" 5 >"$out_on" 2>/dev/null
    if cmp -s "$out_on" "$GOLDEN"; then
        fail 1 "开启 CONCURRENT 后 round_prompt 仍与串行 golden 相同（开关没接线）"
    else
        pass 1 "开启 CONCURRENT 后 round_prompt 插入并发段"
    fi
    expect_contains 1 "$out_on" "并发调度（GOAL.CONCURRENT.enable=true" "并发段内容正确"
    expect_not_contains 1 "$out_on" "绝对是本机路径" "并发段仍只用占位符"
}

# ---------------------------------------------------------------- A-conc-02 依赖未满足

# A-conc-02 依赖未就绪不得派发
case_deps() {
    repo=$(new_repo a02)
    goal_on "$repo"
    write_tasks "$repo" <<EOF
{"tasks": [
 $(task_json T-01 '[]' '["src/a.js"]'),
 $(task_json T-02 '["T-01"]' '["src/b.js"]')
], "epoch": 0}
EOF
    "$PY" "$SCHED" plan --repo "$repo" >"$TMPROOT/a02.plan1" 2>&1
    expect_contains 2 "$TMPROOT/a02.plan1" "READY T-01" "依赖已满足的卡 READY"
    expect_contains 2 "$TMPROOT/a02.plan1" "BLOCKED T-02 deps=T-01" "依赖未满足的卡 BLOCKED"
    expect_not_contains 2 "$TMPROOT/a02.plan1" "READY T-02" "未就绪卡不得出现在 READY"

    "$PY" "$SCHED" start --repo "$repo" --task T-02 >"$TMPROOT/a02.start2" 2>&1
    expect_rc 2 24 "$?" "依赖未满足时 start 拒绝"
    "$PY" "$SCHED" start --repo "$repo" --task T-01 >/dev/null 2>&1
    expect_rc 2 0 "$?" "依赖已满足的卡可 start"
    "$PY" "$SCHED" finish --repo "$repo" --task T-01 --status done >/dev/null 2>&1
    expect_rc 2 0 "$?" "完成 T-01"
    "$PY" "$SCHED" plan --repo "$repo" >"$TMPROOT/a02.plan2" 2>&1
    expect_contains 2 "$TMPROOT/a02.plan2" "READY T-02" "依赖完成后 T-02 转 READY"
}

# ---------------------------------------------------------------- A-conc-03 写集冲突

# A-conc-03 写集冲突拦截（相等与目录前缀）
case_write_conflict() {
    repo=$(new_repo a03)
    goal_on "$repo"
    write_tasks "$repo" <<EOF
{"tasks": [
 $(task_json T-11 '[]' '["src/a.js"]'),
 $(task_json T-12 '[]' '["src/a.js/sub"]'),
 $(task_json T-13 '[]' '["src/b.js"]')
], "epoch": 0}
EOF
    "$PY" "$SCHED" plan --repo "$repo" >"$TMPROOT/a03.plan1" 2>&1
    expect_contains 3 "$TMPROOT/a03.plan1" "READY T-11" "首张卡 READY"
    expect_contains 3 "$TMPROOT/a03.plan1" "DEFER T-12 conflict-with=T-11" "目录前缀也算写集冲突"
    expect_contains 3 "$TMPROOT/a03.plan1" "READY T-13" "互不冲突的卡仍 READY"

    "$PY" "$SCHED" start --repo "$repo" --task T-11 >/dev/null 2>&1
    expect_rc 3 0 "$?" "start T-11"
    "$PY" "$SCHED" start --repo "$repo" --task T-12 >"$TMPROOT/a03.start12" 2>&1
    expect_rc 3 22 "$?" "写集冲突 start 退 22"
    expect_contains 3 "$TMPROOT/a03.start12" "CONFLICT T-12" "冲突提示含卡号"
    "$PY" "$SCHED" start --repo "$repo" --task T-13 >/dev/null 2>&1
    expect_rc 3 0 "$?" "与运行中卡不冲突，可并行 start"
}

# ---------------------------------------------------------------- A-conc-04 锁与单写者

# A-conc-04 文件锁保护 tasks.json / ledger
case_locks() {
    repo=$(new_repo a04)
    goal_on "$repo"
    write_tasks "$repo" <<EOF
{"tasks": [
 $(task_json T-21 '[]' '["src/a.js"]'),
 $(task_json T-22 '[]' '["src/b.js"]')
], "epoch": 0}
EOF
    mkdir -p "$repo/.autopilot/locks/sched.lock"
    echo $$ > "$repo/.autopilot/locks/sched.lock/pid"
    AUTOPILOT_SCHED_LOCK_TIMEOUT=1 "$PY" "$SCHED" start --repo "$repo" --task T-21 >"$TMPROOT/a04.lock" 2>&1
    expect_rc 4 20 "$?" "调度锁被活进程持有时退 20"
    expect_contains 4 "$TMPROOT/a04.lock" "LOCK TIMEOUT" "锁超时有中文提示"

    echo 99999999 > "$repo/.autopilot/locks/sched.lock/pid"
    "$PY" "$SCHED" start --repo "$repo" --task T-21 >/dev/null 2>&1
    expect_rc 4 0 "$?" "陈旧调度锁可抢占"
    if [ -d "$repo/.autopilot/locks/sched.lock" ]; then fail 4 "调度锁未释放"; else pass 4 "调度锁用后释放"; fi

    mkdir -p "$repo/.autopilot/locks/state.lock"
    echo $$ > "$repo/.autopilot/locks/state.lock/pid"
    AUTOPILOT_STATE_LOCK_TIMEOUT=1 "$PY" "$STATUS" task "$repo" set T-22 done >"$TMPROOT/a04.statelock" 2>&1
    expect_rc 4 20 "$?" "状态锁被活进程持有时退 20"
    echo 99999999 > "$repo/.autopilot/locks/state.lock/pid"
    "$PY" "$STATUS" task "$repo" set T-22 done >/dev/null 2>&1
    expect_rc 4 0 "$?" "陈旧状态锁可抢占"

    if "$PY" - "$repo/.autopilot/tasks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if isinstance(d, dict) and isinstance(d.get("tasks"), list) else 1)
PY
    then pass 4 "加锁写入后 tasks.json 仍是合法 JSON"; else fail 4 "tasks.json 被写坏"; fi

    # 并发单写者：8 个进程同时改 8 张卡，一把锁串行化，不允许丢更新
    repo2=$(new_repo a04b)
    goal_on "$repo2"
    {
        printf '{"tasks": [\n'
        i=31
        while [ "$i" -le 38 ]; do
            task_json "T-$i" '[]' "[\"src/f$i.js\"]"
            if [ "$i" -lt 38 ]; then printf ',\n'; fi
            i=$((i + 1))
        done
        printf '\n], "epoch": 0}\n'
    } > "$repo2/.autopilot/tasks.json"

    pids=""
    i=31
    while [ "$i" -le 38 ]; do
        "$PY" "$STATUS" task "$repo2" set "T-$i" done >"$TMPROOT/a04b.$i.log" 2>&1 &
        pids="$pids $!"
        i=$((i + 1))
    done
    rc_all=0
    for p in $pids; do wait "$p" || rc_all=1; done
    if "$PY" - "$repo2/.autopilot/tasks.json" "$repo2/.autopilot/ledger.jsonl" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
ids = [t["id"] for t in doc["tasks"] if t.get("status") == "done"]
events = [json.loads(l) for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
task_events = [e for e in events if e.get("type") == "task" and e.get("status") == "done"]
sys.exit(0 if len(ids) == 8 and len(task_events) == 8 else 1)
PY
    then pass 4 "8 个并发 status.py task 全部生效且账本无丢失"
    else fail 4 "并发 status.py task 丢更新（rc_all=$rc_all）"; fi

    # 幂等：同一状态重复 set 不重写时间戳、不重复记账
    before=$("$PY" - "$repo/.autopilot/tasks.json" <<'PY'
import json, sys
t = next(x for x in json.load(open(sys.argv[1], encoding="utf-8"))["tasks"] if x["id"] == "T-22")
print("%s|%s|%s" % (t.get("ended_at"), t.get("attempts"), t.get("status")))
PY
)
    n_before=$(wc -l < "$repo/.autopilot/ledger.jsonl" | tr -d ' ')
    "$PY" "$STATUS" task "$repo" set T-22 done >"$TMPROOT/a04.idem" 2>&1
    after=$("$PY" - "$repo/.autopilot/tasks.json" <<'PY'
import json, sys
t = next(x for x in json.load(open(sys.argv[1], encoding="utf-8"))["tasks"] if x["id"] == "T-22")
print("%s|%s|%s" % (t.get("ended_at"), t.get("attempts"), t.get("status")))
PY
)
    n_after=$(wc -l < "$repo/.autopilot/ledger.jsonl" | tr -d ' ')
    if [ "$before" = "$after" ] && [ "$n_before" = "$n_after" ]; then
        pass 4 "重复 set 同一状态幂等（时间戳与账本都不变）"
    else
        fail 4 "重复 set 同一状态不幂等（before=$before after=$after ledger=$n_before→$n_after）"
    fi
    expect_contains 4 "$TMPROOT/a04.idem" "跳过" "幂等分支有提示"
}

# ---------------------------------------------------------------- A-conc-05 超时只记账

# A-conc-05 超时只记账标 failed，调度器不卡死
case_timeout_bookkeeping() {
    repo=$(new_repo a05)
    goal_on "$repo" 3 30
    write_tasks "$repo" <<EOF
{"tasks": [
 {"id": "T-41", "title": "T-41", "role": "Builder", "status": "doing", "deps": [],
  "write_set": ["src/a.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-41.md",
  "started_at": "2020-01-01T00:00:00+00:00", "dispatch_round": 1, "attempts": 0}
], "epoch": 0}
EOF
    "$PY" "$SCHED" plan --repo "$repo" >"$TMPROOT/a05.plan" 2>&1
    expect_contains 5 "$TMPROOT/a05.plan" "STALE T-41" "超时卡在 plan 里标 STALE"
    expect_contains 5 "$TMPROOT/a05.plan" "VERIFY-WINDOW closed" "有 RUNNING 时验证窗口关闭"

    "$PY" "$SCHED" recover --repo "$repo" >"$TMPROOT/a05.rec1" 2>&1
    expect_rc 5 0 "$?" "recover 正常退出"
    expect_contains 5 "$TMPROOT/a05.rec1" "RECOVER T-41" "recover 点名超时卡"

    if "$PY" - "$repo/.autopilot/tasks.json" "$repo/.autopilot/ledger.jsonl" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
t = doc["tasks"][0]
ok = (t["status"] == "failed" and t.get("attempts") == 1
      and "不杀工人" in (t.get("last_error") or ""))
ev = [json.loads(l) for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
timeouts = [e for e in ev if e.get("type") == "task-finish" and e.get("reason") == "timeout"]
sys.exit(0 if ok and len(timeouts) == 1 else 1)
PY
    then pass 5 "超时标 failed + attempts+1 + last_error 注明不杀工人"
    else fail 5 "超时记账字段不对"; fi

    "$PY" "$SCHED" recover --repo "$repo" >"$TMPROOT/a05.rec2" 2>&1
    expect_rc 5 0 "$?" "recover 幂等退出"
    expect_contains 5 "$TMPROOT/a05.rec2" "RECOVER none" "重复 recover 不重复记账"
    attempts=$("$PY" - "$repo/.autopilot/tasks.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["tasks"][0].get("attempts"))
PY
)
    if [ "$attempts" = "1" ]; then pass 5 "重复 recover 不重复计 attempts"; else fail 5 "attempts=$attempts（应为 1）"; fi
}

# ---------------------------------------------------------------- A-conc-06 Triage 前提置疑

# A-conc-06 跨任务同前提两次失败 → TRIAGE-HALT
case_triage_halt() {
    repo=$(new_repo a06)
    goal_on "$repo"
    write_tasks "$repo" <<EOF
{"tasks": [
 $(task_json T-51 '[]' '["src/x1.js"]' failed ',"premise_tag": "parser-state"'),
 $(task_json T-52 '[]' '["src/x2.js"]' failed ',"premise_tag": "parser-state"'),
 $(task_json T-53 '[]' '["src/x3.js"]' pending ',"premise_tag": "parser-state"'),
 $(task_json T-54 '[]' '["src/x4.js"]')
], "epoch": 0}
EOF
    "$PY" "$SCHED" plan --repo "$repo" >"$TMPROOT/a06.plan" 2>&1
    expect_contains 6 "$TMPROOT/a06.plan" "TRIAGE-HALT parser-state T-51,T-52" "同前提两次失败被识别"
    expect_contains 6 "$TMPROOT/a06.plan" "BLOCKED T-53 TRIAGE-HALT" "第三张同前提卡 BLOCKED"
    expect_contains 6 "$TMPROOT/a06.plan" "READY T-54" "不同前提的卡不受影响"

    "$PY" "$SCHED" start --repo "$repo" --task T-53 >"$TMPROOT/a06.start" 2>&1
    expect_rc 6 24 "$?" "Triage 前提置疑时 start 拒绝"
    expect_contains 6 "$TMPROOT/a06.start" "同前提已两次失败" "拒绝理由写清前提置疑"
}

# ---------------------------------------------------------------- A-conc-07 并发上限

# A-conc-07 max_concurrent_builder 并发上限
case_concurrency_limit() {
    repo=$(new_repo a07)
    goal_on "$repo" 1
    set_budget "$repo" 4 0
    write_tasks "$repo" <<EOF
{"tasks": [
 $(task_json T-61 '[]' '["src/a.js"]'),
 $(task_json T-62 '[]' '["src/b.js"]')
], "epoch": 0}
EOF
    "$PY" "$SCHED" config --repo "$repo" >"$TMPROOT/a07.config" 2>&1
    expect_contains 7 "$TMPROOT/a07.config" "limit=1" "max_concurrent_builder=1 生效"
    "$PY" "$SCHED" start --repo "$repo" --task T-61 >/dev/null 2>&1
    expect_rc 7 0 "$?" "第一张卡 start"
    "$PY" "$SCHED" start --repo "$repo" --task T-62 >"$TMPROOT/a07.start62" 2>&1
    expect_rc 7 21 "$?" "达到并发上限退 21"
    expect_contains 7 "$TMPROOT/a07.start62" "并发已达上限" "上限提示可读"
    "$PY" "$SCHED" finish --repo "$repo" --task T-61 --status done >/dev/null 2>&1
    "$PY" "$SCHED" start --repo "$repo" --task T-62 >/dev/null 2>&1
    expect_rc 7 0 "$?" "释放并发名额后可继续 start"

    repo2=$(new_repo a07b)
    goal_on "$repo2" 3
    set_budget "$repo2" 1 0
    "$PY" "$SCHED" config --repo "$repo2" >"$TMPROOT/a07b.config" 2>&1
    expect_contains 7 "$TMPROOT/a07b.config" "limit=1" "预算 parallel 比 CONCURRENT 更严时取 budget"
}

# ---------------------------------------------------------------- A-conc-08 验证窗口

# A-conc-08 并行全部结束才开验证窗口
case_verify_window() {
    repo=$(new_repo a08)
    goal_on "$repo"
    write_tasks "$repo" <<EOF
{"tasks": [
 $(task_json T-71 '[]' '["src/a.js"]'),
 $(task_json T-72 '[]' '["src/b.js"]')
], "epoch": 0}
EOF
    "$PY" "$SCHED" start --repo "$repo" --task T-71 >/dev/null 2>&1
    "$PY" "$SCHED" status --repo "$repo" >"$TMPROOT/a08.run" 2>&1
    expect_contains 8 "$TMPROOT/a08.run" "VERIFY-WINDOW closed" "有 RUNNING 时不开验证窗口"

    "$PY" "$HERE/resume.py" "$repo" >"$TMPROOT/a08.resume" 2>&1
    expect_contains 8 "$TMPROOT/a08.resume" "运行中: T-71(" "resume 显示并发运行中的卡"
    expect_contains 8 "$TMPROOT/a08.resume" "并发调度" "resume 注明结束走调度器"

    "$PY" "$SCHED" finish --repo "$repo" --task T-71 --status done >/dev/null 2>&1
    "$PY" "$SCHED" status --repo "$repo" >"$TMPROOT/a08.idle" 2>&1
    expect_contains 8 "$TMPROOT/a08.idle" "VERIFY-WINDOW open" "全部收尾后验证窗口打开"
    expect_not_contains 8 "$TMPROOT/a08.run" "VERIFY-WINDOW open" "运行中不得显示 open"

    repo_old=$(new_repo a08b)
    printf '{"tasks": [%s], "epoch": 0}\n' "$(task_json T-79 '[]' '["src/a.js"]')" \
        > "$repo_old/.autopilot/tasks.json"
    "$PY" "$HERE/resume.py" "$repo_old" >"$TMPROOT/a08b.resume" 2>&1
    expect_not_contains 8 "$TMPROOT/a08b.resume" "并发调度" "老工作区（无 dispatch_round）resume 输出不变"
}

# ---------------------------------------------------------------- A-conc-09 槽位预算

# A-conc-09 任务槽预算计数
case_slots() {
    repo=$(new_repo a09)
    goal_on "$repo" 3
    set_budget "$repo" 4 1
    write_tasks "$repo" <<EOF
{"tasks": [
 $(task_json T-81 '[]' '["src/a.js"]'),
 $(task_json T-82 '[]' '["src/b.js"]')
], "epoch": 0}
EOF
    "$PY" "$SCHED" start --repo "$repo" --task T-81 >/dev/null 2>&1
    expect_rc 9 0 "$?" "第 1 张卡占满槽位"
    "$PY" "$SCHED" finish --repo "$repo" --task T-81 --status done >/dev/null 2>&1
    "$PY" "$SCHED" status --repo "$repo" >"$TMPROOT/a09.status" 2>&1
    expect_contains 9 "$TMPROOT/a09.status" "SLOTS 1/1" "本轮槽位按派发计数"
    "$PY" "$SCHED" start --repo "$repo" --task T-82 >"$TMPROOT/a09.start" 2>&1
    expect_rc 9 21 "$?" "槽位用尽退 21"
    expect_contains 9 "$TMPROOT/a09.start" "槽位已用尽" "槽位提示可读"
}

# ---------------------------------------------------------------- A-conc-10 flex 卡不调度

# A-conc-10 flex 卡不进调度器
case_flex_serial() {
    repo=$(new_repo a10)
    goal_on "$repo"
    write_tasks "$repo" <<EOF
{"tasks": [
 $(task_json T-91 '[]' '["src/a.js"]'),
 {"id": "T-92", "title": "T-92", "role": "Builder", "status": "pending", "deps": [],
  "write_set": ["sandbox/draft/x.js"], "acceptance": [], "card": ".autopilot/tasks/T-92.md",
  "mode": "flex-light", "sandbox_target": "sandbox/draft"}
], "epoch": 0}
EOF
    "$PY" "$SCHED" plan --repo "$repo" >"$TMPROOT/a10.plan" 2>&1
    expect_contains 10 "$TMPROOT/a10.plan" "READY T-91" "strict 卡正常 READY"
    expect_contains 10 "$TMPROOT/a10.plan" "FLEX-SERIAL T-92" "flex 卡标 FLEX-SERIAL"
    expect_not_contains 10 "$TMPROOT/a10.plan" "READY T-92" "flex 卡不得进 READY"
    "$PY" "$SCHED" start --repo "$repo" --task T-92 >"$TMPROOT/a10.start" 2>&1
    expect_rc 10 24 "$?" "对 flex 卡 start 退 24"
    expect_contains 10 "$TMPROOT/a10.start" "不进调度器" "拒绝理由写明 flex 串行"
}

# A-conc-11 kill-running 形态与并发上限来源
case_kill_and_limit_source() {
    # H6 kill-running 的唯一诚实形态 + H26 并发上限来源必须显式
    repo=$(new_repo a11)
    goal_on "$repo" 3 30 kill-running
    cat > "$repo/.autopilot/host.json" <<'EOF'
{"host": "qoder-desktop", "primitives": {"spawn_session": true, "kill_session": true},
 "parallel_workers": 2}
EOF
    write_tasks "$repo" <<EOF
{"tasks": [
 {"id": "T-41", "title": "T-41", "role": "Builder", "status": "doing", "deps": [],
  "write_set": ["src/a.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-41.md",
  "started_at": "2020-01-01T00:00:00+00:00", "dispatch_round": 1, "attempts": 0,
  "session_id": "sess-abc"}
], "epoch": 0}
EOF
    "$PY" "$SCHED" plan --repo "$repo" >"$TMPROOT/a11.plan" 2>&1
    expect_contains 11 "$TMPROOT/a11.plan" "halt=kill-running" "kill-running 被认作合法策略"
    expect_contains 11 "$TMPROOT/a11.plan" "kill=directive" "宿主有 kill_session 时出 KILL 指令清单"
    expect_contains 11 "$TMPROOT/a11.plan" "limit=2" "host.parallel_workers 更严时取它"
    expect_contains 11 "$TMPROOT/a11.plan" "limit_from=host.parallel_workers" "上限来源显式打印"

    "$PY" "$SCHED" recover --repo "$repo" >"$TMPROOT/a11.rec" 2>&1
    expect_rc 11 0 "$?" "kill-running 下 recover 正常退出"
    expect_contains 11 "$TMPROOT/a11.rec" "RECOVER T-41" "超时仍先记账"
    expect_contains 11 "$TMPROOT/a11.rec" "KILL T-41 session=sess-abc" "点名交给执行器去杀"
    if "$PY" - "$repo/.autopilot/tasks.json" <<'PY'
import json, sys
t = json.load(open(sys.argv[1], encoding="utf-8"))["tasks"][0]
sys.exit(0 if t["status"] == "failed" and "不杀工人" in (t.get("last_error") or "") else 1)
PY
    then pass 11 "脚本自己仍不杀：状态只由记账改变"
    else fail 11 "kill-running 竟改变了记账口径"; fi

    # 无 session_id 的卡：只能声明杀不了
    repo2=$(new_repo a11b)
    goal_on "$repo2" 3 30 kill-running
    printf '%s\n' '{"primitives": {"kill_session": true}}' > "$repo2/.autopilot/host.json"
    write_tasks "$repo2" <<EOF
{"tasks": [
 {"id": "T-42", "title": "T-42", "role": "Builder", "status": "doing", "deps": [],
  "write_set": ["src/b.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-42.md",
  "started_at": "2020-01-01T00:00:00+00:00", "dispatch_round": 1, "attempts": 0}
], "epoch": 0}
EOF
    "$PY" "$SCHED" recover --repo "$repo2" >"$TMPROOT/a11b.rec" 2>&1
    expect_contains 11 "$TMPROOT/a11b.rec" "KILL-UNAVAILABLE T-42" "无 session_id 时声明无法杀"

    # 宿主没上报 kill_session → 退化为 wait-running 并说明原因
    repo3=$(new_repo a11c)
    goal_on "$repo3" 3 30 kill-running
    write_tasks "$repo3" <<EOF
{"tasks": [
 {"id": "T-43", "title": "T-43", "role": "Builder", "status": "doing", "deps": [],
  "write_set": ["src/c.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-43.md",
  "started_at": "2020-01-01T00:00:00+00:00", "dispatch_round": 1, "attempts": 0,
  "session_id": "sess-x"}
], "epoch": 0}
EOF
    "$PY" "$SCHED" plan --repo "$repo3" >"$TMPROOT/a11c.plan" 2>&1
    expect_contains 11 "$TMPROOT/a11c.plan" "halt=wait-running" "缺原语时退化为 wait-running"
    expect_contains 11 "$TMPROOT/a11c.plan" "kill=no" "退化后不出 KILL 清单"
    "$PY" "$SCHED" recover --repo "$repo3" >"$TMPROOT/a11c.rec" 2>&1
    expect_not_contains 11 "$TMPROOT/a11c.rec" "KILL T-43" "退化后绝不假装杀过"

    # 乱写的策略值仍然按未支持处理（口径没被放宽）
    repo4=$(new_repo a11d)
    goal_on "$repo4" 3 30 shout-loudly
    write_tasks "$repo4" <<EOF
{"tasks": [$(task_json T-44 '[]' '["src/d.js"]')], "epoch": 0}
EOF
    "$PY" "$SCHED" config --repo "$repo4" >"$TMPROOT/a11d.config" 2>&1
    expect_contains 11 "$TMPROOT/a11d.config" "未支持，按 wait-running 执行" "非法策略仍回落并说明"
    expect_contains 11 "$TMPROOT/a11d.config" "limit_from=CONCURRENT.max_concurrent_builder" "无更严上限时来源写明"

    # 关闭态：一行新增输出都不许漏进串行基线
    repo5=$(new_repo a11e)
    "$PY" "$SCHED" config --repo "$repo5" >"$TMPROOT/a11e.config" 2>&1
    expect_rc 11 0 "$?" "关闭态 config 仍可用"
    "$PY" "$SCHED" plan --repo "$repo5" >"$TMPROOT/a11e.plan" 2>&1
    expect_rc 11 23 "$?" "关闭态 plan 仍退 23"
    expect_not_contains 11 "$TMPROOT/a11e.plan" "kill=" "关闭态不出并发新字段"
}

# A-conc-12 非幂等卡重派需人工放行
case_idempotent_gate() {
    # H25：非幂等卡派过一次之后，未经人工放行不得重派
    repo=$(new_repo a12)
    goal_on "$repo"
    write_tasks "$repo" <<EOF
{"tasks": [
 {"id": "T-51", "title": "T-51", "role": "Builder", "status": "pending", "deps": [],
  "write_set": ["db/migrate/001.sql"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-51.md",
  "idempotent": false, "attempts": 1},
 {"id": "T-52", "title": "T-52", "role": "Builder", "status": "pending", "deps": [],
  "write_set": ["src/a.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-52.md",
  "idempotent": false, "attempts": 0},
 {"id": "T-53", "title": "T-53", "role": "Builder", "status": "pending", "deps": [],
  "write_set": ["src/b.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-53.md",
  "attempts": 3}
], "epoch": 0}
EOF
    "$PY" "$SCHED" start --repo "$repo" --task T-51 >"$TMPROOT/a12.block" 2>&1
    expect_rc 12 24 "$?" "idempotent=false 且 attempts>0 拒绝重派"
    expect_contains 12 "$TMPROOT/a12.block" "人工放行" "拒绝理由写明怎么放行"

    "$PY" "$SCHED" start --repo "$repo" --task T-51 --allow-non-idempotent >"$TMPROOT/a12.noflag" 2>&1
    expect_rc 12 2 "$?" "放行开关必须配 --note 理由"

    "$PY" "$SCHED" start --repo "$repo" --task T-52 --allow-non-idempotent --note "不该用放行开关" \
        >"$TMPROOT/a12.misuse" 2>&1
    expect_rc 12 2 "$?" "对没派过的卡用放行开关属用法错误"

    "$PY" "$SCHED" start --repo "$repo" --task T-51 --allow-non-idempotent \
        --note "使用者 2026-11-01 会话内确认迁移可重跑" >"$TMPROOT/a12.rel" 2>&1
    expect_rc 12 0 "$?" "带理由的人工放行可以重派"
    if "$PY" - "$repo/.autopilot/ledger.jsonl" <<'PY'
import json, sys
ev = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
rel = [e for e in ev if e.get("task") == "T-51" and e.get("human_release")]
sys.exit(0 if len(rel) == 1 and "可重跑" in rel[0]["human_release"] else 1)
PY
    then pass 12 "放行理由进账本（可审计谁放的行）"
    else fail 12 "人工放行没有留痕"; fi

    "$PY" "$SCHED" start --repo "$repo" --task T-52 >"$TMPROOT/a12.fresh" 2>&1
    expect_rc 12 0 "$?" "idempotent=false 但没派过 → 首派不受限"
    "$PY" "$SCHED" start --repo "$repo" --task T-53 >"$TMPROOT/a12.legacy" 2>&1
    expect_rc 12 0 "$?" "无 idempotent 字段的老卡按幂等处理，行为不变"

    # done 的卡必须留下 closed_round，H12 的收轮对账才有依据
    "$PY" "$SCHED" finish --repo "$repo" --task T-53 --status done >/dev/null 2>&1
    if "$PY" - "$repo/.autopilot/tasks.json" <<'PY'
import json, sys
t = [x for x in json.load(open(sys.argv[1], encoding="utf-8"))["tasks"] if x["id"] == "T-53"][0]
sys.exit(0 if t["status"] == "done" and t.get("closed_round") == 1 else 1)
PY
    then pass 12 "finish done 写入 closed_round，供 close-round 对账"
    else fail 12 "done 没写 closed_round"; fi
}

# A-conc-14 判定文件写集闸门（H40：新增判定源可派工，改考卷必须显式放行）
case_checks_edit_gate() {
    repo=$(new_repo a14)
    goal_on "$repo"
    mkdir -p "$repo/.autopilot/checks"
    printf '#!/bin/sh\necho "RESULT A1 PASS ok"\n' > "$repo/.autopilot/checks/run.sh"
    printf '#!/bin/sh\n\n' > "$repo/.autopilot/checks/accept.sh"
    # 夹具必须先冻结尺子，否则 start 会被 H42（no_manifest）抢先退 24，走不到 H40 改考卷闸门。
    freeze_manifest_sh "$repo"
    write_tasks "$repo" <<EOF
{"tasks": [
 {"id": "T-61", "title": "T-61", "role": "Builder", "status": "pending", "deps": [],
  "write_set": [".autopilot/checks/run.sh"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-61.md"},
 {"id": "T-62", "title": "T-62", "role": "Builder", "status": "pending", "deps": [],
  "write_set": [".autopilot/checks/probe-new.html"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-62.md"},
 {"id": "T-63", "title": "T-63", "role": "Builder", "status": "pending", "deps": [],
  "write_set": ["./src/a.js"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-63.md"},
 {"id": "T-64", "title": "T-64", "role": "Builder", "status": "pending", "deps": [],
  "write_set": [".autopilot/checks/accept.sh"], "acceptance": ["A1"], "card": ".autopilot/tasks/T-64.md"}
], "epoch": 0}
EOF
    "$PY" "$SCHED" start --repo "$repo" --task T-61 >"$TMPROOT/a14.block" 2>&1
    expect_rc 14 24 "$?" "写集含已存在的判定文件（run.sh）→ 拒绝派发"
    expect_contains 14 "$TMPROOT/a14.block" "改考卷" "拒绝理由要说清为什么这是改考卷"

    "$PY" "$SCHED" start --repo "$repo" --task T-62 >"$TMPROOT/a14.new" 2>&1
    expect_rc 14 0 "$?" "写集是 checks/ 下**还不存在**的新探针页 → 放行（新增判定源不是改考卷）"

    "$PY" "$SCHED" start --repo "$repo" --task T-63 >"$TMPROOT/a14.src" 2>&1
    expect_rc 14 0 "$?" "普通源码卡不受影响（关闭态不变）"

    "$PY" "$SCHED" finish --repo "$repo" --task T-62 --status done >/dev/null 2>&1
    "$PY" "$SCHED" start --repo "$repo" --task T-64 --allow-checks-edit >"$TMPROOT/a14.noflag" 2>&1
    expect_rc 14 2 "$?" "放行开关必须带 --note 理由"

    "$PY" "$SCHED" start --repo "$repo" --task T-64 --allow-checks-edit \
        --note "控制器 2026-11-01 批准：accept.sh 的判定阈值需按契约 A1 收紧" >"$TMPROOT/a14.rel" 2>&1
    expect_rc 14 0 "$?" "带理由的显式放行可以派"
    if "$PY" - "$repo/.autopilot/ledger.jsonl" <<'PY'
import json, sys
ev = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
hit = [e for e in ev if e.get("task") == "T-64" and e.get("checks_edit")]
miss = [e for e in ev if e.get("task") == "T-62" and e.get("checks_edit")]
sys.exit(0 if len(hit) == 1 and any("accept.sh" in e for e in hit[0]["checks_edit"]) and not miss else 1)
PY
    then pass 14 "改尺子的事实进账本（checks_edit 列出被动的判定文件），新增探针页不污染该字段"
    else fail 14 "checks_edit 留痕不对"; fi
}

# ---------------------------------------------------------------- A-conc-16 N5：touch_set / exclusive 冲突

# A-conc-16 临时触碰集与独占卡必须参与并发冲突判定（T-22 变异实验教训）
case_touch_exclusive() {
    repo=$(new_repo a16)
    goal_on "$repo"
    write_tasks "$repo" <<EOF
{"tasks": [
 $(task_json T-101 '[]' '["src/a.js"]' 'doing'),
 $(task_json T-102 '[]' '["src/b.js"]' 'pending' ',"touch_set":["src/a.js"]'),
 $(task_json T-103 '[]' '["src/c.js"]' 'pending'),
 $(task_json T-104 '[]' '["src/d.js"]' 'pending' ',"exclusive":true')
], "epoch": 0}
EOF
    "$PY" "$SCHED" plan --repo "$repo" >"$TMPROOT/a16.plan" 2>&1
    expect_contains 16 "$TMPROOT/a16.plan" "DEFER T-102 conflict-with=T-101" "touch_set 与运行卡写集相交也算冲突（跑完还原的临时触碰不能并发）"
    expect_contains 16 "$TMPROOT/a16.plan" "READY T-103" "与运行卡写集/touch 都不交集才 READY"
    expect_contains 16 "$TMPROOT/a16.plan" "DEFER T-104 conflict-with=T-101" "exclusive 卡不得与任何运行卡并发（与路径无关）"

    repo2=$(new_repo a16b)
    goal_on "$repo2"
    write_tasks "$repo2" <<EOF
{"tasks": [
 $(task_json T-105 '[]' '["src/x.js"]' 'pending' ',"exclusive":true'),
 $(task_json T-106 '[]' '["src/y.js"]' 'pending')
], "epoch": 0}
EOF
    "$PY" "$SCHED" plan --repo "$repo2" >"$TMPROOT/a16b.plan" 2>&1
    expect_contains 16 "$TMPROOT/a16b.plan" "READY T-105" "无运行卡时 exclusive 卡可 READY"
    "$PY" "$SCHED" start --repo "$repo2" --task T-105 >/dev/null 2>&1
    expect_rc 16 0 "$?" "start exclusive T-105"
    "$PY" "$SCHED" start --repo "$repo2" --task T-106 >"$TMPROOT/a16b.start106" 2>&1
    expect_rc 16 22 "$?" "另一张普通卡不得与运行中的 exclusive 并发（退 22）"
    expect_contains 16 "$TMPROOT/a16b.start106" "CONFLICT T-106" "独占冲突提示含卡号"
}

case_disabled_equivalence
case_deps
case_write_conflict
case_locks
case_timeout_bookkeeping
case_triage_halt
case_concurrency_limit
case_verify_window
case_slots
case_flex_serial
case_kill_and_limit_source
case_idempotent_gate
case_checks_edit_gate
case_replay_determinism
case_ruler_drift_gate
case_touch_exclusive

if [ "$FAILED" -gt 0 ]; then
    printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
    exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
