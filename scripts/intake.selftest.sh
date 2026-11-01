#!/bin/sh
# H39 lite 档自测：A-in-01..12。全程在 mktemp -d 的假仓库里跑，绝不碰真项目与真技能目录。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL=$(cd "$HERE/.." && pwd)
IN="$SKILL/scripts/intake.py"
PY=${PYTHON:-python3}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

# 假 npm：探测会把它写进矩阵，但自测从不执行 run.sh 里的 npm 行（除第 4 组用无探测仓库）
mkdir -p "$TMP/bin"
printf '#!/bin/sh\nexit 0\n' > "$TMP/bin/npm"
chmod +x "$TMP/bin/npm"
PATH="$TMP/bin:$PATH"
export PATH

section() { sed -n "/^## $2\$/,/^## /p" "$1"; }
mk_plain() { d="$1"; mkdir -p "$d/src"; printf 'x = 1\n' > "$d/src/main.py"; printf '# t\n' > "$d/README.md"; }
runsh_of() { grep -n '^check "A' "$1" | tail -1 | cut -d: -f1; }

# ---------------------------------------------------------------- 1 关闭态：不带 --lite 没有任何 lite 痕迹

A="$TMP/a"; mk_plain "$A"
bash "$SKILL/scripts/init.sh" --goal "做一个 index.html" --repo "$A" --host generic-cli >"$TMP/a.log" 2>&1 || true
if [ -f "$A/.autopilot/GOAL.md" ] && [ ! -f "$A/.autopilot/intake.json" ] \
   && ! grep -q '"profile"' "$A/.autopilot/state.json" \
   && grep -q '可观察的行为' "$A/.autopilot/GOAL.md" \
   && cmp -s "$A/.autopilot/checks/run.sh" "$SKILL/templates/checks/run.sh.example"; then
  pass 1 "不带 --lite：无 intake.json、state 无 profile、矩阵仍是模板占位行、run.sh 就是那份样板"
else
  fail 1 "lite 漏进了默认路径：$(ls "$A/.autopilot" | tr '\n' ' ')"
fi

# ---------------------------------------------------------------- 2 开启态：只动矩阵，其余小节一字不改

B="$TMP/b"; mk_plain "$B"
bash "$SKILL/scripts/init.sh" --goal "做一个 index.html" --lite --repo "$B" --host generic-cli >"$TMP/b.log" 2>&1 || true
ok=1
[ -f "$B/.autopilot/intake.json" ] || ok=0
grep -q '"profile": "lite"' "$B/.autopilot/state.json" || ok=0
section "$B/.autopilot/GOAL.md" "验收矩阵" | grep -q '| A1 |' || ok=0
for s in 非目标 边界 停止条件 假设; do
  section "$A/.autopilot/GOAL.md" "$s" > "$TMP/sec.a"
  section "$B/.autopilot/GOAL.md" "$s" > "$TMP/sec.b"
  cmp -s "$TMP/sec.a" "$TMP/sec.b" || ok=0
done
if [ "$ok" = 1 ]; then
  pass 2 "--lite 只替换验收矩阵 + 追加 lite 声明：非目标/边界/停止条件/假设与关闭态逐字节相同"
else
  fail 2 "lite 改坏了契约结构（看 $TMP/b.log）"
fi

# ---------------------------------------------------------------- 3 没有 GOAL.md 时不另立契约格式

out=$($PY "$IN" draft --repo "$TMP/nope" --goal "让首页更快打开" 2>&1); rc=$?
if [ "$rc" = 2 ] && printf '%s' "$out" | grep -q "lite 的入口是"; then
  pass 3 "目录里没有 GOAL.md 时退 2 并指回 init.sh --lite（不在这里复制第二套契约模板）"
else
  fail 3 "该退 2 指回入口，实得 rc=$rc：$out"
fi

# ---------------------------------------------------------------- 4 探测不到 → 全 SKIP，绝不冒 PASS

