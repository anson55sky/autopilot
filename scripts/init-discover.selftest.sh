#!/usr/bin/env sh
# autopilot v0.9 init.sh / discover.py 自测：路径中立（D3）+ 技能根目录配置化（D4）。
#
# 用法: sh scripts/init-discover.selftest.sh
# 只在临时目录里造样本，不碰真实技能目录，不碰仓库 git 状态。
set -u

SELF_DIR=$(cd -P "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd -P "$SELF_DIR/.." && pwd)
INIT_SH="$SELF_DIR/init.sh"
DISCOVER_PY="$SELF_DIR/discover.py"
EXAMPLE_JSON="$REPO_ROOT/config/skill-roots.example.json"

TMP=$(mktemp -d 2>/dev/null || mktemp -d -t autopilot)
FAILED=0

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT INT TERM

pass() { printf 'PASS %s %s\n' "$1" "$2"; }
fail() { printf 'FAIL %s %s\n' "$1" "$2"; FAILED=$((FAILED + 1)); }

# 已知应用名（只在本自测里出现，用来检查源码里没有硬编码的应用目录）
APP_RE='qoder|claude|codex|workbuddy|codebuddy|qclaw|cursor|windsurf|copilot'

env_json_ok() {
  python3 - "$1" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as exc:
    print("读不出 JSON: %s" % exc)
    sys.exit(1)
if not isinstance(d, dict):
    print("不是 JSON 对象")
    sys.exit(1)
need = ["skill_root", "repo_root", "skill_roots", "autopilot_home",
        "hash_impl", "os_kind"]
missing = [k for k in need if k not in d]
if missing:
    print("缺键: " + ", ".join(missing))
    sys.exit(1)
if not isinstance(d.get("skill_roots"), list):
    print("skill_roots 不是列表")
    sys.exit(1)
sys.exit(0)
PY
}

for f in "$INIT_SH" "$DISCOVER_PY" "$EXAMPLE_JSON"; do
  if [ ! -f "$f" ]; then
    printf 'FAIL 0 缺少文件: %s\n' "$f"
    FAILED=$((FAILED + 1))
  fi
done
if [ "$FAILED" -ne 0 ]; then
  printf '缺少被测文件，终止\n'
  exit 1
fi

# --- 1. init.sh 在全新临时仓库上成功并写出 env.json ------------------------
REPO1="$TMP/repo1"
mkdir -p "$REPO1"
if (cd "$REPO1" && sh "$INIT_SH" --goal "自测目标" --repo "$REPO1") >"$TMP/out1" 2>&1; then
  if env_json_ok "$REPO1/.autopilot/env.json" >"$TMP/chk1" 2>&1; then
    pass 1 "init.sh 生成 .autopilot/env.json（含 skill_root/repo_root/skill_roots 等键）"
  else
    fail 1 "init.sh 生成 .autopilot/env.json（含 skill_root/repo_root/skill_roots 等键）"
    cat "$TMP/chk1"
  fi
else
  fail 1 "init.sh 在空仓库上退出码为 0"
  cat "$TMP/out1"
fi

# --- 2. init.sh 写进项目的文件里没有本机绝对路径 ----------------------------
REPO2="$TMP/repo2"
mkdir -p "$REPO2"
(cd "$REPO2" && sh "$INIT_SH" --goal "路径中立" --repo "$REPO2") >"$TMP/out2" 2>&1
BAD2=$(find "$REPO2" -type f ! -name env.json \
        -exec grep -l -F -e "/Users/" -e "$TMP" -e "$REPO_ROOT" {} + 2>/dev/null)
if [ -z "$BAD2" ]; then
  pass 2 "生成物（除 .autopilot/env.json）里没有绝对路径"
else
  fail 2 "生成物（除 .autopilot/env.json）里没有绝对路径"
  printf '%s\n' "$BAD2"
fi

# --- 3. 从别的 cwd 用绝对路径调用，技能根目录仍然解析正确 ------------------
REPO3="$TMP/repo3"
mkdir -p "$REPO3"
if (cd / && sh "$INIT_SH" --goal "绝对路径调用" --repo "$REPO3") >"$TMP/out3" 2>&1; then
  GOT3=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("skill_root",""))' \
         "$REPO3/.autopilot/env.json" 2>/dev/null)
  if [ "$GOT3" = "$REPO_ROOT" ]; then
    pass 3 "换个 cwd 用绝对路径调用，skill_root 仍解析正确"
  else
    fail 3 "换个 cwd 用绝对路径调用，skill_root 仍解析正确"
    printf '期望 %s，实际 %s\n' "$REPO_ROOT" "${GOT3:-<空>}"
  fi
