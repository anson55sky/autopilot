#!/bin/sh
# status.py 自检：C3 时间戳健壮 / C4 收轮幂等 / C5 轮次指标 / H12 收轮对账 / H9 时间账
# 只在 mktemp -d 造临时仓库，不碰真实 skill、也不碰 draft 的 git 历史。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STATUS="$HERE/status.py"
PY=${PYTHON:-python3}

TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPROOT"' EXIT INT TERM

PASSED=0
FAILED=0

pass() {
    PASSED=$((PASSED + 1))
    printf 'PASS %s %s\n' "$1" "$2"
}

fail() {
    FAILED=$((FAILED + 1))
    printf 'FAIL %s %s\n' "$1" "$2"
}

# 写一份最小 state.json；第 2 个参数是 started_at 的 JSON 字面量
write_state() {
    printf '{"started_at": %s, "phase": "execute", "rounds_used": 0, "mode": "auto", "budget": {"max_rounds": 10, "max_minutes": 600, "max_calls": 100}}\n' \
        "$2" > "$1"
}

new_repo() {
    d="$TMPROOT/$1"
    mkdir -p "$d/.autopilot"
    printf '%s\n' "$d"
}

# ---------------------------------------------------------------- C3

# 本地时区钉成 UTC+8：这样"缺偏移按 UTC 解释"与"缺偏移按本地解释"会显示成不同钟点，
# 断言才有鉴别力（否则在 UTC 机器上两者无法区分）。
# 用 POSIX 形式的 TZ，不依赖系统装没装 tzdata。
export TZ=UTC-8

# now_minus <分钟> → UTC 墙钟、故意不带偏移
now_minus_naive() {
    $PY -c 'import datetime, sys
d = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=int(sys.argv[1]))
print(d.replace(tzinfo=None).isoformat(timespec="seconds"))' "$1"
}

# now_minus <分钟> → 同一时刻、写成 +08:00 偏移
now_minus_aware() {
    $PY -c 'import datetime, sys
d = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=int(sys.argv[1]))
print(d.astimezone(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds"))' "$1"
}

# 按 0.9 口径显示成本地钟点：缺偏移 → 按 UTC 解释
local_view() {
    $PY -c 'import datetime, sys
d = datetime.datetime.fromisoformat(sys.argv[1])
if d.tzinfo is None:
    d = d.replace(tzinfo=datetime.timezone.utc)
print(d.astimezone().strftime("%Y-%m-%d %H:%M"))' "$1"
}

# 反例：缺偏移若被当成本地时间，会显示成什么钟点
local_view_as_local() {
    $PY -c 'import datetime, sys
d = datetime.datetime.fromisoformat(sys.argv[1])
print(d.astimezone().strftime("%Y-%m-%d %H:%M"))' "$1"
}

case_naive() {
    repo=$(new_repo c1)
    naive=$(now_minus_naive 90)
    write_state "$repo/.autopilot/state.json" "\"$naive\""
    out=$($PY "$STATUS" summary "$repo" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        fail 1 "naive 时间戳退出码 $rc"
        return
    fi
    case "$out" in
        *Traceback*) fail 1 "naive 时间戳出现 traceback"; return ;;
    esac
    case "$out" in
        *"用时: 90/600 分钟"*) ;;
        *) fail 1 "naive 时间戳按 UTC 解释后用时不对: $out"; return ;;
    esac
    want=$(local_view "$naive")
    case "$out" in
        *"开始:   $want"*) ;;
        *) fail 1 "naive 时间戳显示的不是 UTC 解释后的本地时间 $want: $out"; return ;;
    esac
    as_local=$(local_view_as_local "$naive")
    case "$out" in
        *"开始:   $as_local"*)
            fail 1 "naive 时间戳被当成本地时间解释了（应为 UTC）: $out"
            return ;;
    esac
    case "$out" in
        *"警告:"*"缺时区偏移"*) ;;
        *) fail 1 "naive 时间戳没有记警告: $out"; return ;;
    esac
    pass 1 "naive 时间戳按 UTC 解释 + 记警告 + 用时正确"
}

case_garbage() {
    repo=$(new_repo c2)
    write_state "$repo/.autopilot/state.json" '"不是个时间戳"'
    out=$($PY "$STATUS" summary "$repo" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        fail 2 "坏时间戳退出码 $rc"
        return
    fi
    case "$out" in
        *Traceback*) fail 2 "坏时间戳出现 traceback"; return ;;
    esac
    case "$out" in
        *unknown*) pass 2 "坏时间戳不崩且显示 unknown" ;;
        *) fail 2 "坏时间戳没有显示 unknown: $out" ;;
    esac
}