C="$TMP/c"; mkdir -p "$C"; printf 'x = 1\n' > "$C/app.py"
bash "$SKILL/scripts/init.sh" --goal "让首页更快打开" --lite --repo "$C" --host generic-cli >"$TMP/c.log" 2>&1 || true
out=$(sh "$C/.autopilot/checks/run.sh" 2>&1); rc=$?
n_res=$(printf '%s\n' "$out" | grep -c '^RESULT ')
n_skip=$(printf '%s\n' "$out" | grep -c '^RESULT A[0-9]* SKIP')
if [ "$n_res" -gt 0 ] && [ "$n_res" = "$n_skip" ] \
   && ! printf '%s\n' "$out" | grep -q ' PASS ' \
   && printf '%s\n' "$out" | grep -q '待人工确认'; then
  pass 4a "探测不到判定手段：$n_res 条全判 SKIP 并写明原因，一条 PASS 都不许冒"
else
  fail 4a "探测不到却粉饰：res=$n_res skip=$n_skip rc=$rc"
fi
out=$(bash "$SKILL/scripts/check.sh" freeze "$C" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s\n' "$out" | grep -q "COVERAGE 0"; then
  pass 4b "自动起草的矩阵每条都有发射位点，冻结前的 H38 覆盖闸门直接通过"
else
  fail 4b "起草的矩阵过不了冻结：rc=$rc $(printf '%s\n' "$out" | tail -2)"
fi
out=$(bash "$SKILL/scripts/check.sh" run "$C" 2>&1); rc=$?
if [ "$rc" = 1 ] && printf '%s\n' "$out" | grep -q "0 通过" \
   && printf '%s\n' "$out" | grep -q "没有任何一条真 PASS"; then
  pass 4c "0 条真 PASS 时 check.sh run 退 1 并明写「本轮未完成」——lite 不能把全 SKIP 报成全绿"
else
  fail 4c "全 SKIP 仍像成功：rc=$rc $(printf '%s\n' "$out" | tail -2)"
fi

# ---------------------------------------------------------------- 5 只引用真实存在的命令

D="$TMP/d"; mkdir -p "$D"; printf '<html>hi</html>\n' > "$D/index.html"
printf '{"name":"d","scripts":{"test":"node -e 0"}}\n' > "$D/package.json"
bash "$SKILL/scripts/init.sh" --goal "做一个 index.html" --lite --repo "$D" --host generic-cli >"$TMP/d.log" 2>&1 || true
matrix=$(section "$D/.autopilot/GOAL.md" "验收矩阵")
if printf '%s\n' "$matrix" | grep -q 'npm run test' && printf '%s\n' "$matrix" | grep -q 'test -s index.html' \
   && ! printf '%s\n' "$matrix" | grep -q 'pytest'; then
  pass 5 "矩阵里只出现探测到的 npm run test 与 test -s index.html；没有 pytest 配置就不提 pytest"
else
  fail 5 "探测不干净：$(printf '%s\n' "$matrix" | tr '\n' ' ')"
fi

# ---------------------------------------------------------------- 6 每条标来源，推断出来的一律待确认

$PY - "$D/.autopilot/intake.json" >"$TMP/6.out" 2>&1 <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
want = sorted(m["a"] for m in d["matrix"] if m["source"] != "user")
got = sorted(d["needs_human_confirm"])
user = [m["a"] for m in d["matrix"] if m["source"] == "user"]
assert want == got and want, "needs_human_confirm 与来源标注不一致：%s / %s" % (want, got)
assert user, "用户原话点名的交付物没标成 user"
assert all(m["source"] in ("user", "probed", "template") for m in d["matrix"]), "出现了没定义过的来源"
print("ok")
PY
if [ $? -eq 0 ]; then
  pass 6 "intake.json 的 needs_human_confirm 恰好等于全部非原话条目；原话交付物单独标 source=user"
else
  fail 6 "来源标注与待确认清单对不上：$(cat "$TMP/6.out")"
fi

# ---------------------------------------------------------------- 7 复核：两类错位都退 24

out=$($PY "$IN" check --repo "$D" 2>&1); rc0=$?
cp "$D/.autopilot/checks/run.sh" "$TMP/run.keep"
ln=$(runsh_of "$D/.autopilot/checks/run.sh")
sed "${ln}d" "$TMP/run.keep" > "$D/.autopilot/checks/run.sh"
out=$($PY "$IN" check --repo "$D" 2>&1); rc1=$?
printf '%s\n' "$out" | grep -q '无发射位点' || true
cp "$TMP/run.keep" "$D/.autopilot/checks/run.sh"
sed 's/^| A1 |/| A99 |/' "$D/.autopilot/GOAL.md" > "$D/.autopilot/GOAL.md.x"
mv "$D/.autopilot/GOAL.md.x" "$D/.autopilot/GOAL.md"
out=$($PY "$IN" check --repo "$D" 2>&1); rc2=$?
if [ "$rc0" = 0 ] && [ "$rc1" = 24 ] && [ "$rc2" = 24 ]; then
  pass 7 "复核对两类错位都退 24：契约有条目而 run.sh 没位点 / 有位点而契约没这条（一致时退 0）"
else
  fail 7 "复核没拦住错位：rc0=$rc0 rc1=$rc1 rc2=$rc2"
fi

# ---------------------------------------------------------------- 8 人写的契约绝不覆盖

E="$TMP/e"; mk_plain "$E"
bash "$SKILL/scripts/init.sh" --goal "做一个 index.html" --repo "$E" --host generic-cli >/dev/null 2>&1 || true
$PY - "$E/.autopilot/GOAL.md" <<'PY'
import io, sys
p = sys.argv[1]
s = io.open(p, encoding="utf-8").read()
assert "| A1 | <!-- 可观察的行为 -->" in s, "模板矩阵形态变了，这条用例的前提不成立"
s = s.replace("| A1 | <!-- 可观察的行为 -->", "| A1 | 人写的验收项 | `test -e a` | exit=0 | 待验 |")
io.open(p, "w", encoding="utf-8").write(s)
PY
before=$(shasum -a 256 "$E/.autopilot/GOAL.md" | cut -d' ' -f1)
out=$($PY "$IN" draft --repo "$E" --goal "随便做个东西" 2>&1); rc=$?
after=$(shasum -a 256 "$E/.autopilot/GOAL.md" | cut -d' ' -f1)
if [ "$rc" = 23 ] && [ "$before" = "$after" ] && printf '%s\n' "$out" | grep -q "不覆盖"; then
  pass 8a "矩阵里有人写的验收行时退 23，GOAL.md 一字未动"
else
  fail 8a "把人写的契约覆盖了：rc=$rc 未变=$([ "$before" = "$after" ] && printf yes || printf no)"
fi
printf '#!/bin/sh\necho "人工维护的验收脚本"\n' > "$E/.autopilot/checks/run.sh"
out=$($PY "$IN" draft --repo "$E" --goal "随便做个东西" 2>&1); rc=$?
if [ "$rc" = 23 ] && grep -q "人工维护的验收脚本" "$E/.autopilot/checks/run.sh"; then
  pass 8b "人写的 run.sh 同样退 23 不被覆盖"
else
  fail 8b "人写的 run.sh 被改了：rc=$rc"
fi
out=$($PY "$IN" draft --repo "$E" --goal "随便做个东西" --force 2>&1); rc=$?
if [ "$rc" = 0 ] && grep -q "由 intake.py 自动起草" "$E/.autopilot/checks/run.sh"; then
  pass 8c "只有 --force 才重写，且 --force 走的是同一条起草通路"
else
  fail 8c "--force 不通：rc=$rc $out"
fi

# ---------------------------------------------------------------- 9 一屏结论页：不许写「做完了」

F="$TMP/f"; mkdir -p "$F"
bash "$SKILL/scripts/init.sh" --goal "让页面更快" --lite --repo "$F" --host generic-cli >/dev/null 2>&1 || true
$PY - "$F/.autopilot/checks/last-result.json" <<'PY'
import json, os, sys
p = sys.argv[1]
ids = [m["a"] for m in json.load(open(os.path.join(os.path.dirname(os.path.dirname(p)), "intake.json"),
                                      encoding="utf-8"))["matrix"]]
doc = {"exit": 0, "passed": [], "failed": [], "skipped": list(ids),
       "results": [{"id": a, "status": "SKIP", "note": "自动起草时探测不到判定手段"} for a in ids]}
json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False)
PY
out=$($PY "$IN" brief --repo "$F" 2>&1); rc=$?
if [ "$rc" = 0 ] \
   && printf '%s\n' "$out" | grep -q "我按下面这些标准判的，觉得不对你说" \
   && printf '%s\n' "$out" | grep -q "没有任何一条真 PASS" \
   && printf '%s\n' "$out" | grep -q "待你确认" \
   && ! printf '%s\n' "$out" | grep -q "全绿"; then
  pass 9a "结论页第一句就是那句声明；全 SKIP 时明写未完成、逐条标来源与待确认，且不出现「全绿」字样"