else
  fail 3 "换个 cwd 用绝对路径调用，skill_root 仍解析正确"
  cat "$TMP/out3"
fi

# --- 4. AUTOPILOT_SKILL_ROOTS 指向含假技能目录的临时目录 -------------------
FAKE="$TMP/fake-tool/skills/demo-skill"
mkdir -p "$FAKE"
cat > "$FAKE/SKILL.md" <<'EOF'
---
name: demo-skill
description: 自测用的假技能
---

# demo-skill
EOF
REPO4="$TMP/repo4"
mkdir -p "$REPO4"
(cd "$TMP" && AUTOPILOT_SKILL_ROOTS="$TMP" python3 "$DISCOVER_PY" scan "$REPO4") >"$TMP/out4" 2>&1
RC4=$?
if [ "$RC4" -eq 0 ] && grep -q "demo-skill" "$TMP/out4"; then
  pass 4 "AUTOPILOT_SKILL_ROOTS 指向的假技能被扫到"
else
  fail 4 "AUTOPILOT_SKILL_ROOTS 指向的假技能被扫到"
  cat "$TMP/out4"
fi

# --- 5. 完全没有配置：不能崩，且不出现任何应用默认目录 ----------------------
REPO5="$TMP/repo5"
mkdir -p "$REPO5"
(cd "$TMP" && unset AUTOPILOT_SKILL_ROOTS; python3 "$DISCOVER_PY" scan "$REPO5") >"$TMP/out5" 2>&1
RC5=$?
if [ "$RC5" -eq 0 ]; then
  if grep -qi -E "$APP_RE" "$TMP/out5"; then
    fail 5 "零配置时 discover.py 退出 0 且不吐应用默认路径"
    grep -i -E "$APP_RE" "$TMP/out5" | head -5
  else
    pass 5 "零配置时 discover.py 退出 0 且不吐应用默认路径"
  fi
else
  fail 5 "零配置时 discover.py 退出 0 且不吐应用默认路径"
  cat "$TMP/out5"
fi

# --- 6. 示例配置是合法 JSON，且没有作者本机路径 ----------------------------
if python3 -c 'import json,sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
roots = d.get("roots")
if not isinstance(roots, list) or not roots:
    sys.exit("roots 缺失或为空")
if any("/Users/" in str(r) for r in roots):
    sys.exit("roots 里含本机路径")
if not isinstance(d.get("tool_subdirs"), dict) or not d.get("tool_subdirs"):
    sys.exit("tool_subdirs 缺失或为空")
if "_comment" not in d:
    sys.exit("_comment 缺失")
' "$EXAMPLE_JSON" >"$TMP/chk6" 2>&1; then
  pass 6 "config/skill-roots.example.json 是合法 JSON 且无本机路径"
else
  fail 6 "config/skill-roots.example.json 是合法 JSON 且无本机路径"
  cat "$TMP/chk6"
fi

# --- 7. 三个源文件里没有 /Users/、expanduser、应用目录名 --------------------
BAD7=""
for f in "$INIT_SH" "$DISCOVER_PY" "$EXAMPLE_JSON"; do
  if grep -q -E '/Users/|expanduser' "$f" 2>/dev/null; then
    BAD7="$BAD7 $f(绝对路径/expanduser)"
  fi
  if grep -qi -E "$APP_RE" "$f" 2>/dev/null; then
    BAD7="$BAD7 $f(应用名)"
  fi
done
if [ -z "$BAD7" ]; then
  pass 7 "源码里没有 /Users/、expanduser 或应用目录名"
else
  fail 7 "源码里没有 /Users/、expanduser 或应用目录名"
  printf '%s\n' "$BAD7"
fi

# --- 8. host.json：5 原语矩阵 + 降级声明（P7） ------------------------------
REPO8="$TMP/repo8"
mkdir -p "$REPO8"
(cd "$REPO8" && sh "$INIT_SH" --goal "宿主矩阵" --repo "$REPO8") >"$TMP/out8" 2>&1
if python3 - "$REPO8/.autopilot/host.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for k in ("host", "primitives", "parallel_workers", "degraded_rules"):
    if k not in d:
        print("缺键: " + k); sys.exit(1)
