#!/bin/sh
# H7 工具闸门自测：A-tg-01..06。只在 mktemp -d 造工作区，不碰真实仓库、不执行任何外部工具。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TG="$HERE/toolgate.py"
PY=${PYTHON:-python3}

TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPROOT"' EXIT INT TERM

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

new_repo() {
    _n_repo="$TMPROOT/$1"
    mkdir -p "$_n_repo/.autopilot" "$_n_repo/src"
    printf '# GOAL\n\n（本工作区没有 TOOLBOX 区块）\n' > "$_n_repo/.autopilot/GOAL.md"
    printf 'v1\n' > "$_n_repo/src/a.js"
    printf '%s\n' '{"started_at":"2026-01-01T00:00:00+00:00","phase":"execute","rounds_used":0,
 "budget":{"max_rounds":8,"parallel":3,"max_minutes":300,"max_calls":50}}' > "$_n_repo/.autopilot/state.json"
    printf '%s\n' "$_n_repo"
}

toolbox_on() {
    _t_repo="$1"; _t_allow="${2:-fetch.url, write.file}"; _t_max="${3:-0}"
    cat > "$_t_repo/.autopilot/GOAL.md" <<EOF
# GOAL

## TOOLBOX

enable          = true
allow           = $_t_allow
snapshot_files  = true
max_calls_round = $_t_max
EOF
}

rc_is() {  # 例号 期望 实际 说明
    if [ "$3" -eq "$2" ]; then pass "$1" "$4"; else fail "$1" "$4（退出码 want=$2 got=$3）"; fi
}

# ---------------------------------------------------------------- A-tg-01 关闭态

repo=$(new_repo tg01)
for sub in call rollback snapshot list; do
    if [ "$sub" = "call" ]; then
        out=$($PY "$TG" call --repo "$repo" --tool fetch.url 2>&1); rc=$?
    elif [ "$sub" = "rollback" ]; then
        out=$($PY "$TG" rollback --repo "$repo" --to snap-1 2>&1); rc=$?
    elif [ "$sub" = "snapshot" ]; then
        out=$($PY "$TG" snapshot --repo "$repo" --files src/a.js 2>&1); rc=$?
    else
        out=$($PY "$TG" list --repo "$repo" 2>&1); rc=$?
    fi
    rc_is 1 23 "$rc" "关闭态 $sub 退 23"
done
$PY "$TG" config --repo "$repo" >/dev/null 2>&1; rc_is 1 0 "$?" "config 只读始终可用"
got=$($PY "$TG" config --repo "$repo" --enabled 2>&1)
if [ "$got" = "0" ]; then pass 1 "关闭态 config --enabled 输出 0"; else fail 1 "输出 $got"; fi
if [ ! -d "$repo/sandbox/.toolgate" ]; then
    pass 1 "关闭时连目录都不建，不留痕"
else
    fail 1 "关闭态却写了 sandbox/.toolgate"
fi

# ---------------------------------------------------------------- A-tg-02 白名单

repo2=$(new_repo tg02)
toolbox_on "$repo2" "write.file"
out=$($PY "$TG" call --repo "$repo2" --tool fetch.url --args "GET https://example.com" 2>&1); rc=$?
rc_is 2 22 "$rc" "不在 allow 里的工具被拒"
if printf '%s' "$out" | grep -q "allow=write.file"; then
    pass 2 "拒绝理由打印当前白名单，便于排查"
else
    fail 2 "拒绝输出没带白名单：$out"
fi
$PY "$TG" call --repo "$repo2" --tool write.file --files src/a.js >/dev/null 2>&1
rc_is 2 0 "$?" "白名单内放行"

# ---------------------------------------------------------------- A-tg-03 不可逆复用同一份黑名单

repo3=$(new_repo tg03)
toolbox_on "$repo3" "shell.run"
out=$($PY "$TG" call --repo "$repo3" --tool shell.run --args "git push origin main" 2>&1); rc=$?
rc_is 3 24 "$rc" "命中 deny-list 退 24 转待批"
if printf '%s' "$out" | grep -q "转人工待批"; then
    pass 3 "不可逆不执行，只转待批"
else
    fail 3 "不可逆处理不对：$out"
fi

# ---------------------------------------------------------------- A-tg-04 快照与回滚