else
  fail 9a "结论页不诚实：rc=$rc $(printf '%s\n' "$out" | head -2)"
fi
$PY - "$F/.autopilot/checks/last-result.json" "$F/.autopilot/intake.json" <<'PY'
import json, sys
rp, ip = sys.argv[1], sys.argv[2]
d = json.load(open(rp, encoding="utf-8"))
ids = [m["a"] for m in json.load(open(ip, encoding="utf-8"))["matrix"]]
d["passed"] = ids[:1]
d["skipped"] = ids[1:]
d["results"] = [{"id": a, "status": "PASS" if a in d["passed"] else "SKIP", "note": ""} for a in ids]
json.dump(d, open(rp, "w", encoding="utf-8"), ensure_ascii=False)
PY
out=$($PY "$IN" brief --repo "$F" 2>&1)
n=$(printf '%s\n' "$out" | grep -c '待你确认')
if printf '%s\n' "$out" | grep -q "存在 FAIL/SKIP，不得写「验收全绿」" && [ "$n" -ge 1 ]; then
  pass 9b "混合结果时结论页逐条列出待确认项，并顶住「验收全绿」这个措辞"
else
  fail 9b "混合结果措辞不对：$(printf '%s\n' "$out" | tail -2)"
fi

# ---------------------------------------------------------------- 10 可重放：同输入同产物逐字节