prims = d["primitives"]
for p in ("spawn_session", "await_turn", "ask_human",
          "intercept_permission", "kill_session"):
    if p not in prims:
        print("原语缺失: " + p); sys.exit(1)
if d["host"] != "generic-cli":
    print("未指定宿主时应降级为 generic-cli，实际: " + str(d["host"])); sys.exit(1)
if not d["degraded_rules"]:
    print("降级形态必须写 degraded_rules"); sys.exit(1)
if "intercept_permission: absent" not in d["degraded_rules"]:
    print("degraded_rules 缺 intercept_permission 声明"); sys.exit(1)
sys.exit(0)
PY
then
  pass 8 "init.sh 写 host.json（5 原语矩阵 + generic-cli 降级声明）"
else
  fail 8 "init.sh 写 host.json（5 原语矩阵 + generic-cli 降级声明）"
  cat "$TMP/out8"
fi

# --- 9. --host 指定已知后端时原语矩阵随之展开 ------------------------------
REPO9="$TMP/repo9"
mkdir -p "$REPO9"
(cd "$REPO9" && sh "$INIT_SH" --goal "指定宿主" --repo "$REPO9" --host qoder) >"$TMP/out9" 2>&1
GOT9=$(python3 -c 'import json,sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print(d.get("host"), bool(d.get("primitives", {}).get("spawn_session")), d.get("assumed"))' \
  "$REPO9/.autopilot/host.json" 2>/dev/null)
if [ "$GOT9" = "qoder True False" ]; then
  pass 9 "--host 指定后端时 host.json 的原语矩阵随之展开"
else
  fail 9 "--host 指定后端时 host.json 的原语矩阵随之展开"
  printf '期望 "qoder True False"，实际 "%s"\n' "${GOT9:-<空>}"
fi

# --- 10. sandbox/ 与 environment.json 都在 intake 阶段产出 ----------------
REPO10="$TMP/repo10"
mkdir -p "$REPO10"
(cd "$REPO10" && sh "$INIT_SH" --goal "沙箱与探测" --repo "$REPO10") >"$TMP/out10" 2>&1
MISS10=""
for p in sandbox/.gate sandbox/proposals sandbox/drafts sandbox/hypo sandbox/prototype; do
  [ -d "$REPO10/$p" ] || MISS10="$MISS10 $p"
done
if [ -n "$MISS10" ]; then
  fail 10 "init.sh 建出 sandbox/ 各子目录与 environment.json"
  printf '缺目录:%s\n' "$MISS10"
elif [ ! -f "$REPO10/.autopilot/environment.json" ]; then
  fail 10 "init.sh 建出 sandbox/ 各子目录与 environment.json"
  printf '缺 .autopilot/environment.json\n'
else
  pass 10 "init.sh 建出 sandbox/ 各子目录与 environment.json"
fi

# --- 11. env.json 补齐 python/shell 键，且新写的戳是 UTC --------------------
REPO11="$TMP/repo11"
mkdir -p "$REPO11"
(cd "$REPO11" && sh "$INIT_SH" --goal "环境键与时区" --repo "$REPO11") >"$TMP/out11" 2>&1
if python3 - "$REPO11/.autopilot/env.json" <<'PY'
import datetime, json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for k in ("python", "shell"):
    if not d.get(k):
        print("缺键或为空: " + k); sys.exit(1)
ts = d.get("created_at", "")
dt = datetime.datetime.fromisoformat(ts)
if dt.utcoffset().total_seconds() != 0:
    print("created_at 不是 UTC: " + ts); sys.exit(1)
sys.exit(0)
PY
then
  pass 11 "env.json 含 python/shell 键，且 created_at 是 UTC（+00:00）"
else
  fail 11 "env.json 含 python/shell 键，且 created_at 是 UTC（+00:00）"
  cat "$TMP/out11"
fi

# --- 12. 弹性闸门初值：计数器全 0、令牌簿空 ---------------------------------
REPO12="$TMP/repo12"
mkdir -p "$REPO12"
(cd "$REPO12" && sh "$INIT_SH" --goal "闸门初值" --repo "$REPO12") >"$TMP/out12" 2>&1
if python3 - "$REPO12/sandbox/.gate/state.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for k in ("light_used", "heavy_used", "permits_issued", "flex_calls"):
    if d.get(k) != 0:
        print("计数器非零: %s=%r" % (k, d.get(k))); sys.exit(1)
for k in ("permits", "history"):
    if d.get(k) != []:
        print("簿子非空: %s" % k); sys.exit(1)
