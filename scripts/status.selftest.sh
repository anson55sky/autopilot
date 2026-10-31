#!/bin/sh
# status.py 自检：C3 时间戳健壮 / C4 收轮幂等（含 flex 轮次）/ C5 轮次指标
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

# ---------------------------------------------------------------- C5

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

case_naive
case_garbage
case_empty
case_aware
case_close_twice
case_flex_round
case_metrics

if [ "$FAILED" -gt 0 ]; then
    printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
    exit 1
fi
printf '== 全部通过（%s 项）==\n' "$PASSED"
exit 0
