#!/bin/sh
# H15 看板自测：A-db-01..05。只读快照、单文件、无外部依赖、不带本机路径。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL=$(cd "$HERE/.." && pwd)
DASH="$SKILL/tools/dashboard.py"
PY=${PYTHON:-python3}

TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPROOT"' EXIT INT TERM

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

hash_tree() {  # 目录里除指定前缀外的全部文件哈希
    $PY -c 'import hashlib,os,sys
root, skip = sys.argv[1], sys.argv[2]
h = hashlib.sha256()
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = sorted(d for d in dirnames)
    rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
    if rel.startswith(skip):
        continue
    for fn in sorted(filenames):
        p = os.path.join(dirpath, fn)
        if os.path.getsize(p) > 4 * 1024 * 1024:
            continue
        h.update(os.path.relpath(p, root).encode())
        h.update(open(p, "rb").read())
print(h.hexdigest())' "$1" "$2"
}

new_repo() {
    _d_repo="$TMPROOT/$1"
    mkdir -p "$_d_repo/.autopilot/rounds" "$_d_repo/.autopilot/checks"
    printf '# GOAL\n\n目标：把看板做出来\n' > "$_d_repo/.autopilot/GOAL.md"
    printf '%s' '{"phase":"verify","rounds_used":2,"budget":{"max_rounds":9,"max_minutes":600,"max_calls":80},
      "goal":"目标：把看板做出来（本机路径 '"$_d_repo"' 不该外泄）"}' > "$_d_repo/.autopilot/state.json"
    printf '%s' '{"epoch":2,"tasks":[
      {"id":"T-01","title":"实现渲染","role":"Builder","status":"done","deps":[],"write_set":["src/a.js"],"acceptance":["A1"],"card":"c.md"},
      {"id":"T-02","title":"实现看板","role":"Builder","status":"pending","deps":["T-01"],"write_set":["src/b.js"],"acceptance":["A2"],"card":"c.md"}]}' \
        > "$_d_repo/.autopilot/tasks.json"
    printf '%s' '{"passed":["A1"],"failed":[],"skipped":["A2"],"exit":1}' > "$_d_repo/.autopilot/checks/last-result.json"
    printf '%s' '{"capabilities":{"browser":null,"python":"3.14.2"}}' > "$_d_repo/.autopilot/environment.json"
    printf '%s' '{"host":"qoder-desktop","primitives":{"spawn_session":true}}' > "$_d_repo/.autopilot/host.json"
    printf '%s\n' '{"type":"worker","task":"T-01","ts":"2026-11-01T01:00:00+00:00","note":"路径 '"$_d_repo"'"}' \
        > "$_d_repo/.autopilot/ledger.jsonl"
    printf '%s' '{"round":1,"verdict":"fail","passed":["A1"],"failed":[],"skipped":["A2"],"notes":"一轮收完"}' \
        > "$_d_repo/.autopilot/rounds/r-01.json"
    printf '%s' '{"round":1,"calls_used":7,"elapsed_minutes":120,"coverage":{"contract_items":5,"with_source":3,"ratio":0.6,"protected_by_arrays":2,"weak_not_in_arrays":["A4"],"no_source":["A5","A6"]}}' > "$_d_repo/.autopilot/rounds/r-01.metrics.json"
    printf '%s\n' "$_d_repo"
}

# ---------------------------------------------------------------- 渲染与脱敏

repo=$(new_repo db1)
before=$(hash_tree "$repo/.autopilot" "dashboard")
out=$($PY "$DASH" render --repo "$repo" 2>&1); rc=$?
page="$repo/.autopilot/dashboard/index.html"
if [ "$rc" = "0" ] && [ -f "$page" ]; then
  pass 1 "render 写出单文件看板"
else
  fail 1 "render 失败（rc=$rc）：$out"
fi
if grep -q "$repo" "$page"; then
  fail 2 "看板里带本机绝对路径"
else
  pass 2 "看板全文脱敏（路径写成 {REPO_ROOT}）"
fi
if grep -q "不构成验收证据" "$page" && grep -q "验收 PASS" "$page" && grep -q "SKIP（未判定）" "$page"; then
  pass 3 "页面上明写只读快照 + SKIP 单列为未判定"
else
  fail 3 "看板缺关键声明：$(grep -o "不构成验收证据\|SKIP（未判定）" "$page" | sort -u | tr '\n' ' ')"
fi
if grep -q "T-02" "$page" && grep -q "src/b.js" "$page" && grep -q "browser" "$page"; then
  pass 1 "任务、写集与缺能力（browser=null）都进了页面（含依赖边来源）"
else
  fail 1 "任务/能力没渲染出来"
fi
if grep -q "7 / 80" "$page" && grep -q "120 / 600 分" "$page"; then
  pass 4 "预算取自最近一轮 metrics（不猜数）"
else
  fail 4 "预算数字没出现：$(grep -o "[0-9]* / 80\|[0-9]* / 600 分" "$page" | tr '\n' ' ')"
fi
# H19 × H38：覆盖率卡片必须用契约条目数当分母，并把缺口与 WEAK 一起显示
if grep -q "判定覆盖率" "$page" && grep -q "3/5（缺 2 · 未受兜底 1）" "$page"; then
  pass 6 "看板有判定覆盖率卡片：3/5 + 缺 2 + 未受兜底 1，分母来自契约而不是跑出的结果数"
else
  fail 6 "覆盖率卡片没渲染或分母用错：$(grep -o "判定覆盖率[^<]*<b>[^<]*" "$page" | head -2)"
fi

after=$(hash_tree "$repo/.autopilot" "dashboard")
if [ "$before" = "$after" ]; then
  pass 5 "只读：除 dashboard/ 外，.autopilot 一字未动"
else
  fail 5 "看板写动了别的东西！"
fi

# ---------------------------------------------------------------- 降级与摘要

$PY "$DASH" check --repo "$repo" > "$TMPROOT/check.out" 2>&1
rc=$?
if [ "$rc" = "0" ] && grep -q "验收 PASS 1 / FAIL 0 / SKIP 1" "$TMPROOT/check.out" \
   && grep -q "判定覆盖率 3/5（缺 2 · 未受兜底 1）" "$TMPROOT/check.out"; then
  pass 3 "check 单行摘要里也带判定覆盖率（监督者不用开页面就能看到分母）"
else
  fail 3 "check 输出不对：$(cat "$TMPROOT/check.out")"
fi

empty="$TMPROOT/db-empty"
mkdir -p "$empty/.autopilot"
out2=$($PY "$DASH" render --repo "$empty" 2>&1); rc2=$?
if [ "$rc2" = "0" ] && grep -q "tasks.json 为空" "$empty/.autopilot/dashboard/index.html" \
   && grep -q "—（未收轮或 GOAL 无矩阵行）" "$empty/.autopilot/dashboard/index.html"; then
  pass 4 "空工作区照样出页并如实标空，覆盖率卡片写占位而不编数"
else
  fail 4 "空工作区处理不对（rc=$rc2）：$out2"
fi
$PY "$DASH" render --repo "$TMPROOT/nope" >/dev/null 2>&1
rc3=$?
if [ "$rc3" = "2" ]; then pass 2 "没有 .autopilot 时退 2 并提示先跑 init.sh"; else fail 2 "缺工作区 rc=$rc3"; fi

# 单文件、零外部依赖（不许出现 http(s) 引用）
if grep -qE "https?://" "$page"; then
  fail 5 "看板引用了外部资源（违反离线与隐私约束）"
else
  pass 5 "看板零外部引用，离线可看"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