sys.exit(0)
PY
then
  pass 12 "sandbox/.gate/state.json 初值：计数器全 0、令牌簿空"
else
  fail 12 "sandbox/.gate/state.json 初值：计数器全 0、令牌簿空"
  cat "$TMP/out12"
fi

# --- 13. contract-changelog.md：表头 + epoch 0 一行 --------------------------
REPO13="$TMP/repo13"
mkdir -p "$REPO13"
(cd "$REPO13" && sh "$INIT_SH" --goal "契约变更史" --repo "$REPO13") >"$TMP/out13" 2>&1
CL13="$REPO13/.autopilot/contract-changelog.md"
if [ ! -f "$CL13" ]; then
  fail 13 "init.sh 生成 contract-changelog.md（表头 + epoch 0）"
elif ! grep -q '^# Contract changelog' "$CL13"; then
  fail 13 "init.sh 生成 contract-changelog.md（表头 + epoch 0）"
  head -3 "$CL13"
elif ! grep -qE '^\| 0 \| 0 \| init \|' "$CL13"; then
  fail 13 "init.sh 生成 contract-changelog.md（表头 + epoch 0）"
  head -5 "$CL13"
else
  pass 13 "init.sh 生成 contract-changelog.md（表头 + epoch 0 行）"
fi

# --- 14. --probe-only：只重探环境，不动 GOAL.md / state.json ----------------
REPO14="$TMP/repo14"
mkdir -p "$REPO14"
(cd "$REPO14" && sh "$INIT_SH" --goal "换机重探" --repo "$REPO14") >"$TMP/out14" 2>&1
G14=$(md5 -q "$REPO14/.autopilot/GOAL.md" 2>/dev/null || printf 'none')
S14=$(md5 -q "$REPO14/.autopilot/state.json" 2>/dev/null || printf 'none')
if AUTOPILOT_HASH_IMPL=auto sh "$INIT_SH" --probe-only "$REPO14" >"$TMP/out14b" 2>&1; then
  G14b=$(md5 -q "$REPO14/.autopilot/GOAL.md" 2>/dev/null || printf 'none')
  S14b=$(md5 -q "$REPO14/.autopilot/state.json" 2>/dev/null || printf 'none')
  if [ "$G14" = "$G14b" ] && [ "$S14" = "$S14b" ]; then
    pass 14 "--probe-only 不改 GOAL.md / state.json"
  else
    fail 14 "--probe-only 不改 GOAL.md / state.json"
    printf 'GOAL 变了或 state.json 变了\n'
  fi
else
  fail 14 "--probe-only 不改 GOAL.md / state.json"
  cat "$TMP/out14b"
fi
# 没有工作区时必须明确报错，不是静默新建
EMPTY14="$TMP/repo14-empty"
mkdir -p "$EMPTY14"
sh "$INIT_SH" --probe-only "$EMPTY14" >"$TMP/out14c" 2>&1
RC14=$?
if [ "$RC14" -eq 2 ] && grep -q '需要已存在的' "$TMP/out14c"; then
  pass 14 "--probe-only 在没有工作区时明确报错（退出码 2）"
else
  fail 14 "--probe-only 在没有工作区时明确报错（退出码 2）"
  printf 'rc=%s\n' "$RC14"
  head -2 "$TMP/out14c"
fi

# --- 15. AUTOPILOT_HASH_IMPL 可强制指定，非法值明确报错 ---------------------
REPO15="$TMP/repo15"
mkdir -p "$REPO15"
(cd "$REPO15" && AUTOPILOT_HASH_IMPL=python sh "$INIT_SH" --goal "哈希实现" --repo "$REPO15") >"$TMP/out15" 2>&1
H15=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("hash_impl",""))' \
  "$REPO15/.autopilot/env.json" 2>/dev/null)
if [ "$H15" = "python" ]; then
  pass 15 "AUTOPILOT_HASH_IMPL=python 生效"
else
  fail 15 "AUTOPILOT_HASH_IMPL=python 生效"
  printf '实际 hash_impl=%s\n' "${H15:-<空>}"
fi
AUTOPILOT_HASH_IMPL=bogus sh "$INIT_SH" --probe-only "$REPO15" >"$TMP/out15b" 2>&1
RC15=$?
if [ "$RC15" -eq 2 ]; then
  pass 15 "AUTOPILOT_HASH_IMPL 非法值退出码 2"
