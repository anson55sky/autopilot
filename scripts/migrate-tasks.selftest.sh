#!/bin/sh
# migrate_tasks.py 自测：0.8 tasks.json → 0.9 契约的机械转换。
# 只在 mktemp -d 里造样本，不碰真实工作区。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MIG="$HERE/migrate_tasks.py"
CHECK="$HERE/../schema/check.py"
PY=${PYTHON:-python3}

TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPROOT"' EXIT INT TERM

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

new_repo() {
    d="$TMPROOT/$1"
    mkdir -p "$d/.autopilot/tasks"
    printf '%s\n' "$d"
}

# --- 1. 带任务卡的旧 DAG：角色/写集/验收都要从卡里抽出来 --------------------
repo=$(new_repo c1)
cat > "$repo/.autopilot/tasks.json" <<'EOF'
{"tasks": [
  {"id": "t-1", "title": "写核心", "status": "doing", "deps": [], "attempts": 2},
  {"id": "t-2", "title": "写测试", "status": "pending", "deps": ["t-1"]}
]}
EOF
cat > "$repo/.autopilot/tasks/t-1.md" <<'EOF'
# t-1 — 写核心

- 角色：Builder
- 依赖：—
- 写集：
  - src/core.js
  - src/util.js
- 对应验收：A1, A3
- 完成定义：核心函数行为正确
EOF
if $PY "$MIG" "$repo" >"$TMPROOT/out1" 2>&1; then
    if $PY - "$repo/.autopilot/tasks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
t = {x["id"]: x for x in d["tasks"]}
assert "T-01" in t and "T-02" in t, t.keys()
# 写集两个文件 → strict 一卡一文件 → 拆成两张卡
assert t["T-01"]["write_set"] == ["src/core.js"], t["T-01"]["write_set"]
sib = [x for x in d["tasks"] if x["write_set"] == ["src/util.js"]]
assert len(sib) == 1, sib
assert sib[0]["acceptance"] == [], sib[0]
assert t["T-01"]["role"] == "Builder", t["T-01"]
assert t["T-01"]["acceptance"] == ["A1", "A3"], t["T-01"]["acceptance"]
assert t["T-01"]["attempts"] == 2, t["T-01"]
assert t["T-01"]["status"] == "doing", t["T-01"]
assert t["T-02"]["deps"] == ["T-01"], t["T-02"]
assert t["T-01"]["card"] == ".autopilot/tasks/t-1.md", t["T-01"]["card"]
PY
    then
        pass 1 "从任务卡抽出角色/写集/验收，重映射 id 与依赖，多文件写集拆卡"
    else
        fail 1 "从任务卡抽出角色/写集/验收，重映射 id 与依赖，多文件写集拆卡"
        cat "$TMPROOT/out1"
    fi
else
    fail 1 "迁移命令退出码非 0"
    cat "$TMPROOT/out1"
fi

# --- 2. 迁移后必须过 0.9 契约校验 ------------------------------------------
if $PY "$CHECK" "$repo/.autopilot/tasks.json" >"$TMPROOT/chk2" 2>&1; then
    pass 2 "迁移结果通过 schema/check.py"
else
    fail 2 "迁移结果通过 schema/check.py"
    cat "$TMPROOT/chk2"
fi

# --- 3. 原文件留备份，且备份内容是迁移前的 ---------------------------------
if [ -f "$repo/.autopilot/tasks.json.0.8.bak" ]; then
    if grep -q '"t-1"' "$repo/.autopilot/tasks.json.0.8.bak"; then
        pass 3 "迁移前的内容留在备份里"
    else
        fail 3 "迁移前的内容留在备份里"
    fi
else
    fail 3 "迁移前的内容留在备份里（缺备份文件）"
fi

# --- 4. 幂等：已经是 0.9 契约就别再动 --------------------------------------
before=$(cat "$repo/.autopilot/tasks.json")
out4=$($PY "$MIG" "$repo" 2>&1)
rc4=$?
after=$(cat "$repo/.autopilot/tasks.json")
if [ "$rc4" -eq 0 ] && [ "$before" = "$after" ] && printf '%s' "$out4" | grep -q "无需迁移"; then
    pass 4 "重复迁移是幂等的（不改文件）"
else
    fail 4 "重复迁移是幂等的（不改文件）"
    printf '%s\n' "$out4"
fi

