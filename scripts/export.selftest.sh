#!/bin/sh
# H16/H32 导出自测：A-ex-01..05。只在 mktemp -d 造工作区，绝不碰真实仓库，也不执行 git 写操作。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
EXPORT="$HERE/export.py"
PY=${PYTHON:-python3}

TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPROOT"' EXIT INT TERM

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

new_repo() {
    _e_repo="$TMPROOT/$1"
    mkdir -p "$_e_repo/.autopilot/rounds/r-01-evidence" "$_e_repo/.autopilot/checks" "$_e_repo/src"
    printf '# GOAL\n\n验收矩阵见 checks/run.sh。\n' > "$_e_repo/.autopilot/GOAL.md"
    printf '# CHARTER\n' > "$_e_repo/.autopilot/CHARTER.md"
    printf '%s' '{"epoch":1,"tasks":[{"id":"T-01","title":"x","role":"Builder","status":"done","deps":[],"write_set":["src/a.js"],"acceptance":["A1"],"card":"c.md"}]}' \
        > "$_e_repo/.autopilot/tasks.json"
    printf '%s' '{"started_at":"2026-01-01T00:00:00+00:00","phase":"verify","rounds_used":1,"budget":{"max_rounds":4}}' \
        > "$_e_repo/.autopilot/state.json"
    printf '%s\n' 'RESULT A1 PASS 逻辑绿了' > "$_e_repo/.autopilot/checks/last.log"
    printf '%s' '{"passed":["A1"],"failed":[],"skipped":["A2"],"exit":0}' > "$_e_repo/.autopilot/checks/last-result.json"
    printf 'sha  abc  .autopilot/checks/run.sh\n' > "$_e_repo/.autopilot/checks/MANIFEST.sha256"
    printf '#!/bin/sh\necho RESULT A1 PASS\n' > "$_e_repo/.autopilot/checks/run.sh"
    printf '%s' '{"type":"worker","task":"T-01"}' > "$_e_repo/.autopilot/ledger.jsonl"
    printf '%s' '{"capabilities":{"browser":"Chrome 1"}}' > "$_e_repo/.autopilot/environment.json"
    printf '%s' '{"host":"generic-cli"}' > "$_e_repo/.autopilot/host.json"
    printf '%s' '{"round":1,"verdict":"fail","passed":["A1"],"failed":["A3"],"skipped":["A2"],"tasks_closed":0,
      "blind_spots":["A3 的断言在 level 被钳制时仍可空过","本机路径 '"$_e_repo"' 不该外泄"],
      "notes":"验证者拒收。"}' > "$_e_repo/.autopilot/rounds/r-01.json"
    printf '原始日志 %s\n' "$_e_repo" > "$_e_repo/.autopilot/rounds/r-01-evidence/run.log"
    printf '%s\n' "$_e_repo"
}

# ---------------------------------------------------------------- A-ex-01 出包

repo=$(new_repo ex01)
out=$($PY "$EXPORT" pack --repo "$repo" 2>&1); rc=$?
man="$repo/.autopilot/exports/evidence-r-01/MANIFEST.json"
if [ "$rc" = "0" ] && [ -f "$man" ]; then
  pass 1 "pack 出证据包并写清单"
else
  fail 1 "pack 失败（rc=$rc）：$out"
fi
n=$(grep -c '"path"' "$man" 2>/dev/null)
if [ "${n:-0}" -ge 10 ]; then
  pass 1 "清单条目覆盖契约/账本/轮次/证据/工装（$n 条）"
else
  fail 1 "清单只有 ${n:-0} 条，覆盖不足"
fi

# ---------------------------------------------------------------- A-ex-02 脱敏

if grep -rq "$repo" "$repo/.autopilot/exports/evidence-r-01/files" 2>/dev/null; then
  fail 2 "出包含本机绝对路径，脱敏没生效"
else
  pass 2 "包内所有文件的本机路径都换成 {REPO_ROOT}"
fi
if grep -q '{REPO_ROOT}' "$repo/.autopilot/exports/evidence-r-01/files/.autopilot/rounds/r-01-evidence/run.log"; then
  pass 2 "被脱敏的证据文件仍保留可读占位符"
else
  fail 2 "证据文件里的路径没被替换"
fi

# ---------------------------------------------------------------- A-ex-03 事后篡改可查

$PY "$EXPORT" verify --repo "$repo" --manifest "$man" >/dev/null 2>&1
rc_is=$?
[ "$rc_is" = "0" ] && pass 3 "verify 首轮通过" || fail 3 "verify 本该通过（rc=$rc_is）"
printf '被人改过\n' >> "$repo/.autopilot/exports/evidence-r-01/files/.autopilot/GOAL.md"
out=$($PY "$EXPORT" verify --repo "$repo" --manifest "$man" 2>&1); rc=$?
if [ "$rc" != "0" ] && printf '%s' "$out" | grep -q "与清单不符"; then
  pass 3 "证据文件被改动后 verify 立刻查出"
