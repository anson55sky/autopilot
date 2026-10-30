#!/bin/sh
# 元验收总入口：依次跑 M1–M11，每条一个 `RESULT M<n> PASS|FAIL|SKIP <说明>`。
# 用法: sh meta-checks/run.sh
#   M1 需要一个回归样本工作区：AUTOPILOT_META_SAMPLE=<dir>
#   M1 需要基线冻结脚本作对照：AUTOPILOT_BASELINE_CHECK=<path/to/check.sh>
#   两个都提供时 M1 才真判定，否则记 SKIP（不假绿）。
# 任何 FAIL → 总退出码 1。存在 SKIP → 总退出码仍为 0，但醒目提示"不得宣称全绿"。
# POSIX sh，零第三方依赖，不含任何绝对路径。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info[0]>=3 else 1)' >/dev/null 2>&1; then
      PY=$c
      break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "META FAIL 需要 python3（零第三方依赖，仅需标准库）"
  exit 1
fi

SAMPLE=${AUTOPILOT_META_SAMPLE:-}
IDS="1 2 3 4 5 6 7 8 9 10 11"
pass=0
fail=0
skip=0

for id in $IDS; do
  if [ "$id" = "1" ]; then
    out=$("$PY" "$HERE/m$id.py" --sample "$SAMPLE" 2>&1)
  else
    out=$("$PY" "$HERE/m$id.py" 2>&1)
  fi
  rc=$?
  # 取该条的判定行；脚本崩了/没产出判定行 → 记 FAIL
  line=$(printf '%s\n' "$out" | grep -E "^RESULT M$id (PASS|FAIL|SKIP)( |$)" | head -1)
  if [ -z "$line" ]; then
    printf 'RESULT M%s FAIL 脚本未产出判定行 (rc=%s)\n' "$id" "$rc"
    printf '%s\n' "$out" | sed 's/^/    | /'
    fail=$((fail + 1))
    continue
  fi
  printf '%s\n' "$line"
  status=$(printf '%s' "$line" | awk '{print $3}')
  case "$status" in
    PASS) pass=$((pass + 1)) ;;
    SKIP) skip=$((skip + 1)) ;;
    *)    fail=$((fail + 1)) ;;
  esac
done

total=$((pass + fail + skip))
printf '\n元验收 %d 例：PASS %d / FAIL %d / SKIP %d\n' "$total" "$pass" "$fail" "$skip"

if [ "$fail" -ne 0 ]; then
  printf '>>> 存在 FAIL，升级不得放行。\n'
  exit 1
fi
if [ "$skip" -ne 0 ]; then
  printf '>>> 注意：存在 %d 个未判定项（SKIP），不得宣称全绿。\n' "$skip"
  printf '    （M1 需同时提供 AUTOPILOT_META_SAMPLE 与 AUTOPILOT_BASELINE_CHECK 才判定）\n'
fi
exit 0
