#!/bin/sh
# H16 Triage 归类自测：A-tr-01..05。分类只出建议，任何路径都不许改判定文件。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TRI="$HERE/triage.py"
PY=${PYTHON:-python3}

TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPROOT"' EXIT INT TERM

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

sha_of() {  # 若干文件的拼接哈希，用于"有没有被动过"
    $PY -c 'import hashlib,sys
h = hashlib.sha256()
for p in sys.argv[1:]:
    h.update(p.encode())
    try:
        h.update(open(p, "rb").read())
    except OSError:
        h.update(b"<missing>")
print(h.hexdigest())' "$@"
}

new_repo() {
    _r_repo="$TMPROOT/$1"
    mkdir -p "$_r_repo/.autopilot/rounds" "$_r_repo/.autopilot/checks"
    printf '# GOAL\n' > "$_r_repo/.autopilot/GOAL.md"
    printf '%s' '{"epoch":1,"tasks":[
 {"id":"T-01","title":"a","role":"Builder","status":"done","deps":[],"write_set":["src/a.js"],"acceptance":["A20"],"card":"c.md"},
 {"id":"T-02","title":"b","role":"Builder","status":"failed","deps":[],"write_set":["src/b.js"],"acceptance":["A30"],"card":"c.md","premise_tag":"p1"},
 {"id":"T-03","title":"c","role":"Builder","status":"failed","deps":[],"write_set":["src/c.js"],"acceptance":["A30"],"card":"c.md","premise_tag":"p1"},
 {"id":"T-04","title":"d","role":"Builder","status":"pending","deps":[],"write_set":["src/d.js"],"acceptance":["A9"],"card":"c.md"}]}' \
        > "$_r_repo/.autopilot/tasks.json"
    printf '%s' '{"capabilities":{"browser":null,"container":"docker 27","python":"3.14.2"}}' > "$_r_repo/.autopilot/environment.json"
    printf '%s' '{"_README":"注释键忽略","A9":["browser"],"A20":["container"],"A31":["browser","container"]}' \
        > "$_r_repo/.autopilot/acceptance-needs.json"
    printf '%s' '{"passed":["A1"],"failed":["A9","A20","A31","A30","A77"],"skipped":[],"exit":1}' \
        > "$_r_repo/.autopilot/checks/last-result.json"
    printf '#!/bin/sh\nexit 0\n' > "$_r_repo/.autopilot/checks/run.sh"
    printf 'sha x .autopilot/checks/run.sh\n' > "$_r_repo/.autopilot/checks/MANIFEST.sha256"
    printf '%s' '{"round":1,"verdict":"fail","passed":["A1"],"failed":["A9"],"tasks_closed":0,
      "blind_spots":["A47 在 level 被钳制到 3 时仍可 PASS（空过）","A22 未验护盾计时自然递减"],
      "notes":"两条断言有洞。"}' > "$_r_repo/.autopilot/rounds/r-01.json"
    printf '%s\n' "$_r_repo"
}

# ---------------------------------------------------------------- 四类分桶

repo=$(new_repo tr1)
out=$($PY "$TRI" classify --repo "$repo" --json 2>&1); rc=$?
if [ "$rc" = "0" ]; then pass 1 "classify 正常退出"; else fail 1 "classify rc=$rc：$out"; fi

if printf '%s' "$out" | $PY -c '
import json,sys
d = json.load(sys.stdin)
b = d["buckets"]
env = {x["a"] for x in b["env"]}
code = {x["a"] for x in b["code"]}
un = {x["a"] for x in b["unimpl"]}
acc = len(b["acceptance"])
sys.exit(0 if env == {"A9", "A31"} and code == {"A20"} and un == {"A77", "A30"} and acc >= 1 else 1)
'; then
  pass 1 "四类分对了：缺能力→env（优先级最高）、已完成卡仍红→code、没卡覆盖→unimpl、盲区洞→acceptance"
else
  fail 1 "分桶结果不对：$(printf '%s' "$out" | tr -d '\n' | head -c 400)"
fi

if printf '%s' "$out" | $PY -c '
import json,re,sys
d = json.load(sys.stdin)
ids = [x.get("a") for b in d["buckets"].values() for x in b if isinstance(x, dict) and x.get("a")]
bad = [i for i in ids if not re.match(r"^A\d+$", str(i))]
sys.exit(0 if bad == [] and ids else 1)
'; then
  pass 1 "进桶的全是 A# 编号，acceptance-needs 的下划线注释键被忽略"
else
  fail 1 "有非 A# 编号或注释键混进分桶"; fi

# ---------------------------------------------------------------- 前提置疑

text=$($PY "$TRI" classify --repo "$repo" 2>&1)
if printf '%s' "$text" | grep -q "前提置疑" && printf '%s' "$text" | grep -q "T-02,T-03"; then
  pass 3 "同前提两次失败被点名，并写明第三次修法不得开工"
else
  fail 3 "前提置疑没出来：$(printf '%s' "$text" | grep -A 3 前提置疑)"
fi

# ---------------------------------------------------------------- 只作建议

if printf '%s' "$text" | grep -q "判定来源仍是冻结"; then
  pass 4 "输出里明写「判定来源仍是冻结 run.sh 的 RESULT 行」"
else
  fail 4 "缺建议属性声明"
fi

before=$(sha_of "$repo/.autopilot/checks/run.sh" "$repo/.autopilot/rounds/r-01.json")
$PY "$TRI" propose --repo "$repo" --out .autopilot/triage-suggest.md >/dev/null 2>&1
after=$(sha_of "$repo/.autopilot/checks/run.sh" "$repo/.autopilot/rounds/r-01.json")
if [ "$before" = "$after" ]; then
  pass 5 "propose 之后 checks/ 与轮次报告一字未动（不越权改判定）"
else
  fail 5 "propose 动了判定文件！"
fi
if [ -f "$repo/.autopilot/triage-suggest.md" ] \
   && grep -q "第三次修法不得开工" "$repo/.autopilot/triage-suggest.md" \
   && grep -q "人批准" "$repo/.autopilot/triage-suggest.md"; then
  pass 5 "提案文本落到独立文件，等人工确认，不自动合并"
else
  fail 5 "提案文件内容不对"
fi

# ---------------------------------------------------------------- 没有账本时不崩

empty="$TMPROOT/empty"
mkdir -p "$empty/.autopilot"
$PY "$TRI" classify --repo "$empty" >/dev/null 2>&1
rc=$?
if [ "$rc" = "0" ]; then
  pass 2 "账本残缺时照样出报告（不崩、不假绿）"
else
  fail 2 "空工作区 classify 退 $rc"
fi
$PY "$TRI" classify --repo "$TMPROOT/nope" >/dev/null 2>&1
rc2=$?
if [ "$rc2" = "5" ]; then pass 2 "没有 .autopilot 时退 5（缺工作区），不当作分类结果"; else fail 2 "缺工作区 rc=$rc2"; fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