else
  fail 15 "AUTOPILOT_HASH_IMPL 非法值退出码 2"
  printf 'rc=%s\n' "$RC15"
fi

# --- 16. H46 时长口径：缺省产物与 0.9.7 逐字节一致 -------------------------
REPO16="$TMP/repo16"
mkdir -p "$REPO16"
sh "$INIT_SH" --goal "缺省口径" --repo "$REPO16" >"$TMP/out16" 2>&1
G16="$REPO16/.autopilot/GOAL.md"
if grep -qxF 'minute_basis = wall      # H46 时长预算口径：wall（缺省，= 0.9.7 及更早）| active（按账本事件折叠出的活动分钟）' "$G16" \
   && ! grep -q '{{' "$G16"; then
  pass 16 "不加 --unattended：minute_basis 行逐字节不变，无残留占位符"
else
  fail 16 "不加 --unattended：minute_basis 行逐字节不变，无残留占位符"
  grep -n 'minute_basis' "$G16" | head -3
fi

# --- 17. --unattended "原话"：改写现有 ## BUDGET 行，并把原话留在同一行 -----
REPO17="$TMP/repo17"
mkdir -p "$REPO17"
sh "$INIT_SH" --goal "无人值守长跑" --repo "$REPO17" \
  --unattended "跨天连着跑，按活动分钟算" >"$TMP/out17" 2>&1
G17="$REPO17/.autopilot/GOAL.md"
python3 "$SELF_DIR/status.py" log "$REPO17" '{"type":"round","round":1,"note":"t17a"}' >/dev/null 2>&1
python3 "$SELF_DIR/status.py" log "$REPO17" '{"type":"round","round":2,"note":"t17b"}' >/dev/null 2>&1
S17=$(python3 "$SELF_DIR/status.py" summary "$REPO17" 2>&1)
if printf '%s' "$S17" | grep -q '时长按活动分钟计' \
   && grep -q '^minute_basis = active' "$G17" \
   && grep -q '人授权无人值守：跨天连着跑，按活动分钟算' "$G17"; then
  pass 17 "--unattended 写 active + 原话入档 + summary 按活动分钟"
else
  fail 17 "--unattended 写 active + 原话入档 + summary 按活动分钟"
  grep -n '^minute_basis' "$G17"
  printf '%s\n' "$S17" | grep -E '预算口径|用时' | head -2
fi

# --- 18. 口径开关只认 GOAL：status.py budget 不接受 minute_basis ------------
python3 "$SELF_DIR/status.py" budget "$REPO17" minute_basis=wall >"$TMP/out18" 2>&1
RC18=$?
if [ "$RC18" -ne 0 ] && grep -q '^minute_basis = active' "$G17"; then
  pass 18 "控制器用 status.py budget 改口径被拒（退 $RC18），GOAL 仍是 active"
else
  fail 18 "控制器用 status.py budget 改口径被拒"
  printf 'rc=%s\n' "$RC18"
  head -2 "$TMP/out18"
  grep -n '^minute_basis' "$G17"
fi

# --- 19. 三道拒绝：空原话 / 缺参数 / 与 --probe-only 冲突，且不写坏目录 -----
REPO19="$TMP/repo19"
mkdir -p "$REPO19"
sh "$INIT_SH" --goal x --repo "$REPO19" --unattended "" >/dev/null 2>&1; RC19A=$?
sh "$INIT_SH" --goal x --repo "$REPO19" --unattended >/dev/null 2>&1; RC19B=$?
sh "$INIT_SH" --probe-only "$REPO16" --unattended "跨天" >/dev/null 2>&1; RC19C=$?
if [ "$RC19A" -eq 2 ] && [ "$RC19B" -eq 2 ] && [ "$RC19C" -eq 2 ] \
   && [ -z "$(ls -A "$REPO19" 2>/dev/null)" ] && ! grep -q '^minute_basis = active' "$G16"; then
  pass 19 "空原话/缺参数/与 probe-only 冲突均退 2，且没落下半个工作区"
else
  fail 19 "空原话/缺参数/与 probe-only 冲突均退 2，且没落下半个工作区"
  printf 'rc=%s %s %s repo19=%s\n' "$RC19A" "$RC19B" "$RC19C" "$(ls -A "$REPO19" 2>/dev/null | tr '\n' ' ')"
fi

if [ "$FAILED" -eq 0 ]; then
  printf 'ALL PASS\n'
  exit 0
fi
printf '%s 个用例失败\n' "$FAILED"
exit 1