case_empty() {
    repo=$(new_repo c3)
    write_state "$repo/.autopilot/state.json" '""'
    out=$($PY "$STATUS" summary "$repo" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        fail 3 "空时间戳退出码 $rc"
        return
    fi
    case "$out" in
        *Traceback*) fail 3 "空时间戳出现 traceback"; return ;;
    esac
    case "$out" in
        *unknown*) pass 3 "空时间戳不崩且显示 unknown" ;;
        *) fail 3 "空时间戳没有显示 unknown: $out" ;;
    esac
}

case_aware() {
    repo=$(new_repo c4)
    aware=$(now_minus_aware 90)
    write_state "$repo/.autopilot/state.json" "\"$aware\""
    out=$($PY "$STATUS" summary "$repo" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        fail 4 "带偏移时间戳退出码 $rc"
        return
    fi
    case "$out" in
        *Traceback*) fail 4 "带偏移时间戳出现 traceback"; return ;;
    esac
    case "$out" in
        *"用时: 90/600 分钟"*) ;;
        *) fail 4 "带偏移时间戳用时不对: $out"; return ;;
    esac
    want=$(local_view "$aware")
    case "$out" in
        *"开始:   $want"*) ;;
        *) fail 4 "带偏移时间戳显示不对（应为 $want）: $out"; return ;;
    esac
    case "$out" in
        *"警告:"*) fail 4 "带偏移时间戳不该有警告: $out"; return ;;
    esac
    pass 4 "带偏移时间戳按偏移解释 + 用时正确 + 无警告"
}

# ---------------------------------------------------------------- C4

case_close_twice() {
    repo=$(new_repo c5)
    mkdir -p "$repo/.autopilot/rounds"
    write_state "$repo/.autopilot/state.json" '""'
    cat > "$repo/.autopilot/rounds/r-01.json" <<'EOF'
{"round": 1, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 2, "notes": "第一轮"}
EOF
    out1=$($PY "$STATUS" close-round "$repo" "$repo/.autopilot/rounds/r-01.json" 2>&1)
    rc1=$?
    if [ "$rc1" -ne 0 ]; then
        fail 5 "第一次收轮退出码 $rc1: $out1"
        return
    fi
    cp "$repo/.autopilot/rounds/r-01.json" "$TMPROOT/c5-snap.json"
    out2=$($PY "$STATUS" close-round "$repo" "$repo/.autopilot/rounds/r-01.json" 2>&1)
    rc2=$?
    if [ "$rc2" -ne 0 ]; then
        fail 5 "第二次收轮退出码 $rc2: $out2"
        return
    fi
    if ! cmp -s "$TMPROOT/c5-snap.json" "$repo/.autopilot/rounds/r-01.json"; then
        fail 5 "第二次收轮改了轮次文件"
        return
    fi
    case "$out2" in
        *跳过*) ;;
        *) fail 5 "第二次收轮没有走跳过分支: $out2"; return ;;
    esac
    n=$(ls "$repo/.autopilot/rounds" | grep -c '^r-[0-9][0-9]*\.json$')
    if [ "$n" -ne 1 ]; then
        fail 5 "rounds/ 里有 $n 个轮次文件（应为 1）"
        return
    fi
    used=$($PY -c 'import json,sys; print(json.load(open(sys.argv[1])).get("rounds_used"))' "$repo/.autopilot/state.json")
    if [ "$used" != "1" ]; then
        fail 5 "rounds_used 被记成 $used（应为 1）"
        return
    fi
    pass 5 "close-round 跑两次幂等"
}