# --- 5. 写集推导不出来 → 明确回落到整仓并在报告里点名 ----------------------
repo5=$(new_repo c5)
cat > "$repo5/.autopilot/tasks.json" <<'EOF'
{"tasks": [{"id": "t-1", "title": "无卡任务", "status": "pending", "deps": []}]}
EOF
if $PY "$MIG" "$repo5" >"$TMPROOT/out5" 2>&1; then
    if $PY - "$repo5/.autopilot/tasks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d["tasks"][0]["write_set"] == ["."], d["tasks"][0]
PY
    then
        if grep -q "整仓" "$TMPROOT/out5"; then
            pass 5 "写集推导不出时回落到整仓并在报告里点名"
        else
            fail 5 "写集推导不出时回落到整仓并在报告里点名"
        fi
    else
        fail 5 "写集推导不出时回落到整仓并在报告里点名"
    fi
else
    fail 5 "写集推导不出时回落到整仓并在报告里点名"
    cat "$TMPROOT/out5"
fi

# --- 6. 卡里的绝对路径必须被丢掉 -------------------------------------------
repo6=$(new_repo c6)
cat > "$repo6/.autopilot/tasks.json" <<'EOF'
{"tasks": [{"id": "t-1", "title": "越界卡", "status": "pending", "deps": []}]}
EOF
cat > "$repo6/.autopilot/tasks/t-1.md" <<'EOF'
# t-1 — 越界卡

- 角色：Builder
- 写集：
  - /etc/passwd
  - ../../outside.txt
  - src/ok.js
EOF
if $PY "$MIG" "$repo6" >"$TMPROOT/out6" 2>&1; then
    if $PY - "$repo6/.autopilot/tasks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
ws = d["tasks"][0]["write_set"]
assert ws == ["src/ok.js"], ws
PY
    then
        pass 6 "任务卡里的绝对路径与 .. 越界路径被丢掉"
    else
        fail 6 "任务卡里的绝对路径与 .. 越界路径被丢掉"
        cat "$TMPROOT/out6"
    fi
else
    fail 6 "任务卡里的绝对路径与 .. 越界路径被丢掉"
    cat "$TMPROOT/out6"
fi

# --- 7. 悬空依赖被丢弃并点名 ------------------------------------------------
repo7=$(new_repo c7)
cat > "$repo7/.autopilot/tasks.json" <<'EOF'
{"tasks": [{"id": "t-1", "title": "挂依赖", "status": "pending", "deps": ["t-9"]}]}
EOF
if $PY "$MIG" "$repo7" >"$TMPROOT/out7" 2>&1; then
    if grep -q "丢弃依赖" "$TMPROOT/out7" && $PY - "$repo7/.autopilot/tasks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d["tasks"][0]["deps"] == [], d["tasks"][0]
PY
    then
        pass 7 "悬空依赖被丢弃并在报告里点名"
    else
        fail 7 "悬空依赖被丢弃并在报告里点名"
        cat "$TMPROOT/out7"
    fi
else
    fail 7 "悬空依赖被丢弃并在报告里点名"
    cat "$TMPROOT/out7"
fi

# --- 8. 不是 autopilot 工作区 → 退出 2 --------------------------------------
out8=$($PY "$MIG" "$TMPROOT/nonexistent" 2>&1)
rc8=$?
if [ "$rc8" -eq 2 ]; then
    pass 8 "不是 autopilot 工作区时退出 2"
else
    fail 8 "不是 autopilot 工作区时退出 2（实际 $rc8）"
fi

# --- 9. 异形 id 顺序补号且不撞车 -------------------------------------------
repo9=$(new_repo c9)
cat > "$repo9/.autopilot/tasks.json" <<'EOF'
{"tasks": [
  {"id": "weird-name", "title": "甲", "status": "pending", "deps": []},
  {"id": "t-1", "title": "乙", "status": "pending", "deps": ["weird-name"]}
]}
EOF
if $PY "$MIG" "$repo9" >"$TMPROOT/out9" 2>&1 && $PY "$CHECK" "$repo9/.autopilot/tasks.json" >/dev/null 2>&1; then
    pass 9 "异形 id 被补号且不与既有 id 撞车"
else
    fail 9 "异形 id 被补号且不与既有 id 撞车"
    cat "$TMPROOT/out9"
fi

if [ "$FAILED" -gt 0 ]; then
    printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
    exit 1
fi
printf '== 全部通过（%s 项）==\n' "$PASSED"
exit 0