else
  fail 3 "篡改没被查出来：$out"
fi

# ---------------------------------------------------------------- A-ex-04 原仓库一字未动

repo2=$(new_repo ex04)
before=$(cd "$repo2" && find . -type f | sort | xargs $PY -c 'import hashlib,sys
h=hashlib.sha256()
for line in sys.stdin:
    p=line.strip()
    h.update(p.encode())
    h.update(open(p,"rb").read())
print(h.hexdigest())')
$PY "$EXPORT" pack --repo "$repo2" >/dev/null 2>&1
after=$(cd "$repo2/.autopilot/exports" && true; cd "$repo2" && find . -type f -not -path "./.autopilot/exports/*" | sort | xargs $PY -c 'import hashlib,sys
h=hashlib.sha256()
for line in sys.stdin:
    p=line.strip()
    h.update(p.encode())
    h.update(open(p,"rb").read())
print(h.hexdigest())')
if [ "$before" = "$after" ]; then
  pass 4 "pack 只写导出目录，原仓库字节不变（不删不改）"
else
  fail 4 "原仓库被动过：$before → $after"
fi

# ---------------------------------------------------------------- A-ex-05 PR 描述

repo3=$(new_repo ex05)
pr=$($PY "$EXPORT" pr --repo "$repo3" 2>&1); rc=$?
if [ "$rc" = "0" ] && printf '%s' "$pr" | grep -q "验证者拒收" && printf '%s' "$pr" | grep -q "A3 的断言"; then
  pass 5 "PR 描述带判定来源、盲区与收轮说明"
else
  fail 5 "PR 描述不对：$(printf '%s' "$pr" | head -5)"
fi
if printf '%s' "$pr" | grep -q "SKIP 1" && printf '%s' "$pr" | grep -q "未判定（缺能力"; then
  pass 5 "SKIP 单列且不混进通过（B3 口径守住）"
else
  fail 5 "SKIP 口径丢了：$(printf '%s' "$pr" | grep -n SKIP | head -3)"
fi
if printf '%s' "$pr" | grep -q "$repo3"; then
  fail 5 "PR 文本里还留着本机路径"
else
  pass 5 "PR 文本已脱敏，可直接贴给外部"
fi
if printf '%s' "$pr" | grep -q "控制器不执行 push"; then
  pass 5 "PR 文本自带「不自动 push」声明（铁律 5）"
else
  fail 5 "缺不可逆声明"
fi

# ---------------------------------------------------------------- A-ex-06 OTLP 导出（H34）

repo4=$(new_repo ex06)
{
  printf '%s\n' '{"type":"worker","task":"T-01","ts":"2026-11-01T02:00:00+00:00","note":"本机 '"$repo4"' 路径要脱敏"}'
  printf '%s\n' '{"type":"round","round":1,"ts":"2026-11-01T03:00:00+00:00","verdict":"fail"}'
} > "$repo4/.autopilot/ledger.jsonl"
$PY "$EXPORT" otel --repo "$repo4" --out .autopilot/exports/otel.json >"$TMPROOT/ex06.out" 2>&1; rc=$?
if [ "$rc" = "0" ] && [ -f "$repo4/.autopilot/exports/otel.json" ]; then
  pass 6 "otel 写出 OTLP 风格 JSON 文件"
else
  fail 6 "otel 失败（rc=$rc）：$(cat "$TMPROOT/ex06.out")"
fi
if $PY - "$repo4/.autopilot/exports/otel.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
spans = [s for rs in d["resourceSpans"] for ss in rs["scopeSpans"] for s in ss["spans"]]
assert len(spans) == 2, spans
assert all(s["traceId"] and s["spanId"] and s["startTimeUnixNano"] != "0" for s in spans)
assert any(s["name"].startswith("round") for s in spans), [s["name"] for s in spans]
PY
then
  pass 6 "两条 span 都带 traceId/spanId 与可解析时间（worker 与 round 各一条）"
else
  fail 6 "span 结构或计数不对"
fi
OTEL="$repo4/.autopilot/exports/otel.json"
if [ -f "$OTEL" ] && ! grep -q "$repo4" "$OTEL"; then
  pass 6 "span 属性已脱敏，可直接给外部观测栈"
else
  fail 6 "导出文件缺失或仍含本机路径"
fi
if [ -f "$OTEL" ] && ! grep -qE "https?://" "$OTEL"; then
  pass 6 "不发送任何网络请求，只落文件（默认关，显式调用才出）"
else
  fail 6 "导出里出现了外部地址或文件不存在"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
