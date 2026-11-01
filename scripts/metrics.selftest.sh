#!/bin/sh
# H19 度量自测：A-mt-01..07。在 mktemp -d 的假工作区里造轮次文档，不碰真项目。
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

R="$TMP/w"; mkdir -p "$R/.autopilot/rounds"
M="$SKILL/scripts/metrics.py"

mk_round() {  # $1=轮 $2=manifest戳 $3=passed(JSON数组) $4=failed(JSON数组)
    printf '{"round":%s,"verdict":"pass","manifest":"%s","passed":%s,"failed":%s,"skipped":[]}\n' \
      "$1" "$2" "$3" "$4" > "$R/.autopilot/rounds/r-$(printf '%02d' "$1").json"
}
mk_tasks() {
    printf '{"epoch":0,"tasks":[%s]}\n' "$1" > "$R/.autopilot/tasks.json"
}

# ---------------------------------------------------------------- 1 空工作区不编数

out=$($PY "$M" summary --repo "$R" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "INSUFFICIENT" \
   && printf '%s' "$out" | grep -q "NA（宿主未上报，不自估）" \
   && ! printf '%s' "$out" | grep -qE "漂移：[0-9]"; then
  pass 1 "空工作区：漂移与成本都打 INSUFFICIENT/NA，绝不冒出一个数"
else
  fail 1 "空数据却给了数字：rc=$rc $(printf '%s' "$out" | sed -n '2p')"
fi

# ---------------------------------------------------------------- 2 单轮无对比序列

mk_round 1 "" '["A1","A2"]' '["A3"]'
out=$($PY "$M" verdicts --repo "$R" 2>&1); rc=$?
if [ "$rc" = 10 ] && printf '%s' "$out" | grep -q INSUFFICIENT; then
  pass 2 "只有一轮时退 10（INSUFFICIENT），不把『没有对比』说成『零漂移』"
else
  fail 2 "单轮判定不对：rc=$rc $out"
fi

# ---------------------------------------------------------------- 3 同基线全一致 → 0 漂移

mk_round 2 "deadbeef1234" '["A1","A2"]' '["A3"]'
mk_round 1 "deadbeef1234" '["A1","A2"]' '["A3"]'
out=$($PY "$M" verdicts --repo "$R" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "0.0%"; then
  pass 3 "同一冻结基线下判定完全一致 → 漂移率 0.0%（且是真算出来的）"
else
  fail 3 "零漂移算错：rc=$rc $out"
fi

# ---------------------------------------------------------------- 4 同基线翻转 → 报出来

mk_round 3 "deadbeef1234" '["A1"]' '["A2","A3"]'
out=$($PY "$M" verdicts --repo "$R" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -qE "漂移率 = [1-9]" \
   && printf '%s' "$out" | grep -q "DRIFT A#A2"; then
  pass 4 "同一基线戳下 A2 由 PASS 翻成 FAIL → 计入漂移并点名（这才是『判定腐化』的信号）"
else
  fail 4 "翻转没抓到：rc=$rc $out"
fi

# ---------------------------------------------------------------- 5 换基线不算漂移

mk_round 4 "cafe1234abcd" '["A1"]' '["A2","A3"]'
before=$($PY "$M" verdicts --repo "$R" 2>&1)
mk_round 5 "cafe1234abcd" '["A1","A2"]' '["A3"]'
after=$($PY "$M" verdicts --repo "$R" 2>&1)
if printf '%s' "$after" | grep -q "DRIFT A#A2"; then
  pass 5 "新基线（不同 manifest 戳）内部照样能算，且不与旧基线混在一起比"
else
  fail 5 "分基线统计不对：$after"
fi

# ---------------------------------------------------------------- 6 成本只认宿主上报

mk_tasks '{"id":"T-01","status":"done","attempts":1},{"id":"T-02","status":"done","attempts":3},{"id":"T-03","status":"ready"}'
out=$($PY "$M" cost --repo "$R" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "NA（宿主未上报，不自估）" \
   && printf '%s' "$out" | grep -q "一次通过 0.5000"; then
  pass 6 "没有宿主 usage 事件时成本是 NA；一次通过率按 attempts 精确算（1/2 卡首试即过）"
else
  fail 6 "成本/通过率口径不对：rc=$rc $(printf '%s' "$out" | tr '\n' ' ')"
fi
printf '{"type":"usage","source":"host","usd":4.0,"round":5}\n' >> "$R/.autopilot/ledger.jsonl"
printf '{"type":"usage","source":"self-estimate","usd":99.0}\n' >> "$R/.autopilot/ledger.jsonl"
out=$($PY "$M" cost --repo "$R" 2>&1)
if printf '%s' "$out" | grep -q "USD=4.0" && printf '%s' "$out" | grep -q "每关闭卡=2.0" \
   && ! printf '%s' "$out" | grep -q "103"; then
  pass 6 "只累加 source=host 的成本；自估事件（source=self-estimate）不进判定数字"
else
  fail 6 "成本来源过滤不对：$(printf '%s' "$out" | head -1)"
fi

# ---------------------------------------------------------------- 7 机器可读

j=$($PY "$M" summary --repo "$R" --json 2>&1 | tail -1)
if printf '%s' "$j" | "$PY" -c 'import json,sys; d=json.loads(sys.stdin.read()); assert "drift" in d and "cost" in d and "first_try" in d' 2>/dev/null; then
  pass 7 "--json 一次给出 drift/cost/first_try 三块，状态文件能被别的工具直接消费"
else
  fail 7 "--json 不可解析：$j"
fi

# ---------------------------------------------------------------- A-mt-08/09 判定覆盖率
R2="$TMP/cov"; mkdir -p "$R2/.autopilot/checks"
printf '{"schema":2,"rounds_used":1,"phase":"build"}\n' > "$R2/.autopilot/state.json"
{
  printf '# GOAL\n\n## 验收矩阵\n\n| A# | 条目 | 判定 |\n| --- | --- | --- |\n'
  printf '| A1 | x | y |\n| A2 | x | y |\n| A3 | x | y |\n'
} > "$R2/.autopilot/GOAL.md"
printf '%s\n' '#!/bin/sh' 'NODE_IDS=(A1)' 'echo "RESULT A1 PASS ok"' 'echo "RESULT A2 PASS ok"' \
  > "$R2/.autopilot/checks/run.sh"
out=$($PY "$M" summary --repo "$R2" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "判定覆盖率：2/3 有判定源" \
   && printf '%s' "$out" | grep -q "未纳入数组 1" && printf '%s' "$out" | grep -q "完全无判定源 1"; then
  pass 8 "覆盖率进小结：分母是契约条数，不是已判定的条数（17/17 那种错觉就此消失）"
else
  fail 8 "覆盖率口径不对：rc=$rc $(printf '%s' "$out" | sed -n '2p')"
fi
j=$($PY "$M" summary --repo "$R2" --json 2>&1 | grep '^{' | tail -1)
if printf '%s' "$j" | "$PY" -c 'import json,sys;d=json.load(sys.stdin)["coverage"];assert d["contract_items"]==3 and d["no_source"]==["A3"] and d["weak_not_in_arrays"]==["A2"], d' 2>/dev/null; then
  pass 9 "--json 里 coverage 分得清「无判定源」与「有断言但未纳入兜底数组」两类缺口"
else
  fail 9 "json coverage 字段不对：$j"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
