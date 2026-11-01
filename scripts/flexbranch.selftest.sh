#!/bin/sh
# H35 多分支 flex 对比自测：A-fb-01..07。全程在 mktemp -d 的假工作区里跑。
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
mkdir -p "$REPO/.autopilot" "$REPO/sandbox" "$REPO/src"
FB="$SKILL/scripts/flexbranch.py"

put_goal() {  # $1 = branch_max（空串=不写这一行）
    {
      printf '# GOAL — {REPO_ROOT}\n\n## 终结目标\n做 X\n\n## FLEX_RULES\nmode_default = strict\n'
      [ -n "${1:-}" ] && printf 'branch_max = %s\n' "$1"
      printf '\n'
    } > "$REPO/.autopilot/GOAL.md"
}
printf '{"schema":2,"rounds_used":5,"phase":"build","budget":{"max_rounds":9}}\n' \
  > "$REPO/.autopilot/state.json"
printf '{"epoch":2,"tasks":[{"id":"T-04","status":"doing","track":"flex-light","write_set":["sandbox/T-04"]}]}\n' \
  > "$REPO/.autopilot/tasks.json"

# ---------------------------------------------------------------- 1 关闭态

put_goal ""
rc_all=0
for c in "list" "add --task T-04 --name a --target sandbox/T-04/a" "audit"; do
    o=$($PY "$FB" $c --repo "$REPO" 2>&1); r=$?
    [ "$r" = 23 ] || rc_all=1
done
if [ "$rc_all" = 0 ] && ! [ -e "$REPO/sandbox/.gate/branches.json" ]; then
  pass 1 "FLEX_RULES 里没有 branch_max（或为 0）时三个子命令都退 23，且不落任何文件"
else
  fail 1 "关闭态不干净（写出东西或退出码不对）"
fi

# ---------------------------------------------------------------- 2 登记与上限

put_goal 2
$PY "$FB" add --repo "$REPO" --task T-04 --name lazy --target sandbox/T-04/lazy --purpose "首屏不卡" >/dev/null 2>&1
$PY "$FB" add --repo "$REPO" --task T-04 --name eager --target sandbox/T-04/eager >/dev/null 2>&1
out=$($PY "$FB" add --repo "$REPO" --task T-04 --name third --target sandbox/T-04/third 2>&1); rc=$?
if [ "$rc" = 24 ] && printf '%s' "$out" | grep -q "branch_max=2"; then
  pass 2 "分支数到 branch_max 就退 24，不给无限开分支烧预算"
else
  fail 2 "上限没生效：rc=$rc $out"
fi
out=$($PY "$FB" add --repo "$REPO" --task T-04 --name lazy --target sandbox/T-04/lazy2 2>&1); rc=$?
if [ "$rc" = 24 ]; then
  pass 2 "同卡重名分支被拦住：两个名字指向同一个做法不算对比"
else
  fail 2 "重名没拦住：rc=$rc $out"
fi

# ---------------------------------------------------------------- 3 写集越界

out=$($PY "$FB" add --repo "$REPO" --task T-09 --name sneaky --target src/sneaky.py 2>&1); rc=$?
if [ "$rc" = 22 ] && printf '%s' "$out" | grep -q "sandbox/"; then
  pass 3 "分支产物落在 sandbox/ 之外退 22（探索代码不得混进主目录）"
else
  fail 3 "越界没拦住：rc=$rc $out"
fi

# ---------------------------------------------------------------- 4 只有 Verifier 能定选择

mkdir -p "$REPO/sandbox/T-04/lazy" "$REPO/sandbox/T-04/eager"
printf 'x\n' > "$REPO/sandbox/T-04/lazy/impl.js"
tasks_before=$(shasum -a 256 "$REPO/.autopilot/tasks.json" | cut -d' ' -f1)
out=$($PY "$FB" pick --repo "$REPO" --task T-04 --choose lazy --by builder --note "我的方案最快，A7 应该能过" 2>&1); rc=$?
if [ "$rc" = 31 ] && printf '%s' "$out" | grep -q "只有 Verifier"; then
  pass 4 "写码的人选自己的方案被剥夺权限（退 31）"
else
  fail 4 "角色没拦住：rc=$rc $out"
fi

out=$($PY "$FB" pick --repo "$REPO" --task T-04 --choose lazy --by verifier --note "短" 2>&1); rc=$?
if [ "$rc" = 2 ] && printf '%s' "$out" | grep -q "20 字"; then
  pass 4 "理由少于 20 字被拒：空话式选择理由不进提案"
else
  fail 4 "理由长度没校验：rc=$rc $out"
fi

# ---------------------------------------------------------------- 5 选择写成提案，判定面一字不动

out=$($PY "$FB" pick --repo "$REPO" --task T-04 --choose lazy --by verifier \
      --note "冻结矩阵里 A7 与 A9 只有 lazy 这条能过，eager 首屏超时" 2>&1); rc=$?
prop="$REPO/sandbox/proposals/BRANCH_PICK-T-04-1.md"
tasks_after=$(shasum -a 256 "$REPO/.autopilot/tasks.json" | cut -d' ' -f1)
if [ "$rc" = 0 ] && [ -f "$prop" ] && [ "$tasks_before" = "$tasks_after" ] \
   && printf '%s' "$out" | grep -q "本 run 不生效" \
   && grep -q "epoch +1" "$prop" && grep -q "eager" "$prop"; then
  pass 5 "选择落成为提案（含落选分支与生效方式），tasks.json 指纹未变——探索不碰判定"
else
  fail 5 "提案落点或生效声明不对：rc=$rc 文件=$([ -f "$prop" ] && echo 有 || echo 无)"
fi

# ---------------------------------------------------------------- 6 账本可追溯

if grep -q '"flex_branch_pick"' "$REPO/.autopilot/ledger.jsonl" 2>/dev/null \
   && grep -q '"chosen": "lazy"' "$REPO/.autopilot/ledger.jsonl"; then
  pass 6 "对比结果进账本（chosen/rejected/round），审计包能重建"
else
  fail 6 "账本里没有 flex_branch_pick 事件"
fi

# ---------------------------------------------------------------- 7 审计口径

out=$($PY "$FB" audit --repo "$REPO" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "分支 2 个" && printf '%s' "$out" | grep -q "提案 1 份"; then
  pass 7 "audit 报出分支数与提案数——有分支却没提案等于没比"
else
  fail 7 "audit 口径不对：rc=$rc $out"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