G="$TMP/g"; mkdir -p "$G"; printf '<html>hi</html>\n' > "$G/index.html"
bash "$SKILL/scripts/init.sh" --goal "做一个 index.html" --lite --repo "$G" --host generic-cli >/dev/null 2>&1 || true
cp "$G/.autopilot/intake.json" "$TMP/g1.json"
cp "$G/.autopilot/checks/run.sh" "$TMP/g1.sh"
cp "$G/.autopilot/GOAL.md" "$TMP/g1.md"
$PY "$IN" draft --repo "$G" --goal "做一个 index.html" --force >/dev/null 2>&1 || true
if cmp -s "$TMP/g1.json" "$G/.autopilot/intake.json" && cmp -s "$TMP/g1.sh" "$G/.autopilot/checks/run.sh" \
   && cmp -s "$TMP/g1.md" "$G/.autopilot/GOAL.md"; then
  pass 10 "同一句话连起草两次，intake.json / run.sh / GOAL.md 逐字节相同（无时间戳，lite 声明不叠第二份）"
else
  fail 10 "起草不可重放"
fi

# ---------------------------------------------------------------- 11 一句话里的引号不能打破 run.sh

H="$TMP/h"; mkdir -p "$H"; printf '<html>hi</html>\n' > "$H/index.html"
bash "$SKILL/scripts/init.sh" --goal '做一个 index.html 的"落地"页' --lite --repo "$H" --host generic-cli >/dev/null 2>&1 || true
if sh -n "$H/.autopilot/checks/run.sh" 2>/dev/null; then
  pass 11 "用户原话里带双引号，起草出来的 run.sh 仍是合法 shell（描述文本已消毒）"
