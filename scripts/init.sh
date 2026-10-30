#!/usr/bin/env bash
# autopilot intake: 建立 .autopilot 工作区、目标契约、起始快照。
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TPL_DIR="$SKILL_DIR/templates"

GOAL=""
REPO="$PWD"
MODE="auto"
MAX_ROUNDS=6
MAX_TASKS=8
PARALLEL=3
BUDGET_MIN=240
MAX_CALLS=120

usage() {
  cat <<'EOF'
用法: init.sh --goal "终极目标" [选项]

  --goal TEXT       终结目标（必填）
  --repo PATH       目标仓库（默认当前目录）
  --mode MODE       build | fix | auto（默认 auto，由控制器判断）
  --max-rounds N    最多轮次（默认 6）
  --max-tasks N     每轮最多任务（默认 8）
  --parallel N      并行工人数（默认 3）
  --budget-min N    总时长上限，分钟（默认 240）
  --max-calls N     子代理调用上限（默认 120）
  -h, --help
EOF
}

die() { printf '错误: %s\n' "$*" >&2; exit 2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --goal)      GOAL="${2:-}"; shift 2 ;;
    --repo)      REPO="${2:-}"; shift 2 ;;
    --mode)      MODE="${2:-}"; shift 2 ;;
    --max-rounds) MAX_ROUNDS="${2:-}"; shift 2 ;;
    --max-tasks) MAX_TASKS="${2:-}"; shift 2 ;;
    --parallel)  PARALLEL="${2:-}"; shift 2 ;;
    --budget-min) BUDGET_MIN="${2:-}"; shift 2 ;;
    --max-calls) MAX_CALLS="${2:-}"; shift 2 ;;
    -h|--help)   usage; exit 0 ;;
    *) die "未知参数: $1" ;;
  esac
done

[[ -n "$GOAL" ]] || die '缺 --goal "终极目标"'
[[ -d "$REPO" ]] || die "目录不存在: $REPO"
case "$MODE" in build|fix|auto) ;; *) die "--mode 只能是 build|fix|auto" ;; esac
for v in "$MAX_ROUNDS" "$MAX_TASKS" "$PARALLEL" "$BUDGET_MIN" "$MAX_CALLS"; do
  [[ "$v" =~ ^[0-9]+$ ]] || die "数字参数非法: $v"
done

REPO="$(cd "$REPO" && pwd)"
AP="$REPO/.autopilot"

if [[ -f "$AP/state.json" ]]; then
  echo "已存在一次运行: $AP/state.json"
  echo "查看:  python3 \"$SKILL_DIR/scripts/status.py\" summary \"$REPO\""
  echo "重开:  mv \"$AP\" \"$AP.bak-$(date +%Y%m%d-%H%M%S)\""
  exit 3
fi

mkdir -p "$AP"/{tasks,runs,rounds,checks,baseline,remote}
: > "$AP/ledger.jsonl"
: > "$AP/inbox.jsonl"
if [[ ! -f "$AP/playbook.md" ]]; then
  printf '# Playbook\n\n只记「下次还会踩 / 下次还能用」的结论，一条一行。add 自动去重并计数。\n' > "$AP/playbook.md"
fi
if [[ ! -f "$AP/BACKLOG.md" ]]; then
  printf '# BACKLOG\n\n范围外发现只记在这里，不进本轮。\n' > "$AP/BACKLOG.md"
fi

if git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$REPO" rev-parse HEAD >"$AP/baseline/HEAD" 2>/dev/null || true
  git -C "$REPO" rev-parse --abbrev-ref HEAD >"$AP/baseline/branch" 2>/dev/null || true
  git -C "$REPO" status --porcelain >"$AP/baseline/git-status.txt" 2>/dev/null || true
  git -C "$REPO" diff >"$AP/baseline/wip.diff" 2>/dev/null || true
fi

if [[ ! -f "$AP/checks/run.sh" ]]; then
  cp "$TPL_DIR/checks/run.sh.example" "$AP/checks/run.sh"
  chmod +x "$AP/checks/run.sh"