repo4=$(new_repo tg4)
toolbox_on "$repo4"
out=$($PY "$TG" call --repo "$repo4" --tool write.file --files src/a.js 2>&1); rc=$?
rc_is 4 0 "$rc" "带写集声明的调用先快照"
snap=$(printf '%s' "$out" | sed -n 's/.*快照 \(snap-[0-9]*\).*/\1/p')
if [ -n "$snap" ] && [ -f "$repo4/sandbox/.toolgate/$snap/manifest.json" ]; then
    pass 4 "快照清单落盘"
else
    fail 4 "没生成快照：$out"
fi
# 工具真的动手改文件（快照之后才发生的变化）
printf 'v2 改坏了\n' > "$repo4/src/a.js"
if grep -q '^v1$' "$repo4/sandbox/.toolgate/$snap/src/a.js" 2>/dev/null; then
    pass 4 "快照里存的是调用前的 v1 内容"
else
    fail 4 "快照内容不是改动前的版本"
fi
$PY "$TG" rollback --repo "$repo4" --to "$snap" >/dev/null 2>&1
rc_is 4 0 "$?" "回滚退 0"
if [ "$(cat "$repo4/src/a.js")" = "v1" ]; then
    pass 4 "仓库内文件写真的能退回快照前"
else
    fail 4 "回滚后内容不对：$(cat "$repo4/src/a.js")"
fi

# 快照前文件不存在 → 回滚要把新建的文件删掉（这是回滚语义，不是"删用户文件"）
repo5=$(new_repo tg5)
toolbox_on "$repo5"
$PY "$TG" call --repo "$repo5" --tool write.file --files src/new.js >/dev/null 2>&1
printf '新写出来的\n' > "$repo5/src/new.js"
$PY "$TG" rollback --repo "$repo5" --to snap-1 >/dev/null 2>&1
if [ ! -e "$repo5/src/new.js" ]; then
    pass 5 "快照时不存在的文件，回滚后按原样回到"不存在""
else
    fail 5 "新增文件没被回滚清掉"
fi

# ---------------------------------------------------------------- A-tg-05 外部副作用不承诺回滚

repo6=$(new_repo tg6)
toolbox_on "$repo6" "fetch.url, post.mail"
snap6=$($PY "$TG" call --repo "$repo6" --tool fetch.url --files src/a.js \
        --args "POST https://api.example.com/x" 2>&1 | sed -n 's/.*快照 \(snap-[0-9]*\).*/\1/p')
out=$($PY "$TG" rollback --repo "$repo6" --to "$snap6" 2>&1); rc=$?
rc_is 6 24 "$rc" "副作用类工具的 rollback 被拒（不假装能撤销）"
if printf '%s' "$out" | grep -q "回滚不了已发出的请求"; then
    pass 6 "拒绝理由写明边界在哪"
else
    fail 6 "边界说明缺失：$out"
fi
snap_plain=$($PY "$TG" snapshot --repo "$repo6" --files src/a.js 2>&1 | sed -n 's/SNAPSHOT \(snap-[0-9]*\).*/\1/p')
$PY "$TG" rollback --repo "$repo6" --to "$snap_plain" >/dev/null 2>&1
rc_is 6 0 "$?" "手工快照（无副作用工具归属）仍可正常回滚"

# ---------------------------------------------------------------- A-tg-06 每轮上限与记账

repo7=$(new_repo tg7)
toolbox_on "$repo7" "write.file" 2
$PY "$TG" call --repo "$repo7" --tool write.file --files src/a.js >/dev/null 2>&1
$PY "$TG" call --repo "$repo7" --tool write.file --files src/a.js >/dev/null 2>&1
out=$($PY "$TG" call --repo "$repo7" --tool write.file --files src/a.js 2>&1); rc=$?
rc_is 7 21 "$rc" "max_calls_round 上限生效退 21"
lines=$(grep -c '"tool": "write.file"' "$repo7/sandbox/.toolgate/calls.jsonl")
if [ "$lines" = "3" ]; then
    pass 7 "被拒的调用也留痕（否则上限成了黑箱）"
else
    fail 7 "calls.jsonl 条数 $lines，应为 3"
fi
if grep -q '"type": "tool"' "$repo7/.autopilot/ledger.jsonl"; then
    pass 7 "工具调用进项目账本，H8 的 max_tool_calls 直接可数"
else
    fail 7 "账本里没有 tool 事件"
fi

if [ "$FAILED" -gt 0 ]; then
    printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
    exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