else
  fail 11 "一句话里的双引号打破了生成的 run.sh"
fi

# ---------------------------------------------------------------- 12 不覆盖规则也保护 --probe-only 的产物

I="$TMP/i"; mk_plain "$I"
bash "$SKILL/scripts/init.sh" --goal "做一个 index.html" --lite --repo "$I" --host generic-cli >/dev/null 2>&1 || true
out=$(bash "$SKILL/scripts/init.sh" --goal "做一个 index.html" --lite --probe-only --repo "$I" 2>&1); rc=$?
if [ "$rc" = 2 ] && printf '%s\n' "$out" | grep -q "互斥"; then
  pass 12 "--lite 与 --probe-only 互斥：重探环境绝不重写已冻结的契约"
else
  fail 12 "互斥没拦住：rc=$rc $out"
fi

# ---------------------------------------------------------------- 13 轮提示里带上一屏结论页的要求

rp() { bash "$SKILL/scripts/round_prompt.sh" "$1" 2>&1; }
out_lite=$(rp "$B")
out_off=$(rp "$A")
if printf '%s\n' "$out_lite" | grep -q "intake.py brief" \
   && printf '%s\n' "$out_lite" | grep -q "我按下面这些标准判的" \
   && ! printf '%s\n' "$out_off" | grep -q "intake.py brief"; then
  pass 13 "轮提示只在 lite 工作区追加结论页要求；非 lite 的提示词里没有这一段"
else
  fail 13 "lite 段没接进轮提示：lite=$(printf '%s\n' "$out_lite" | grep -c brief) off=$(printf '%s\n' "$out_off" | grep -c brief)"
fi

# ---------------------------------------------------------------- 14 lite 的复核与结论页不去判别人的契约

out=$($PY "$IN" check --repo "$A" 2>&1); rc1=$?
out2=$($PY "$IN" brief --repo "$A" 2>&1); rc2=$?
if [ "$rc1" = 2 ] && [ "$rc2" = 2 ] && printf '%s\n' "$out" | grep -q "status.py coverage" \
   && printf '%s\n' "$out2" | grep -q "REPORT.md" \
   && ! printf '%s\n' "$out" | grep -q "复核不通过"; then
  pass 14 "非 lite 工作区：check/brief 都退 2 并指向 H38 与 REPORT.md，不对手写契约下 lite 的结论"
else
  fail 14 "越界判了别人的契约：rc1=$rc1 rc2=$rc2 $(printf '%s\n' "$out" | head -1)"
fi

# ---------------------------------------------------------------- 15 接续包只在 lite 工作区多一行

out=$(python3 "$SKILL/scripts/resume.py" "$B" 2>&1)
out_off=$(python3 "$SKILL/scripts/resume.py" "$A" 2>&1)
if printf '%s\n' "$out" | grep -q "档位:   lite" \
   && printf '%s\n' "$out" | grep -q "intake.py brief" \
   && ! printf '%s\n' "$out_off" | grep -q "档位:"; then
  pass 15 "接续包：lite 工作区多一行「档位: lite + 收尾发 brief」，标准档的接续包里没有这行"
else
  fail 15 "接续包没接上 lite：$(printf '%s\n' "$out" | grep -c '档位') / 关闭态 $(printf '%s\n' "$out_off" | grep -c '档位')"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
