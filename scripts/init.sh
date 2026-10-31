#!/usr/bin/env sh
# autopilot intake v0.9：建立 .autopilot 工作区、目标契约、起始快照。
#
# 路径中立约定（0.9 起强制）：
#   - 生成物（GOAL.md / state.json / 任务卡 / 打印给控制器的提示）里只出现占位符
#     {SKILL_ROOT} 与 {REPO_ROOT}；真实路径由读取方（resume.py / round_prompt.sh）
#     在读取时替换，或查 .autopilot/env.json。
#   - 本机真实路径只允许出现在 .autopilot/env.json（机器本地运行时真值）。
#   - 本脚本不写死任何绝对路径：技能根目录从脚本自身位置推导（支持绝对/相对调用与符号链接）。
#
# 用法: init.sh --goal "终极目标" [选项]
set -eu

GOAL=""
REPO="$PWD"
MODE="auto"
MAX_ROUNDS=6
MAX_TASKS=8
PARALLEL=3
BUDGET_MIN=240
MAX_CALLS=120
SKILL_ROOTS=""
CONFIG=""
HOST_NAME=""
HOST_SOURCE=""
PROBE_ONLY=0

usage() {
  cat <<'EOF'
用法: init.sh --goal "终结目标" [选项]
      init.sh --probe-only [REPO]        换机后重探环境，不动工作区

  --goal TEXT        终结目标（必填；--probe-only 时不需要）
  --repo PATH        目标仓库（默认当前目录）
  --mode MODE        build | fix | auto（默认 auto，由控制器判断）
  --max-rounds N     最多轮次（默认 6）
  --max-tasks N      每轮最多任务（默认 8）
  --parallel N       并行工人数（默认 3）
  --budget-min N     总时长上限，分钟（默认 240）
  --max-calls N      子代理调用上限（默认 120）
  --skill-roots LIST 技能根目录路径列表（POSIX 用 ":" 分隔），写进 .autopilot/env.json
  --config PATH      技能根目录配置文件（JSON），写进 .autopilot/env.json
  --host NAME        宿主适配器名（默认取 AUTOPILOT_HOST，缺失按 generic-cli 降级）
  --probe-only       只重探环境：重写 .autopilot/env.json、host.json、environment.json，
                     不碰 GOAL.md / state.json / 任务卡 / 冻结基线
  -h, --help

环境变量:
  AUTOPILOT_HOME           全局记忆目录（默认 $HOME/.autopilot）
  AUTOPILOT_HOST           宿主适配器名（同 --host）
  AUTOPILOT_SKILL_ROOTS    技能根目录列表（同 --skill-roots）
  AUTOPILOT_HASH_IMPL      哈希实现：auto（自动探测，默认）| shasum | sha256sum | python

说明: 生成物里只写 {SKILL_ROOT} / {REPO_ROOT} 占位符；本机真实路径记在 .autopilot/env.json。
EOF
}

die() { printf '错误: %s\n' "$*" >&2; exit 2; }
note() { printf '%s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --goal)        [ $# -ge 2 ] || die "--goal 缺参数"; GOAL="$2"; shift 2 ;;
    --repo)        [ $# -ge 2 ] || die "--repo 缺参数"; REPO="$2"; shift 2 ;;
    --mode)        [ $# -ge 2 ] || die "--mode 缺参数"; MODE="$2"; shift 2 ;;
    --max-rounds)  [ $# -ge 2 ] || die "--max-rounds 缺参数"; MAX_ROUNDS="$2"; shift 2 ;;
    --max-tasks)   [ $# -ge 2 ] || die "--max-tasks 缺参数"; MAX_TASKS="$2"; shift 2 ;;
    --parallel)    [ $# -ge 2 ] || die "--parallel 缺参数"; PARALLEL="$2"; shift 2 ;;
    --budget-min)  [ $# -ge 2 ] || die "--budget-min 缺参数"; BUDGET_MIN="$2"; shift 2 ;;
    --max-calls)   [ $# -ge 2 ] || die "--max-calls 缺参数"; MAX_CALLS="$2"; shift 2 ;;
    --skill-roots) [ $# -ge 2 ] || die "--skill-roots 缺参数"; SKILL_ROOTS="$2"; shift 2 ;;
    --config)      [ $# -ge 2 ] || die "--config 缺参数"; CONFIG="$2"; shift 2 ;;
    --host)        [ $# -ge 2 ] || die "--host 缺参数"; HOST_NAME="$2"; HOST_SOURCE="cli"; shift 2 ;;
    --probe-only)  PROBE_ONLY=1; shift ;;
    -h|--help)     usage; exit 0 ;;
    *)             if [ "$PROBE_ONLY" = 1 ] && [ "${1#-}" = "$1" ]; then
                     REPO="$1"; shift
                   else
                     die "未知参数: $1"
                   fi ;;
  esac