case_flex_round() {
    repo=$(new_repo c6)
    mkdir -p "$repo/.autopilot/rounds" "$repo/sandbox/.gate"
    write_state "$repo/.autopilot/state.json" '"2026-01-01T07:00:00+08:00"'
    cat > "$repo/sandbox/.gate/state.json" <<'EOF'
{"light_used": 1, "heavy_used": 0, "flex_calls": 1, "permits": [{"permit_id": "p-1", "used": false, "revoked": false}]}
EOF
    cat > "$repo/sandbox/.gate/gate.jsonl" <<'EOF'
{"round": 1, "task": "t-1", "mode": "flex-light", "decision": "allow", "code": 0, "reason": "额度内", "ts": "2026-01-01T08:00:00+08:00", "gate_version": "autopilot selftest"}
EOF
    cat > "$repo/.autopilot/ledger.jsonl" <<'EOF'
{"type": "worker", "task": "t-1", "ts": "2026-01-01T08:00:00+08:00"}
{"type": "verifier", "task": "t-1", "ts": "2026-01-01T08:05:00+08:00"}
EOF
    cat > "$repo/.autopilot/rounds/r-01.json" <<'EOF'
{"round": 1, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 1}
EOF
    out1=$($PY "$STATUS" close-round "$repo" "$repo/.autopilot/rounds/r-01.json" 2>&1)
    rc1=$?
    if [ "$rc1" -ne 0 ]; then
        fail 6 "flex 轮次收轮退出码 $rc1: $out1"
        return
    fi
    if ! $PY -c 'import json,sys
d = json.load(open(sys.argv[1]))
f = d.get("flex") or {}
sys.exit(0 if "flex" in f and f.get("flex") == 1 and f.get("decisions") == 1 and f.get("flex_decisions") == 1 else 1)' \
        "$repo/.autopilot/rounds/r-01.json"; then
        fail 6 "轮次记录里没记上 flex 用量"
        return
    fi
    cp "$repo/.autopilot/rounds/r-01.json" "$TMPROOT/c6-snap.json"
    out2=$($PY "$STATUS" close-round "$repo" "$repo/.autopilot/rounds/r-01.json" 2>&1)
    rc2=$?
    if [ "$rc2" -ne 0 ]; then
        fail 6 "flex 轮次第二次收轮退出码 $rc2: $out2"
        return
    fi
    if ! cmp -s "$TMPROOT/c6-snap.json" "$repo/.autopilot/rounds/r-01.json"; then
        fail 6 "flex 轮次第二次收轮改了 flex 计数"
        return
    fi
    used=$($PY -c 'import json,sys; print(json.load(open(sys.argv[1])).get("rounds_used"))' "$repo/.autopilot/state.json")
    if [ "$used" != "1" ]; then
        fail 6 "flex 轮次 rounds_used 被记成 $used（应为 1）"
        return
    fi
    pass 6 "flex 轮次收轮幂等且记上 flex 字段"
}

# ---------------------------------------------------------------- C5（合同变更轮）

case_contract_change() {
    repo=$(new_repo c8)
    mkdir -p "$repo/.autopilot/rounds"
    cat > "$repo/.autopilot/state.json" <<'EOF'
{"started_at": "2026-01-01T00:00:00+00:00", "phase": "execute", "rounds_used": 1, "closed_rounds": [1], "no_progress_streak": 1, "last_passed": ["A1"], "budget": {"max_rounds": 10}}
EOF
    cat > "$repo/.autopilot/rounds/r-01.json" <<'EOF'
{"round": 1, "epoch": 0, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 0}
EOF
    cat > "$repo/.autopilot/rounds/r-02.json" <<'EOF'
{"round": 2, "epoch": 1, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 0}
EOF
    out=$($PY "$STATUS" close-round "$repo" "$repo/.autopilot/rounds/r-02.json" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        fail 9 "合同变更轮收轮退出码 $rc: $out"
        return
    fi
    streak=$($PY -c 'import json,sys; print(json.load(open(sys.argv[1])).get("no_progress_streak"))' "$repo/.autopilot/state.json")
    if [ "$streak" != "0" ]; then
        fail 9 "合同变更轮后零进展连击应为 0，实际 $streak: $out"
        return
    fi
    case "$out" in
        *"合同 epoch 0→1"*) ;;
        *) fail 9 "收轮输出没记合同变更: $out"; return ;;
    esac
    if ! $PY -c 'import json,sys
d = json.load(open(sys.argv[1]))
cc = (d.get("detail") or {}).get("contract_change") or {}
sys.exit(0 if cc.get("from") == 0 and cc.get("to") == 1 else 1)' \
        "$repo/.autopilot/rounds/r-02.metrics.json"; then
        fail 9 "指标文件没记 contract_change"
        return
    fi
    cat > "$repo/.autopilot/rounds/r-03.json" <<'EOF'
{"round": 3, "epoch": 1, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 0}
EOF
    out=$($PY "$STATUS" close-round "$repo" "$repo/.autopilot/rounds/r-03.json" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        fail 9 "同 epoch 收轮退出码 $rc: $out"
        return
    fi
    streak=$($PY -c 'import json,sys; print(json.load(open(sys.argv[1])).get("no_progress_streak"))' "$repo/.autopilot/state.json")
    if [ "$streak" != "1" ]; then
        fail 9 "同 epoch 且无新增通过应计 1 次零进展，实际 $streak: $out"
        return
    fi
    pass 9 "合同变更轮不计零进展，同 epoch 空轮仍计"
}

# ---------------------------------------------------------------- C6（审计文件隔离 + 指标）

