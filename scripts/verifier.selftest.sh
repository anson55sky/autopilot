#!/bin/sh
# H31 验证者权限分级自测：A-va-01..07。全程在 mktemp -d 的假工作区里跑。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL=$(cd "$HERE/.." && pwd)
PY=${PYTHON:-python3}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

REPO="$TMP/repo"
mkdir -p "$REPO/.autopilot/rounds" "$REPO/src"
V="$SKILL/scripts/verifier.py"
RP="$SKILL/scripts/round_prompt.sh"

mk_goal() {  # $1 = off|present-off|on
    {
      printf '# GOAL — {REPO_ROOT}\n\n## 终结目标\n做 X\n\n## 预算\n- 轮次 ≤ 6\n'
      case "$1" in
        on) printf '\n## VERIFY_ACL\nenable = true\nrequire_mode = plan\n\n' ;;
        present-off) printf '\n## VERIFY_ACL\nenable = false\nrequire_mode = plan\n\n' ;;
      esac
    } > "$REPO/.autopilot/GOAL.md"
}
mk_state() { printf '{"schema":2,"rounds_used":%s,"phase":"verify"}\n' "$1" > "$REPO/.autopilot/state.json"; }
mk_host() {  # $1 = yes|no
    if [ "$1" = yes ]; then
      printf '{"primitives":{"session_mode":true,"intercept_permission":true}}\n' > "$REPO/.autopilot/host.json"
    else
      printf '{"primitives":{"intercept_permission":true}}\n' > "$REPO/.autopilot/host.json"
    fi
}

# ---------------------------------------------------------------- 1 关闭态

mk_goal off; mk_state 4; mk_host no
off_out=$(bash "$RP" "$REPO" 5 2>/dev/null)
rm -f "$REPO/.autopilot/GOAL.md"
mk_goal present-off
off2_out=$(bash "$RP" "$REPO" 5 2>/dev/null)
out=$($PY "$V" check --repo "$REPO" --task T-05 2>&1); rc=$?
if [ "$rc" = 23 ] && [ "$off_out" = "$off2_out" ] && ! printf '%s' "$off_out" | grep -q "验证者权限分级"; then
  pass 1 "未启用时 check 退 23，且 GOAL 里写了段落但 enable=false 时提示词输出与没写一字不差"
else
  fail 1 "关闭态不干净：rc=$rc / 输出差异 $([ "$off_out" = "$off2_out" ] && echo 无 || echo 有)"
fi

# ---------------------------------------------------------------- 2 启用后没声明就出结论

mk_goal on; mk_state 4; mk_host no
out=$($PY "$V" check --repo "$REPO" --task T-05 2>&1); rc=$?
if [ "$rc" = 24 ] && printf '%s' "$out" | grep -q "declare"; then
  pass 2 "启用后没有权限声明就想出结论 → 退 24 并给出该跑的 declare 命令"
else
  fail 2 "未声明没拦住：rc=$rc $out"
fi

# ---------------------------------------------------------------- 3 档位越界

$PY "$V" declare --repo "$REPO" --task T-05 --mode default >/dev/null 2>&1
out=$($PY "$V" check --repo "$REPO" --task T-05 2>&1); rc=$?
if [ "$rc" = 24 ] && printf '%s' "$out" | grep -q "仍能改产品码"; then
  pass 3 "声明成可写档（不在只读白名单）被拦住，并把后果说清楚"
else
  fail 3 "越档没拦住：rc=$rc $out"
fi

# ---------------------------------------------------------------- 4 无原语 = 诚实降级

$PY "$V" declare --repo "$REPO" --task T-05 --mode plan --session s-1 >/dev/null 2>&1
out=$($PY "$V" check --repo "$REPO" --task T-05 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "DEGRADED" \
   && printf '%s' "$out" | grep -q "提示词级"; then
  pass 4 "宿主无 session_mode 原语：退 0 但明写 DEGRADED + 只是自报（不把提示词级说成脚本级）"
else
  fail 4 "降级声明不对：rc=$rc $out"
fi

# ---------------------------------------------------------------- 5 有原语 = 真强制

mk_host yes
out=$($PY "$V" check --repo "$REPO" --task T-05 2>&1); rc=$?
if [ "$rc" = 0 ] && ! printf '%s' "$out" | grep -q DEGRADED \
   && printf '%s' "$out" | grep -q "宿主原语强制"; then
  pass 5 "宿主有原语时不提降级，直接按强制档位放行"
else
  fail 5 "原语在位时口径不对：rc=$rc $out"
fi

# ---------------------------------------------------------------- 6 一次声明不能吃全程

mk_state 5
out=$($PY "$V" check --repo "$REPO" --task T-05 2>&1); rc=$?
if [ "$rc" = 24 ] && printf '%s' "$out" | grep -q "第 5 轮"; then
  pass 6 "上一轮的声明在当前轮失效（退 24），不给"声明一次管全程"留口子"
else
  fail 6 "跨轮复用没拦住：rc=$rc $out"
fi

# ---------------------------------------------------------------- 7 打开态才追加提示词段；audit 与账本

mk_state 5
rp_on=$(bash "$RP" "$REPO" 5 2>/dev/null)
$PY "$V" declare --repo "$REPO" --task T-05 --mode plan --session s-2 >/dev/null 2>&1
audit=$($PY "$V" audit --repo "$REPO" 2>&1)
ledger_has=$(grep -c '"type": "verify_acl"' "$REPO/.autopilot/ledger.jsonl" 2>/dev/null || printf 0)
if printf '%s' "$rp_on" | grep -q "验证者权限分级" && printf '%s' "$rp_on" | grep -q "verifier.py declare" \
   && printf '%s' "$audit" | grep -q "T-05" && [ "${ledger_has:-0}" -ge 1 ]; then
  pass 7 "启用后执行器提示词里带上权限段，audit 列出本轮声明，声明也进了账本"
else
  msg="打开态接线不全：prompt权限段=$(printf '%s' "$rp_on" | grep -c 权限分级) audit命中=$(printf '%s' "$audit" | grep -c T-05) 账本=$ledger_has"
  fail 7 "$msg"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