fi

AP="$AP" TPL_GOAL="$TPL_DIR/GOAL.md" GOAL_TEXT="$GOAL" REPO_PATH="$REPO" \
RUN_MODE="$MODE" MAX_ROUNDS="$MAX_ROUNDS" MAX_TASKS="$MAX_TASKS" PARALLEL="$PARALLEL" \
BUDGET_MIN="$BUDGET_MIN" MAX_CALLS="$MAX_CALLS" python3 - <<'PY'
import datetime, json, os

ap = os.environ["AP"]
goal = os.environ["GOAL_TEXT"]

repl = {
    "{{GOAL}}": goal,
    "{{REPO}}": os.environ["REPO_PATH"],
    "{{MODE}}": os.environ["RUN_MODE"],
    "{{MAX_ROUNDS}}": os.environ["MAX_ROUNDS"],
    "{{MAX_TASKS}}": os.environ["MAX_TASKS"],
    "{{PARALLEL}}": os.environ["PARALLEL"],
    "{{BUDGET_MIN}}": os.environ["BUDGET_MIN"],
    "{{MAX_CALLS}}": os.environ["MAX_CALLS"],
    "{{DATE}}": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
}

tpl = open(os.environ["TPL_GOAL"], encoding="utf-8").read()
for k, v in repl.items():
    tpl = tpl.replace(k, v)
open(os.path.join(ap, "GOAL.md"), "w", encoding="utf-8").write(tpl)

state = {
    "schema": 2,
    "goal": goal,
    "repo": os.environ["REPO_PATH"],
    "mode": os.environ["RUN_MODE"],
    "started_at": repl["{{DATE}}"],
    "phase": "intake",
    "rounds_used": 0,
    "closed_rounds": [],
    "no_progress_streak": 0,
    "last_passed": [],
    "last_verdict": None,
    "budget": {
        "max_rounds": int(os.environ["MAX_ROUNDS"]),
        "max_tasks_per_round": int(os.environ["MAX_TASKS"]),
        "parallel": int(os.environ["PARALLEL"]),
        "max_minutes": int(os.environ["BUDGET_MIN"]),
        "max_calls": int(os.environ["MAX_CALLS"]),
    },
}
json.dump(state, open(os.path.join(ap, "state.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
open(os.path.join(ap, "ledger.jsonl"), "a", encoding="utf-8").close()
PY

echo "工作区: $AP"
echo "目标:   $AP/GOAL.md"

CAP_COUNT="?"
if python3 "$SKILL_DIR/scripts/discover.py" scan "$REPO" >/dev/null 2>&1; then
  CAP_COUNT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["unique"])' "$AP/capabilities.json" 2>/dev/null || echo "?")"
  echo "能力:   $AP/CAPABILITIES.md（去重后 $CAP_COUNT 个技能）"
else
  echo "能力:   扫描失败（可手动跑 discover.py scan，不影响开工）"
fi
echo
echo "下一步（控制器自己完成，不要问用户）:"
echo "  1. 填 GOAL.md 的验收矩阵 / 非目标 / 边界 / 假设"
echo "  2. 写 checks/run.sh（每条验收一个 RESULT 行）"
echo "  3. bash $SKILL_DIR/scripts/check.sh freeze $REPO"
echo "  4. 写 CHARTER.md / SPEC.md / DESIGN.md / tasks.json / 任务卡"
echo "  5. 进入 do → verify → gap → replan 循环"
echo "  6. 本机没有合适技能时（不安装，只读参考）: python3 $SKILL_DIR/scripts/remote.py search $REPO \"关键词\""
echo
echo "长跑（新会话接着跑）:"
echo "  接续包: python3 $SKILL_DIR/scripts/resume.py $REPO"
echo "  轮提示: bash $SKILL_DIR/scripts/round_prompt.sh $REPO"
echo "  待批件: python3 $SKILL_DIR/scripts/inbox.py list $REPO"
echo "  排队目标: python3 $SKILL_DIR/scripts/queue.py add --repo $REPO --goal \"...\""