done

if [ "$PROBE_ONLY" = 0 ]; then
  [ -n "$GOAL" ] || die '缺 --goal "终结目标"'
fi
[ -d "$REPO" ] || die "目录不存在: $REPO"
case "$MODE" in
  build|fix|auto) ;;
  *) die "--mode 只能是 build|fix|auto" ;;
esac
for v in "$MAX_ROUNDS" "$MAX_TASKS" "$PARALLEL" "$BUDGET_MIN" "$MAX_CALLS"; do
  case "$v" in
    ''|*[!0-9]*) die "数字参数非法: $v" ;;
  esac
done

# --- 定位自身与技能根目录 --------------------------------------------------
# 自身路径：绝对调用 / 相对调用 / 经符号链接调用都要能找到真身。
self_path=$0
case "$self_path" in
  */*) ;;
  *) self_path=$(command -v "$self_path" 2>/dev/null || printf '%s' "$self_path") ;;
esac

resolve_dir() {
  p=$1
  while [ -L "$p" ]; do
    command -v readlink >/dev/null 2>&1 || break
    d=$(cd -P "$(dirname "$p")" 2>/dev/null && pwd) || break
    l=$(readlink "$p") || break
    case "$l" in
      /*) p=$l ;;
      *)  p="$d/$l" ;;
    esac
  done
  (cd -P "$(dirname "$p")" && pwd)
}

find_skill_root() {
  d=$1
  n=0
  while [ -n "$d" ] && [ "$d" != "/" ] && [ "$n" -lt 8 ]; do
    if [ -d "$d/templates" ] || [ -d "$d/config" ]; then
      printf '%s\n' "$d"
      return 0
    fi
    d=$(dirname "$d")
    n=$((n + 1))
  done
  return 1
}

SELF_DIR=$(resolve_dir "$self_path")
if [ -n "${AUTOPILOT_SKILL_ROOT:-}" ]; then
  [ -d "$AUTOPILOT_SKILL_ROOT" ] || die "AUTOPILOT_SKILL_ROOT 不存在: $AUTOPILOT_SKILL_ROOT"
  SKILL_ROOT=$(cd -P "$AUTOPILOT_SKILL_ROOT" && pwd)
else
  SKILL_ROOT=$(find_skill_root "$SELF_DIR" || true)
  if [ -z "$SKILL_ROOT" ]; then
    SKILL_ROOT=$(cd -P "$SELF_DIR/.." && pwd)
  fi
fi
TPL_DIR="$SKILL_ROOT/templates"
[ -d "$TPL_DIR" ] || die "找不到模板目录: $TPL_DIR"

REPO=$(cd "$REPO" && pwd)
AP="$REPO/.autopilot"

if [ "$PROBE_ONLY" = 0 ]; then
  if [ -f "$AP/state.json" ]; then
    note "已存在一次运行: $AP/state.json"
    note "查看:  python3 {SKILL_ROOT}/scripts/status.py summary {REPO_ROOT}"
    note "重开:  mv \"{REPO_ROOT}/.autopilot\" \"{REPO_ROOT}/.autopilot.bak-$(date +%Y%m%d-%H%M%S)\""
    exit 3
  fi

  mkdir -p "$AP/tasks" "$AP/runs" "$AP/rounds" "$AP/checks" "$AP/baseline" "$AP/remote"
  # 弹性轨道唯一可写区（flex 卡只能写这里，见 specs/sandbox-layout.md）
  mkdir -p "$REPO/sandbox/.gate" "$REPO/sandbox/proposals" "$REPO/sandbox/drafts" \
           "$REPO/sandbox/hypo" "$REPO/sandbox/prototype"
  # 闸门初值：flexgate.py 读同一份结构。已存在就不写 —— 运行中的计数器不能被 init 抹掉。
  if [ ! -f "$REPO/sandbox/.gate/state.json" ]; then
    cat > "$REPO/sandbox/.gate/state.json" <<'EOF'
{
  "round": 0,
  "epoch": 0,
  "light_used": 0,
  "heavy_used": 0,
  "permits_issued": 0,
  "flex_calls": 0,
  "permits": [],
  "history": []
}
EOF
  fi
  : > "$AP/ledger.jsonl"
  : > "$AP/inbox.jsonl"
  if [ ! -f "$AP/playbook.md" ]; then
    cat > "$AP/playbook.md" <<'EOF'
# Playbook

只记「下次还会踩 / 下次还能用」的结论，一条一行。add 自动去重并计数。
EOF
  fi
  if [ ! -f "$AP/BACKLOG.md" ]; then
    cat > "$AP/BACKLOG.md" <<'EOF'
# BACKLOG

范围外发现只记在这里，不进本轮。
EOF
  fi
  # A#→能力映射：没有这份文件，overlay 只能给「空映射」提示，验收永远退化成 FAIL。
  # 模板只带 _ 开头的注释键，判定层忽略它们，所以脚手架本身不会凭空造出 SKIP。
  if [ ! -f "$AP/acceptance-needs.json" ] && [ -f "$TPL_DIR/acceptance-needs.json" ]; then
    cp "$TPL_DIR/acceptance-needs.json" "$AP/acceptance-needs.json"
  fi

  if git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$REPO" rev-parse HEAD >"$AP/baseline/HEAD" 2>/dev/null || true
    git -C "$REPO" rev-parse --abbrev-ref HEAD >"$AP/baseline/branch" 2>/dev/null || true
    git -C "$REPO" status --porcelain >"$AP/baseline/git-status.txt" 2>/dev/null || true
    git -C "$REPO" diff >"$AP/baseline/wip.diff" 2>/dev/null || true
  fi

  if [ ! -f "$AP/checks/run.sh" ]; then
    if [ -f "$TPL_DIR/checks/run.sh.example" ]; then
      cp "$TPL_DIR/checks/run.sh.example" "$AP/checks/run.sh"
    elif [ -f "$TPL_DIR/checks/run.sh" ]; then
      cp "$TPL_DIR/checks/run.sh" "$AP/checks/run.sh"
    fi
    if [ -f "$AP/checks/run.sh" ]; then
      chmod +x "$AP/checks/run.sh"
    fi
  fi
else
  # --probe-only：只重探环境，工作区必须已存在（否则先跑一次正常初始化）
  [ -d "$AP" ] || die "--probe-only 需要已存在的 .autopilot 工作区: $AP（先跑一次 init.sh --goal ...）"
  # 迁移路径：老工作区没有 sandbox/ 与闸门初值，probe 时补齐（计数器归零）
  mkdir -p "$REPO/sandbox/.gate" "$REPO/sandbox/proposals" "$REPO/sandbox/drafts" \
           "$REPO/sandbox/hypo" "$REPO/sandbox/prototype"
  if [ ! -f "$REPO/sandbox/.gate/state.json" ]; then
    cat > "$REPO/sandbox/.gate/state.json" <<'EOF'
{
  "round": 0,
  "epoch": 0,
  "light_used": 0,
  "heavy_used": 0,
  "permits_issued": 0,
  "flex_calls": 0,
  "permits": [],
  "history": []
}
EOF
  fi
  # 迁移路径：老工作区没有 A#→能力映射时补一份空脚手架（不覆盖已有内容）。
  if [ ! -f "$AP/acceptance-needs.json" ] && [ -f "$TPL_DIR/acceptance-needs.json" ]; then
    cp "$TPL_DIR/acceptance-needs.json" "$AP/acceptance-needs.json"
  fi
fi

# 迁移标记：老工作区（已有 state.json）走 probe-only 时，changelog 第 0 条记「迁移」
MIGRATED=0
if [ "$PROBE_ONLY" = 1 ] && [ -f "$AP/state.json" ]; then MIGRATED=1; fi

# --- 机器本地环境（真实路径只落在这里） ------------------------------------
if [ -n "${AUTOPILOT_HOME:-}" ]; then
  AUTOPILOT_HOME_DIR=$AUTOPILOT_HOME
elif [ -n "${HOME:-}" ]; then
  AUTOPILOT_HOME_DIR="$HOME/.autopilot"
else
  AUTOPILOT_HOME_DIR="$AP"
fi

# 哈希实现必须与实际 freeze 用的那个一致。freeze 走 scripts/environ.py 的 pick_hash_impl()
# （顺序 shasum → sha256sum → python），init.sh 之前自己探一遍且顺序相反，
# 会让 env.json 记的 hash_impl 和真跑起来用的不是同一个实现。这里直接问 environ.py，
# 单一事实来源；问不到（python 缺失/模块坏了）才退回本地同序探测。
# AUTOPILOT_HASH_IMPL 可强制指定：auto（自动探测，默认）| shasum | sha256sum | python。
HASH_IMPL="${AUTOPILOT_HASH_IMPL:-auto}"
case "$HASH_IMPL" in
  auto|"")
    HASH_IMPL=""
    if command -v python3 >/dev/null 2>&1; then
      HASH_IMPL=$(PYTHONPATH="$SKILL_ROOT/scripts" python3 -c 'import environ; print(environ.pick_hash_impl())' 2>/dev/null || printf '')
    fi
    if [ -z "$HASH_IMPL" ]; then
      if command -v shasum >/dev/null 2>&1; then
        HASH_IMPL=shasum
      elif command -v sha256sum >/dev/null 2>&1; then
        HASH_IMPL=sha256sum
      elif command -v python3 >/dev/null 2>&1; then
        HASH_IMPL=python
      else
        HASH_IMPL=none
      fi
    fi
    ;;
  shasum|sha256sum|python) ;;
  *) die "AUTOPILOT_HASH_IMPL 只能是 auto|shasum|sha256sum|python: $HASH_IMPL" ;;
esac

OS_KIND=$(uname -s 2>/dev/null | tr 'A-Z' 'a-z' || printf 'unknown')

# 本机 python 版本（写进 env.json，换机后接手的人能立刻知道该用哪个解释器）
PY_VER=$(python3 -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || printf 'unknown')

# 宿主适配器名：--host > AUTOPILOT_HOST > generic-cli（最保守降级）
if [ -z "$HOST_NAME" ] && [ -n "${AUTOPILOT_HOST:-}" ]; then
  HOST_NAME="$AUTOPILOT_HOST"
  HOST_SOURCE="env"
fi
if [ -z "$HOST_NAME" ]; then
  HOST_NAME="generic-cli"
  HOST_SOURCE="default"
fi
HOST_PROFILES="$SKILL_ROOT/config/host-profiles.json"

AP="$AP" TPL_DIR="$TPL_DIR" GOAL_TEXT="$GOAL" REPO_PATH="$REPO" \
RUN_MODE="$MODE" MAX_ROUNDS="$MAX_ROUNDS" MAX_TASKS="$MAX_TASKS" PARALLEL="$PARALLEL" \
BUDGET_MIN="$BUDGET_MIN" MAX_CALLS="$MAX_CALLS" SKILL_ROOT_PATH="$SKILL_ROOT" \
SKILL_ROOTS_RAW="$SKILL_ROOTS" CONFIG_PATH="$CONFIG" AUTOPILOT_HOME_DIR="$AUTOPILOT_HOME_DIR" \
HASH_IMPL="$HASH_IMPL" OS_KIND="$OS_KIND" HOST_NAME="$HOST_NAME" HOST_SOURCE="$HOST_SOURCE" \
HOST_PROFILES_PATH="$HOST_PROFILES" WRITE_WORKSPACE="$([ "$PROBE_ONLY" = 1 ] && printf 0 || printf 1)" \
MIGRATED="$MIGRATED" PY_VER="$PY_VER" \
python3 - <<'PY'
import datetime, json, os, sys

ap = os.environ["AP"]
goal = os.environ["GOAL_TEXT"]
repo = os.environ["REPO_PATH"]
skill_root = os.environ["SKILL_ROOT_PATH"]
host_name = os.environ["HOST_NAME"]
write_workspace = os.environ.get("WRITE_WORKSPACE", "1") == "1"
migrated = os.environ.get("MIGRATED", "0") == "1"

# 新写的戳一律 UTC（+00:00）：换时区后"距今多久"不能跟着墙钟漂（C3）。
# 历史戳带本地偏移也能读 —— status.py / resume.py 用 fromisoformat + astimezone。
now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

if write_workspace:
    # 生成物里只放占位符：真实路径由读取时替换或查 env.json。
    repl = {
        "{{GOAL}}": goal,
        "{{REPO_ROOT}}": "{REPO_ROOT}",
        "{{REPO}}": "{REPO_ROOT}",
        "{{SKILL_ROOT}}": "{SKILL_ROOT}",
        "{{MODE}}": os.environ["RUN_MODE"],
        "{{MAX_ROUNDS}}": os.environ["MAX_ROUNDS"],
        "{{MAX_TASKS}}": os.environ["MAX_TASKS"],
        "{{PARALLEL}}": os.environ["PARALLEL"],
        "{{BUDGET_MIN}}": os.environ["BUDGET_MIN"],
        "{{MAX_CALLS}}": os.environ["MAX_CALLS"],
        "{{DATE}}": now,
    }

    tpl_path = os.path.join(os.environ["TPL_DIR"], "GOAL.md")
    try:
        with open(tpl_path, encoding="utf-8") as f:
            tpl = f.read()
    except OSError:
        print("错误: 读不到模板: " + tpl_path, file=sys.stderr)
        sys.exit(2)
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    with open(os.path.join(ap, "GOAL.md"), "w", encoding="utf-8") as f:
        f.write(tpl)

    state = {
        "schema": 2,
        "goal": goal,
        "repo": "{REPO_ROOT}",
        "repo_root": "{REPO_ROOT}",
        "skill_root": "{SKILL_ROOT}",
        "mode": os.environ["RUN_MODE"],
        "started_at": now,
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
    with open(os.path.join(ap, "state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def home_dir():
    return os.environ.get("HOME") or os.environ.get("USERPROFILE") or ""


def expand_tilde(path):
    """只把 ~ 展开成通用主目录，不拼接任何应用子目录。"""
    if not path:
        return path
    if path == "~":
        return home_dir() or path
    if path.startswith("~/") or path.startswith("~\\"):  # M6-allow 前缀判定，非路径常量
        base = home_dir()
        return os.path.join(base, path[2:]) if base else path
    return path


def split_path_list(raw):
    """路径列表分隔符：POSIX 用 ":"，Windows 用 ";"。"""
    if not raw:
        return []
    parts = raw.split(os.pathsep)
    if os.pathsep != ";":
        extra = []
        for p in parts:
            extra.extend(p.split(";"))
        parts = extra
    out = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(p)
    return out


cfg = {}
cfg_path = os.environ.get("CONFIG_PATH", "").strip()
if cfg_path:
    try:
        with open(cfg_path, encoding="utf-8") as f:
            doc = json.load(f)
        cfg = doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        print("警告: 配置文件不是合法 JSON，已忽略: " + cfg_path, file=sys.stderr)
        cfg = {}

raw_cli = os.environ.get("SKILL_ROOTS_RAW", "").strip()
raw_env = os.environ.get("AUTOPILOT_SKILL_ROOTS", "").strip()
if raw_cli:
    roots, source = split_path_list(raw_cli), "cli"
elif raw_env:
    roots, source = split_path_list(raw_env), "env"
elif isinstance(cfg.get("roots"), list) and cfg.get("roots"):
    roots, source = [str(r) for r in cfg["roots"]], "config"
else:
    roots, source = [], "none"

tool_subdirs = {}
if isinstance(cfg.get("tool_subdirs"), dict):
    for k, v in cfg["tool_subdirs"].items():
        if isinstance(v, str) and v.strip():
            tool_subdirs[str(k)] = v.strip()

env_doc = {
    "schema": 1,
    "skill_version": "0.9",
    "created_at": now,
    "skill_root": skill_root,
    "repo_root": repo,
    "autopilot_home": os.environ["AUTOPILOT_HOME_DIR"],
    "hash_impl": os.environ["HASH_IMPL"],
    "python": os.environ.get("PY_VER", "unknown"),
    "shell": "posix-sh",
    "os_kind": os.environ["OS_KIND"],
    "skill_roots": [expand_tilde(r) for r in roots],
    "skill_roots_source": source,
    "tool_subdirs": tool_subdirs,
    "placeholders": {"skill_root": "{SKILL_ROOT}", "repo_root": "{REPO_ROOT}"},
}
with open(os.path.join(ap, "env.json"), "w", encoding="utf-8") as f:
    json.dump(env_doc, f, ensure_ascii=False, indent=2)

# host.json：宿主与 5 原语能力矩阵（specs/host-adapter.md §4）。
# 原语矩阵查 config/host-profiles.json（适配器名是数据不是代码）；
# 查不到就按最保守降级（无原语）并标 assumed=true。
ALL_PRIMITIVES = ["spawn_session", "await_turn", "ask_human",
                   "intercept_permission", "kill_session"]
profiles = {}
profiles_path = os.environ.get("HOST_PROFILES_PATH", "")
if profiles_path and os.path.isfile(profiles_path):
    try:
        with open(profiles_path, encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict) and isinstance(doc.get("profiles"), dict):
            profiles = doc["profiles"]
    except (OSError, ValueError):
        profiles = {}
profile = profiles.get(host_name)
if isinstance(profile, list):
    available = {str(p) for p in profile}
    assumed = False
else:
    available = set()
    assumed = True
primitives = {p: (p in available) for p in ALL_PRIMITIVES}
degraded = []
if not primitives["intercept_permission"]:
    degraded.append("intercept_permission: absent")
if not primitives["spawn_session"]:
    degraded.append("spawn_session: absent（降级为同会话顺序轮）")
if not primitives["kill_session"]:
    degraded.append("kill_session: absent（无法硬停跑飞的执行器）")
host_doc = {
    "schema": 1,
    "host": host_name,
    "host_source": os.environ["HOST_SOURCE"],
    "version": "unknown",
    "assumed": assumed,
    "primitives": primitives,
    "parallel_workers": primitives["spawn_session"],
    "degraded_rules": degraded,
    "updated_at": now,
}
with open(os.path.join(ap, "host.json"), "w", encoding="utf-8") as f:
    json.dump(host_doc, f, ensure_ascii=False, indent=2)

# contract-changelog.md：契约变更与 epoch 递增史（proposal_merge.py 往同一张表里追加行）。
# 表头格式必须与 proposal_merge.py 的 append_changelog 一致，否则两处写出来的表拼不起来。
changelog_path = os.path.join(ap, "contract-changelog.md")
if not os.path.exists(changelog_path):
    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write("# Contract changelog\n\n")
        f.write("| from | to | type | proposal | affected | approved_by | approved_at | ts |\n")
        f.write("| --- | --- | --- | --- | --- | --- | --- | --- |\n")
        if migrated:
            f.write("| 0 | 0 | migrate-0.8 | - | - | - | - | %s |\n" % now)
        else:
            f.write("| 0 | 0 | init | - | - | - | - | %s |\n" % now)
PY

# --- 能力索引（0.8 行为保留：失败不阻塞开工） -----------------------------
DISCOVER=""
for cand in "$SELF_DIR/discover.py" "$SKILL_ROOT/scripts/discover.py"; do
  if [ -f "$cand" ]; then
    DISCOVER="$cand"
    break
  fi
done

if [ -n "$DISCOVER" ]; then
  if python3 "$DISCOVER" scan "$REPO" >/dev/null 2>&1; then
    CAP_COUNT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["unique"])' "$AP/capabilities.json" 2>/dev/null || printf '?')
    note "能力:   $AP/CAPABILITIES.md（去重后 $CAP_COUNT 个技能）"
  else
    note "能力:   扫描失败（可手动跑 discover.py scan，不影响开工）"
  fi
else
  note "能力:   未找到 discover.py（可手动跑 discover.py scan，不影响开工）"
fi

# --- 环境能力探测（写 .autopilot/environment.json；失败不阻塞开工） ---------
ENVIRON=""
for cand in "$SELF_DIR/environ.py" "$SKILL_ROOT/scripts/environ.py"; do
  if [ -f "$cand" ]; then
    ENVIRON="$cand"
    break
  fi
done
if [ -n "$ENVIRON" ] && python3 "$ENVIRON" probe --repo "$REPO" >/dev/null 2>&1; then
  note "环境:   $AP/environment.json（能力探测；缺能力的验收项走 SKIP，不算绿）"
else
  note "环境:   探测失败（可手动跑 environ.py probe --repo {REPO_ROOT}，不影响开工）"
fi

# --- 占位化兜底：生成物里不许出现本机绝对路径 -----------------------------
AP="$AP" SKILL_ROOT_PATH="$SKILL_ROOT" REPO_PATH="$REPO" python3 - <<'PY'
import os

ap = os.environ["AP"]
subs = []
for var, token in (("SKILL_ROOT_PATH", "{SKILL_ROOT}"), ("REPO_PATH", "{REPO_ROOT}")):
    old = os.environ.get(var, "")
    if old:
        subs.append((old, token))

changed = 0
for root, dirs, files in os.walk(ap):
    for fn in files:
        p = os.path.join(root, fn)
        if fn == "env.json":
            continue  # env.json 是机器本地真值，允许写真实路径
        try:
            with open(p, encoding="utf-8") as f:
                txt = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        new = txt
        for old, token in subs:
            if old:
                new = new.replace(old, token)
        if new != txt:
            with open(p, "w", encoding="utf-8") as f:
                f.write(new)
            changed += 1
print("占位化文件: %d" % changed)
PY

if [ "$PROBE_ONLY" = 1 ]; then
  note "已重探环境（未改动 GOAL.md / state.json / 任务卡 / 冻结基线）"
  note "环境:   {REPO_ROOT}/.autopilot/env.json（skill_root / repo_root / skill_roots / hash_impl）"
  note "宿主:   {REPO_ROOT}/.autopilot/host.json（5 原语能力矩阵；缺能力即降级，须在 REPORT 声明）"
  note "探测:   {REPO_ROOT}/.autopilot/environment.json（本机能力；缺能力项验收走 SKIP）"
  exit 0
fi

note "工作区: {REPO_ROOT}/.autopilot（本机真实路径见 .autopilot/env.json）"
note "目标:   {REPO_ROOT}/.autopilot/GOAL.md"
note "环境:   {REPO_ROOT}/.autopilot/env.json（skill_root / repo_root / skill_roots 本机真值）"
note "宿主:   {REPO_ROOT}/.autopilot/host.json（5 原语能力矩阵；缺能力即降级，须在 REPORT 声明）"
note "探测:   {REPO_ROOT}/.autopilot/environment.json（本机能力；缺能力项验收走 SKIP）"
note "沙箱:   {REPO_ROOT}/sandbox/（弹性轨道唯一可写区）"
note ""
note "下一步（控制器自己完成，不要问用户）:"
note "  1. 填 GOAL.md 的验收矩阵 / 非目标 / 边界 / 假设"
note "  2. 写 checks/run.sh（每条验收一个 RESULT 行）"
note "  3. bash {SKILL_ROOT}/scripts/check.sh freeze {REPO_ROOT}"
note "  4. 写 CHARTER.md / SPEC.md / DESIGN.md / tasks.json / 任务卡"
note "  5. 进入 do → verify → gap → replan 循环"
note "  6. 本机没有合适技能时（不安装，只读参考）: python3 {SKILL_ROOT}/scripts/remote.py search {REPO_ROOT} \"关键词\""
note ""
note "长跑（新会话接着跑）:"
note "  接续包: python3 {SKILL_ROOT}/scripts/resume.py {REPO_ROOT}"
note "  轮提示: bash {SKILL_ROOT}/scripts/round_prompt.sh {REPO_ROOT}"
note "  待批件: python3 {SKILL_ROOT}/scripts/inbox.py list {REPO_ROOT}"
note "  排队目标: python3 {SKILL_ROOT}/scripts/queue.py add --repo {REPO_ROOT} --goal \"...\""