case_audit_not_record() {
    repo=$(new_repo c8)
    mkdir -p "$repo/.autopilot/rounds" "$repo/sandbox/.gate"
    write_state "$repo/.autopilot/state.json" '"2026-01-01T07:00:00+08:00"'
    cat > "$repo/sandbox/.gate/state.json" <<'EOF'
{"light_used": 1, "heavy_used": 0, "flex_calls": 1}
EOF
    cat > "$repo/sandbox/.gate/gate.jsonl" <<'EOF'
{"round": 1, "task": "t-1", "mode": "flex-light", "decision": "allow", "ts": "2026-01-01T08:00:00+08:00"}
EOF
    cat > "$repo/.autopilot/rounds/r-01.json" <<'EOF'
{"round": 1, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 1}
EOF
    $PY "$STATUS" close-round "$repo" "$repo/.autopilot/rounds/r-01.json" >/dev/null 2>&1
    cat > "$repo/.autopilot/rounds/r-01.flex.json" <<'EOF'
{"round": 1, "epoch": 0, "flex_used": {"light": 1, "heavy": 0, "calls": 1}, "artifacts": []}
EOF
    cat > "$repo/.autopilot/rounds/r-02.json" <<'EOF'
{"round": 2, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 0}
EOF
    out=$($PY "$STATUS" close-round "$repo" "$repo/.autopilot/rounds/r-02.json" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        fail 8 "审计文件在场时收轮退出码 $rc: $out"
        return
    fi
    if ! $PY -c 'import json,sys
d = json.load(open(sys.argv[1]))
f = d.get("flex") or {}
cum = f.get("cumulative") or {}
sys.exit(0 if f.get("light") == 0 and f.get("decisions") == 0 and cum.get("light_used") == 1 else 1)' \
        "$repo/.autopilot/rounds/r-02.json"; then
        fail 8 "r-01.flex.json 被当成上一轮记录，第 2 轮 flex 增量算错"
        return
    fi
    if ! $PY -c 'import json,sys
d = json.load(open(sys.argv[1]))
f = d.get("flex") or {}
sys.exit(0 if f.get("usage_rate") is None and "均为 0" in (f.get("usage_rate_basis") or "") else 1)' \
        "$repo/.autopilot/rounds/r-02.json"; then
        fail 8 "第 2 轮无调用无决策时占比应记为不适用"
        return
    fi
    pass 8 "r-01.flex.json 不算轮次记录（第 2 轮增量为 0、累计仍为 1）"
}

case_metrics() {
    repo=$(new_repo c7)
    mkdir -p "$repo/.autopilot/rounds"
    write_state "$repo/.autopilot/state.json" '""'
    cat > "$repo/.autopilot/rounds/r-01.json" <<'EOF'
{"round": 1, "verdict": "fail", "passed": [], "failed": ["A1"], "tasks_closed": 0}
EOF
    out=$($PY "$STATUS" close-round "$repo" "$repo/.autopilot/rounds/r-01.json" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        fail 7 "收轮退出码 $rc: $out"
        return
    fi
    if [ ! -f "$repo/.autopilot/rounds/r-01.metrics.json" ]; then
        fail 7 "收轮后没有生成 r-01.metrics.json"
        return
    fi
    if ! $PY -c 'import json,sys
d = json.load(open(sys.argv[1]))
need = ["round", "calls_used", "elapsed_minutes", "max_parallel", "rework_rate", "flex_usage_rate"]
missing = [k for k in need if k not in d]
sys.exit(1 if missing else 0)' "$repo/.autopilot/rounds/r-01.metrics.json"; then
        fail 7 "指标文件缺少必需字段"
        return
    fi
    pass 7 "收轮写出指标文件且字段齐全"
}

# ---------------------------------------------------------------- C7（返工率与并发峰值）

case_rework_parallel() {
    repo=$(new_repo c9)
    mkdir -p "$repo/.autopilot/rounds"
    write_state "$repo/.autopilot/state.json" '"2026-01-01T07:00:00+00:00"'
    cat > "$repo/.autopilot/ledger.jsonl" <<'EOF'
{"type": "worker", "task": "t-1", "ts": "2026-01-01T08:00:00+00:00"}
{"type": "worker", "task": "t-1", "ts": "2026-01-01T08:10:00+00:00"}
{"type": "worker", "task": "t-2", "ts": "2026-01-01T08:15:00+00:00"}
{"type": "verifier", "task": "t-1", "ts": "2026-01-01T08:20:00+00:00"}
EOF
    cat > "$repo/.autopilot/rounds/r-01.json" <<'EOF'
{"round": 1, "epoch": 0, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 1, "started_at": "2026-01-01T08:00:00+00:00", "parallel_peak": 2}
EOF
    out=$($PY "$STATUS" close-round "$repo" "$repo/.autopilot/rounds/r-01.json" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        fail 10 "收轮退出码 $rc: $out"
        return
    fi
    if ! $PY -c 'import json,sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if d.get("max_parallel") == 2 and d.get("rework_rate") == 0.25 else 1)' \
        "$repo/.autopilot/rounds/r-01.metrics.json"; then
        fail 10 "并发峰值或返工率不对: $(cat "$repo/.autopilot/rounds/r-01.metrics.json")"
        return
    fi
    if ! $PY -c 'import json,sys
d = json.load(open(sys.argv[1]))
bad = [k for k in ("max_parallel", "rework_rate") if k in (d.get("unknown_reasons") or {})]
sys.exit(1 if bad else 0)' "$repo/.autopilot/rounds/r-01.metrics.json"; then
        fail 10 "两项已有明证却仍记 unknown_reasons"
        return
    fi
    pass 10 "重复派发推出返工率 0.25，parallel_peak 记入并发峰值"
}

# ---------------------------------------------------------------- C8（异形 JSON 不崩）

case_corrupt_files() {
    repo=$(new_repo c10)
    mkdir -p "$repo/.autopilot/checks"
    printf '%s\n' '{"goal": 123, "phase": "weird", "rounds_used": "x", "no_progress_streak": "y", "budget": {"max_rounds": "z"}}' \
        > "$repo/.autopilot/state.json"
    printf '[1,2]\n' > "$repo/.autopilot/tasks.json"
    printf '[1,2]\n' > "$repo/.autopilot/checks/last-result.json"
    printf '%s\n' '{broken' '{"type":"worker","ts":"nope"}' > "$repo/.autopilot/ledger.jsonl"
    out=$($PY "$STATUS" summary "$repo" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        fail 11 "异形 JSON 下 summary 退出码 $rc: $out"
        return
    fi
    case "$out" in
        *Traceback*) fail 11 "异形 JSON 下出现 traceback"; return ;;
    esac
    case "$out" in
        *"目标:"*) pass 11 "异形 JSON 下 summary 不崩且照样输出" ;;
        *) fail 11 "异形 JSON 下 summary 输出不完整: $out" ;;
    esac
}

# ---------------------------------------------------------------- H12 收轮对账

mk_tasks() {
    # $1=目标文件 $2=每张卡的附加字段串 $3=done 的张数
    _t="$1"; _extra="$2"; _n="$3"
    {
        printf '{"epoch": 1, "tasks": ['
        _i=1
        while [ "$_i" -le "$_n" ]; do
            [ "$_i" -gt 1 ] && printf ','
            printf '{"id": "T-%02d", "title": "x", "role": "Builder", "status": "done", "deps": [], "write_set": ["src/f%d.js"], "acceptance": ["A%d"], "card": "c.md"%s}' \
                "$_i" "$_i" "$_i" "$_extra"
            _i=$((_i + 1))
        done
        printf ']}'
    } > "$_t"
}

case_close_check() {
    # 1) 声明数与 closed_round 记账一致 → 正常收轮
    repo=$(new_repo h12a)
    mkdir -p "$repo/.autopilot/rounds"
    write_state "$repo/.autopilot/state.json" "\"$(now_minus_aware 60)\""
    mk_tasks "$repo/.autopilot/tasks.json" ', "closed_round": 1' 2
    cat > "$repo/.autopilot/rounds/r-01.json" <<'EOF'
{"round": 1, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 2, "notes": "对账一致"}
EOF
    out=$($PY "$STATUS" close-round "$repo" "$repo/.autopilot/rounds/r-01.json" 2>&1); rc=$?
    if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q "CLOSE CHECK 通过"; then
        pass 12 "tasks_closed 与 closed_round 一致时正常收轮"
    else
        fail 12 "一致却没通过（rc=$rc）：$out"
    fi

    # 2) 声明 0 但记了 2 张关闭 → 拒收，且不许留下半个轮次的写盘
    repo2=$(new_repo h12b)
    mkdir -p "$repo2/.autopilot/rounds"
    write_state "$repo2/.autopilot/state.json" "\"$(now_minus_aware 60)\""
    mk_tasks "$repo2/.autopilot/tasks.json" ', "closed_round": 1' 2
    cat > "$repo2/.autopilot/rounds/r-01.json" <<'EOF'
{"round": 1, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 0, "notes": "验证者说没关闭"}
EOF
    out2=$($PY "$STATUS" close-round "$repo2" "$repo2/.autopilot/rounds/r-01.json" 2>&1); rc2=$?
    ru=$($PY -c 'import json,sys;print(json.load(open(sys.argv[1]))["rounds_used"])' \
        "$repo2/.autopilot/state.json")
    if [ "$rc2" -eq 24 ] && [ "$ru" = "0" ] && printf '%s' "$out2" | grep -q "拒绝收轮" \
        && [ ! -f "$repo2/.autopilot/rounds/r-01.metrics.json" ] \
        && [ ! -f "$repo2/.autopilot/rounds/r-01.json.lock" ]; then
        pass 12 "对不上时退 24，且 state/轮次记录/指标一个字都没写"
    else
        fail 12 "该拒的没拒（rc=$rc2 rounds_used=$ru）：$out2"
    fi
    if grep -q '"type": "round"' "$repo2/.autopilot/ledger.jsonl" 2>/dev/null; then
        fail 12 "拒收轮却往账本写了 round 事件"
    else
        pass 12 "拒收轮不污染账本"
    fi

    # 3) 只有 ended_at 的卡按时间窗对账
    repo3=$(new_repo h12c)
    mkdir -p "$repo3/.autopilot/rounds"
    write_state "$repo3/.autopilot/state.json" "\"$(now_minus_aware 60)\""
    mk_tasks "$repo3/.autopilot/tasks.json" ", \"ended_at\": \"$(now_minus_aware 5)\"" 1
    cat > "$repo3/.autopilot/rounds/r-01.json" <<'EOF'
{"round": 1, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 1, "notes": "时间窗对账"}
EOF
    out3=$($PY "$STATUS" close-round "$repo3" "$repo3/.autopilot/rounds/r-01.json" 2>&1); rc3=$?
    if [ "$rc3" -eq 0 ] && printf '%s' "$out3" | grep -q "CLOSE CHECK 通过"; then
        pass 12 "ended_at 落在本轮窗口内也计入对账"
    else
        fail 12 "时间窗对账没通过（rc=$rc3）：$out3"
    fi

    # 4) 老工作区（没有任何记账字段）：行为与加校验前完全一致
    repo4=$(new_repo h12d)
    mkdir -p "$repo4/.autopilot/rounds"
    write_state "$repo4/.autopilot/state.json" '""'
    mk_tasks "$repo4/.autopilot/tasks.json" '' 3
    cat > "$repo4/.autopilot/rounds/r-01.json" <<'EOF'
{"round": 1, "verdict": "pass", "passed": ["A1"], "failed": [], "tasks_closed": 3, "notes": "老工作区"}
EOF
    out4=$($PY "$STATUS" close-round "$repo4" "$repo4/.autopilot/rounds/r-01.json" 2>&1); rc4=$?
    if [ "$rc4" -eq 0 ] && ! printf '%s' "$out4" | grep -q "CLOSE CHECK"; then
        pass 12 "无记账字段时不打印校验行，也不拦老工作区"
    else
        fail 12 "老工作区被新校验影响（rc=$rc4）：$out4"
    fi
}

# ---------------------------------------------------------------- H9 时间账

case_clock_accounting() {
    repo=$(new_repo h9)
    mkdir -p "$repo/.autopilot/rounds"
    write_state "$repo/.autopilot/state.json" "\"$(now_minus_aware 120)\""

    # 1) 老工作区（没有任何 pause/resume 事件）：summary 不得出现新行，口径一字不变
    out0=$($PY "$STATUS" summary "$repo" 2>&1)
    if printf '%s' "$out0" | grep -q "时间账"; then
        fail 9 "没有 pause 事件却打印了时间账"
    else
        pass 9 "无 pause/resume 事件时 summary 与旧口径一致"
    fi

    # 2) 手写一对 pause/resume（pause 在 60 分钟前，resume 在 30 分钟前 → 暂停 30 分钟）
    {
        printf '%s\n' "{\"type\": \"pause\", \"ts\": \"$(now_minus_aware 60)\"}"
        printf '%s\n' "{\"type\": \"resume\", \"ts\": \"$(now_minus_aware 30)\"}"
    } >> "$repo/.autopilot/ledger.jsonl"
    out1=$($PY "$STATUS" summary "$repo" 2>&1)
    line=$(printf '%s' "$out1" | grep "时间账")
    if printf '%s' "$line" | $PY -c '
import re, sys
m = re.search(r"墙钟 (\d+) 分钟 = 活跃 (\d+) \+ 暂停/休眠 (\d+)", sys.stdin.read())
if not m:
    sys.exit(1)
wall, active, slept = (int(x) for x in m.groups())
sys.exit(0 if slept == 30 and active + slept == wall and wall in (119, 120) else 1)
'; then
        pass 9 "墙钟拆成活跃 + 暂停 30 分钟，且三段自洽"
    else
        fail 9 "时间账算错：$line"
    fi
    if printf '%s' "$out1" | grep -qE "用时: (119|120)/600 分钟"; then
        pass 9 "停止判定仍按墙钟，没有因为活跃时长而放宽"
    else
        fail 9 "墙钟口径被改动了：$(printf '%s' "$out1" | grep 用时)"
    fi

    # 3) pause / resume 子命令的配对与幂等
    repo2=$(new_repo h9b)
    write_state "$repo2/.autopilot/state.json" "\"$(now_minus_aware 10)\""
    o=$($PY "$STATUS" resume "$repo2" 2>&1); r=$?
    if [ "$r" -eq 2 ] && printf '%s' "$o" | grep -q "没有未闭合的 pause"; then
        pass 9 "没有 pause 时 resume 被拒"
    else
        fail 9 "裸 resume 没被拦（rc=$r）：$o"
    fi
    $PY "$STATUS" pause "$repo2" --note "机器休眠" >/dev/null 2>&1
    $PY "$STATUS" pause "$repo2" --note "重复" >/dev/null 2>&1
    n=$(grep -c '"type": "pause"' "$repo2/.autopilot/ledger.jsonl")
    if [ "$n" = "1" ]; then
        pass 9 "重复 pause 只记一条"
    else
        fail 9 "重复 pause 记了 $n 条"
    fi
    $PY "$STATUS" resume "$repo2" >/dev/null 2>&1
    n=$(grep -c '"type": "resume"' "$repo2/.autopilot/ledger.jsonl")
    if [ "$n" = "1" ]; then
        pass 9 "resume 正常闭合 pause 窗口"
    else
        fail 9 "resume 记账条数 $n"
    fi

    # 4) 指标文件带上活跃/暂停时长
    repo3=$(new_repo h9c)
    mkdir -p "$repo3/.autopilot/rounds"
    write_state "$repo3/.autopilot/state.json" "\"$(now_minus_aware 90)\""
    printf '%s\n' "{\"type\": \"pause\", \"ts\": \"$(now_minus_aware 40)\"}" >> "$repo3/.autopilot/ledger.jsonl"
    printf '%s\n' "{\"type\": \"resume\", \"ts\": \"$(now_minus_aware 20)\"}" >> "$repo3/.autopilot/ledger.jsonl"
    cat > "$repo3/.autopilot/rounds/r-01.json" <<'EOF'
{"round": 1, "verdict": "fail", "passed": ["A1"], "failed": ["A2"], "tasks_closed": 0, "notes": "时间账指标"}
EOF
    $PY "$STATUS" close-round "$repo3" "$repo3/.autopilot/rounds/r-01.json" >/dev/null 2>&1
    if "$PY" - "$repo3/.autopilot/rounds/r-01.metrics.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
ok = (m.get("slept_minutes") == 20
      and m.get("active_minutes") is not None
      and m.get("elapsed_minutes") is not None
      and m["active_minutes"] + 20 == m["elapsed_minutes"]
      and m["elapsed_minutes"] in (89, 90))
sys.exit(0 if ok else 1)
PY
    then pass 9 "metrics 有 slept=20 与 active=墙钟-20，elapsed 仍是墙钟"
    else fail 9 "metrics 时间账字段不对"; fi
}

rc_expect() {  # 例号 期望 实际 说明
    if [ "$3" -eq "$2" ]; then pass "$1" "$4"; else fail "$1" "$4（退出码 want=$2 got=$3）"; fi
}

json_field() {  # 文件 点分路径
    $PY -c 'import json,sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for part in sys.argv[2].split("."):
    d = d.get(part) if isinstance(d, dict) else None
print("" if d is None else d)' "$1" "$2"
}

case_multibudget() {
    repo=$(new_repo h8)
    mkdir -p "$repo/.autopilot"
    cat > "$repo/.autopilot/state.json" <<'EOF'
{"started_at": "2026-01-01T00:00:00+00:00", "phase": "execute", "rounds_used": 1,
 "no_progress_streak": 0, "last_passed": [],
 "budget": {"max_rounds": 10, "max_minutes": 100000, "max_calls": 100, "max_tool_calls": 2}}
EOF
    {
        printf '%s\n' '{"type": "tool", "name": "Bash"}'
        printf '%s\n' '{"type": "tool", "name": "Read"}'
    } > "$repo/.autopilot/ledger.jsonl"
    out=$($PY "$STATUS" summary "$repo" 2>&1)
    if printf '%s' "$out" | grep -q "工具调用 2/2" && printf '%s' "$out" | grep -q "工具调用预算耗尽"; then
        pass 13 "工具调用数可数并进停止条件"
    else
        fail 13 "工具调用预算没生效：$(printf '%s' "$out" | grep -E "成本账|停止")"
    fi

    repo2=$(new_repo h8b)
    mkdir -p "$repo2/.autopilot"
    cat > "$repo2/.autopilot/state.json" <<'EOF'
{"started_at": "2026-01-01T00:00:00+00:00", "phase": "execute", "rounds_used": 1,
 "no_progress_streak": 0, "last_passed": [],
 "budget": {"max_rounds": 10, "max_minutes": 100000, "max_calls": 100, "max_usd": 1.0}}
EOF
    printf '%s\n' '{"type": "usage", "usd": 0.9, "source": "self-estimate"}' > "$repo2/.autopilot/ledger.jsonl"
    out2=$($PY "$STATUS" summary "$repo2" 2>&1)
    if printf '%s' "$out2" | grep -q "自估 0.90（不参与判定）" && ! printf '%s' "$out2" | grep -q "成本预算耗尽"; then
        pass 13 "脚本自估的成本只展示，不参与判定（H23）"
    else
        fail 13 "自估成本口径不对：$(printf '%s' "$out2" | grep -E "成本账|停止")"
    fi
    printf '%s\n' '{"type": "usage", "usd": 1.2, "source": "host"}' >> "$repo2/.autopilot/ledger.jsonl"
    out3=$($PY "$STATUS" summary "$repo2" 2>&1)
    if printf '%s' "$out3" | grep -q "宿主上报 1.20/1.00 USD" && printf '%s' "$out3" | grep -q "宿主上报成本预算耗尽"; then
        pass 13 "宿主上报成本过线才触发停止"
    else
        fail 13 "宿主上报成本没触发：$(printf '%s' "$out3" | grep -E "成本账|停止")"
    fi

    # 没配这两个上限的工作区：一行新输出都不许多打
    repo3=$(new_repo h8c)
    mkdir -p "$repo3/.autopilot"
    write_state "$repo3/.autopilot/state.json" '"2026-01-01T00:00:00+00:00"'
    out4=$($PY "$STATUS" summary "$repo3" 2>&1)
    if printf '%s' "$out4" | grep -qE "成本账|时间账"; then
        fail 13 "未配置多维预算的工作区被加了新行"
    else
        pass 13 "未配置时 summary 输出与旧版一字不差"
    fi

    # 指标里带上两个口径
    mkdir -p "$repo2/.autopilot/rounds"
    cat > "$repo2/.autopilot/rounds/r-02.json" <<'EOF'
{"round": 2, "verdict": "fail", "passed": [], "failed": ["A1"], "tasks_closed": 0, "notes": "成本指标"}
EOF
    $PY "$STATUS" close-round "$repo2" "$repo2/.autopilot/rounds/r-02.json" >/dev/null 2>&1
    if "$PY" - "$repo2/.autopilot/rounds/r-02.metrics.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if abs(m.get("host_reported_usd", 0) - 1.2) < 1e-9 and m.get("tool_calls_used") == 0 else 1)
PY
    then pass 13 "metrics 只把宿主上报计入 host_reported_usd"
    else fail 13 "metrics 成本口径不对"; fi

    # status.py budget：只准新设或收紧，放宽一律被夹回更严值
    repo4=$(new_repo h8d)
    mkdir -p "$repo4/.autopilot"
    printf '%s\n' '{"phase":"execute","rounds_used":1,"budget":{"max_rounds":10,"max_tool_calls":400}}' \
        > "$repo4/.autopilot/state.json"
    $PY "$STATUS" budget "$repo4" max_tool_calls=200 max_usd=5 >/dev/null 2>&1
    got=$(json_field "$repo4/.autopilot/state.json" "budget.max_tool_calls")
    if [ "$got" = "200" ]; then
        pass 13 "budget 新设/收紧生效（400 → 200）"
    else
        fail 13 "budget 收紧没写入（got=$got）"
    fi
    $PY "$STATUS" budget "$repo4" max_tool_calls=999 >/dev/null 2>&1
    got2=$(json_field "$repo4/.autopilot/state.json" "budget.max_tool_calls")
    if [ "$got2" = "200" ]; then
        pass 13 "请求放宽时被夹回更严值，不自己放水"
    else
        fail 13 "放宽请求把上限改成了 $got2"
    fi
    if grep -q '"applied"' "$repo4/.autopilot/ledger.jsonl" \
       && grep -q '"requested"' "$repo4/.autopilot/ledger.jsonl"; then
        pass 13 "账本同时记下请求值与实际生效值（审计看得见夹回）"
    else
        fail 13 "budget 记账缺 requested/applied"
    fi
    $PY "$STATUS" budget "$repo4" max_usd=0 >/dev/null 2>&1
    rc_expect 13 24 "$?" "取消上限（设 0）退 24，要人自己动手"
    $PY "$STATUS" budget "$repo4" nonsense=1 >/dev/null 2>&1
    rc_expect 13 2 "$?" "未知预算维度退 2"
}

case_naive
case_garbage
case_empty
case_aware
case_close_twice
case_flex_round
case_contract_change
case_audit_not_record
case_metrics
case_rework_parallel
case_corrupt_files
case_close_check
case_clock_accounting
case_multibudget

if [ "$FAILED" -gt 0 ]; then
    printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
    exit 1
fi
printf '== 全部通过（%s 项）==\n' "$PASSED"
exit 0
