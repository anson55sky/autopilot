#!/bin/sh
# 生成一份**确定性的 0.8 样本工作区**，供 M1（0.8↔0.9 字节等价回归）与迁移彩排使用。
#
# 为什么要有它：这两件事都需要"一份装好的 0.8 工作区"当输入。以前是手工现搓的，
# 结果每次搓出来的样本都不一样，回归结论就不可复现。这里把样本的构造过程写成脚本：
# 输入 = 线上 0.8 技能目录，输出 = 一个冻结好的、验收全绿、没有抖动探针的 0.8 工作区。
#
# 用法: sh tools/make_v08_sample.sh <out-dir>
#   out-dir 要么不存在，要么是空目录。
# 环境变量:
#   AUTOPILOT_LIVE_SKILL     线上技能目录（切换前它就是 0.8）
#   AUTOPILOT_BASELINE_SKILL 0.8 基线目录（切换后用这个，见 tools/baseline08.sh）
#
# 退出码: 0 成功 / 2 用法错 / 3 0.8 技能缺失 / 4 冻结失败
set -u

ROOT=$(cd -P "$(dirname "$0")/.." && pwd)
OUT=${1:-}

[ -n "$OUT" ] || { echo "用法: make_v08_sample.sh <out-dir>" >&2; exit 2; }
# 0.8 基线从哪来：切换前是线上目录，切换后是保留下来的快照 —— 见 tools/baseline08.sh
. "$ROOT/tools/baseline08.sh"
resolve_baseline_skill || exit 3
LIVE_SKILL="$BASELINE_SKILL"
if [ ! -f "$LIVE_SKILL/scripts/init.sh" ]; then
    echo "0.8 技能目录缺 scripts/init.sh: $LIVE_SKILL" >&2
    exit 3
fi
if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then
    echo "输出目录必须不存在或是空目录: $OUT" >&2
    exit 2
fi

mkdir -p "$OUT" || exit 2
OUT=$(cd -P "$OUT" && pwd)

# ---- 1. 用 0.8 的 init.sh 建工作区（GOAL.md / state.json / 骨架） -------------
if ! bash "$LIVE_SKILL/scripts/init.sh" --goal "0.8 样本工作区（回归与迁移彩排用）" \
        --repo "$OUT" >"$OUT/.init.log" 2>&1; then
    echo "0.8 init.sh 失败:" >&2
    tail -n 20 "$OUT/.init.log" >&2
    exit 3
fi
rm -f "$OUT/.init.log"

AP="$OUT/.autopilot"

# ---- 2. 确定性验收脚本（三条，全绿，无浏览器/网络/时间探针） ----------------
# 必须在 sh 与 bash 下行为一致：0.8 的 check.sh 用 bash 跑，0.9 的等价回归用 sh 跑。
# 所以不写 local、不写 pipefail。
cat > "$AP/checks/run.sh" <<'EOF'
#!/usr/bin/env bash
# 0.8 样本验收脚本（确定性，无外部依赖）。
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1

fail=0
check() {
    id="$1"; desc="$2"; shift 2
    if out="$("$@" 2>&1)"; then
        printf 'RESULT %s PASS %s\n' "$id" "$desc"
    else
        fail=1
        printf 'RESULT %s FAIL %s :: %s\n' "$id" "$desc" \
            "$(printf '%s' "$out" | tail -n 3 | tr '\n' ' ')"
    fi
}

check A1 "样本工作区文件齐全" test -f .autopilot/tasks.json
check A2 "tasks.json 是合法 JSON" python3 -c "import json; json.load(open('.autopilot/tasks.json'))"
check A3 "样本标记文件存在" test -f .autopilot/SAMPLE.txt

exit "$fail"
EOF
chmod +x "$AP/checks/run.sh"
printf '0.8 样本工作区\n' > "$AP/SAMPLE.txt"

# ---- 3. tasks.json（0.8 的位置与结构） ---------------------------------------
cat > "$AP/tasks.json" <<'EOF'
{
  "tasks": [
    {"id": "t-1", "title": "样本任务", "status": "done", "deps": [], "attempts": 1},
    {"id": "t-2", "title": "样本任务（依赖 t-1）", "status": "pending", "deps": ["t-1"]}
  ]
}
EOF

# ---- 4. GOAL.md 的验收矩阵换成 A1–A3（0.8 的矩阵表头不变） -------------------
python3 - "$AP/GOAL.md" <<'PY'
import re, sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
rows = [
    "| A1 | 样本工作区文件齐全 | test -f .autopilot/tasks.json | exit=0 | PASS |",
    "| A2 | tasks.json 是合法 JSON | python3 json.load | exit=0 | PASS |",
    "| A3 | 样本标记文件存在 | test -f .autopilot/SAMPLE.txt | exit=0 | PASS |",
]
block = "| ID | 验收项 | 检查方式 | 阈值 | 结果 |\n| --- | --- | --- | --- | --- |\n"
text = re.sub(r"\| ID \| 验收项 \| 检查方式 \| 阈值 \| 结果 \|\n\| --- \| --- \| --- \| --- \| --- \|\n(?:\|.*\n)*",
               block + "\n".join(rows) + "\n", text, count=1)
open(path, "w", encoding="utf-8").write(text)
PY

# ---- 5. 用 0.8 的 check.sh 冻结 ----------------------------------------------
if ! bash "$LIVE_SKILL/scripts/check.sh" freeze "$OUT" >"$OUT/.freeze.log" 2>&1; then
    echo "0.8 check.sh freeze 失败:" >&2
    tail -n 20 "$OUT/.freeze.log" >&2
    rm -f "$OUT/.freeze.log"
    exit 4
fi
rm -f "$OUT/.freeze.log"

if [ ! -f "$AP/checks/MANIFEST.sha256" ]; then
    echo "冻结后没有 MANIFEST.sha256" >&2
    exit 4
fi

printf '0.8 样本工作区: %s\n' "$OUT"
printf '冻结文件数: %s\n' "$(wc -l < "$AP/checks/MANIFEST.sha256" | tr -d ' ')"
exit 0
