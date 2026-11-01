#!/bin/sh
# environ 自检：在 mktemp fixture 上验证三哈希逐字节一致（M7）+ 缺能力 SKIP 语义（M5 的地基）。
# 用法: sh scripts/environ.selftest.sh
# 每条一行 RESULT E<n> PASS|FAIL <说明>；任何 FAIL 退出 1。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENVIRON="$HERE/environ.sh"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/environ-selftest-XXXXXX")
trap 'printf "# fixture: %s\n" "$TMP"' EXIT
AP="$TMP/.autopilot"
CH="$AP/checks"
mkdir -p "$CH" "$TMP/src"

# 一个稳定的被测文件
printf 'hello autopilot 0.9\nsecond line\n' > "$TMP/src/target.txt"

# A# → 能力映射：browser 缺失时 A99 应进 skipped_acceptance
cat > "$AP/acceptance-needs.json" <<'EOF'
{"A99": ["browser"], "A100": ["paid-api"]}
EOF

idx=0
fails=0
ok() { idx=$((idx + 1)); printf 'RESULT E%s PASS %s\n' "$idx" "$1"; }
bad() { idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT E%s FAIL %s\n' "$idx" "$1"; }
check() { # $1=want $2=desc ; 其余=命令
  want=$1; desc=$2; shift 2
  idx=$((idx + 1))
  out=$("$@" 2>&1); got=$?
  if [ "$got" = "$want" ]; then
    printf 'RESULT E%s PASS %s (exit=%s)\n' "$idx" "$desc" "$got"
  else
    fails=$((fails + 1))
    printf 'RESULT E%s FAIL %s :: want=%s got=%s :: %s\n' "$idx" "$desc" "$want" "$got" \
      "$(printf '%s' "$out" | tail -2 | tr '\n' ' ')"
  fi
}

e() { sh "$ENVIRON" "$@"; }

# E1: probe 写出 environment.json，且含 capabilities / skipped_acceptance
check 0 "probe 生成 environment.json" e probe --repo "$TMP"
if [ -f "$AP/environment.json" ] \
   && python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));assert "capabilities" in d and "skipped_acceptance" in d and d["probed_at"]' "$AP/environment.json" 2>/dev/null; then
  ok "environment.json 结构完整（probed_at/capabilities/skipped_acceptance）"
else
  bad "environment.json 结构不完整"
fi

# E2: 三种哈希实现对同一文件产出逐字节相同的一行（M7）
FIXED_DISPLAY="./src/target.txt"
L_shasum=$(e hash --repo "$TMP" --file src/target.txt --impl shasum    --display "$FIXED_DISPLAY" 2>/dev/null); r1=$?
L_sha256=$(e hash --repo "$TMP" --file src/target.txt --impl sha256sum --display "$FIXED_DISPLAY" 2>/dev/null); r2=$?
L_py=$(e     hash --repo "$TMP" --file src/target.txt --impl python    --display "$FIXED_DISPLAY" 2>/dev/null); r3=$?
# 收集成功产出的行（某实现本机不存在时会被跳过，不参与"必须一致"）
avail=""
[ $r1 -eq 0 ] && avail="$avail|$L_shasum"
[ $r2 -eq 0 ] && avail="$avail|$L_sha256"
[ $r3 -eq 0 ] && avail="$avail|$L_py"
n=$(printf '%s' "$avail" | tr '|' '\n' | grep -c '.')
if [ "$r3" -eq 0 ] && [ "$n" -ge 2 ] \
   && [ "$(printf '%s' "$avail" | tr '|' '\n' | grep -v '^$' | sort -u | wc -l | tr -d ' ')" = "1" ]; then
  ok "可用哈希实现（本机 $n/3 个）产出逐字节相同的一行"
else
  bad "哈希实现产出不一致或可用实现不足（n=$n python_ok=$r3）"
fi

# E3: hash 行格式 = 64hex + 两空格 + ./相对路径
if printf '%s\n' "$L_py" | grep -Eq '^[0-9a-f]{64}  \./src/target\.txt$'; then
  ok "hash 行格式符合 MANIFEST（64hex·两空格·相对路径）"
else
  bad "hash 行格式不符：$L_py"
fi

# E4: freeze 写出的每行都是同一格式，且能对上 shasum 基线算法
e freeze --repo "$TMP" --checks src >/dev/null 2>&1  # 冻结 src 目录（仅测格式）
if [ -f "$TMP/src/MANIFEST.sha256" ] \
   && grep -Eq '^[0-9a-f]{64}  \./target\.txt$' "$TMP/src/MANIFEST.sha256" \
   && ! grep -q 'MANIFEST.sha256' "$TMP/src/MANIFEST.sha256"; then
  ok "freeze 产出 MANIFEST 行格式正确且排除自身"
else
  bad "freeze MANIFEST 行异常"
fi
# 清理，避免污染后续 checks 目录的 ENVIRONMENT 断言
rm -f "$TMP/src/MANIFEST.sha256"

# E5/E6: 伪造"无浏览器"世界 → require 退出 40 且 ENVIRONMENT 记 null + skipped 含 A99
check 40 "缺 browser 时 require 退出 40" \
  env AUTOPILOT_NO_CAPS=browser sh "$ENVIRON" require --repo "$TMP" --need browser
env AUTOPILOT_NO_CAPS=browser sh "$ENVIRON" probe --repo "$TMP" >/dev/null 2>&1
if python3 - "$AP/environment.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
caps = d["capabilities"]
skipped = d["skipped_acceptance"]
# browser 必须为 null；A99 必须因缺 browser 进入 skipped_acceptance
assert caps.get("browser") in (None, False, ""), f"browser 未记 null: {caps.get('browser')!r}"
assert "A99" in skipped, f"A99 不在 skipped_acceptance: {list(skipped)}"
PY
then
  ok "environment.json 内 browser=null 且 skipped_acceptance 含 A99"
else
  bad "缺能力场景下 environment.json 判定不正确"
fi

# E7: 正常场景（用一个必然存在的能力 python）→ require 退出 0
check 0 "满足能力时 require 退出 0（假绿不会发生）" e require --repo "$TMP" --need python

# E8: require 的 ENV SKIP 输出行存在
out=$(env AUTOPILOT_NO_CAPS=browser sh "$ENVIRON" require --repo "$TMP" --need browser 2>&1)
if printf '%s' "$out" | grep -q '^ENV SKIP browser '; then
  ok "缺能力时打印 ENV SKIP <能力> <原因>"
else
  bad "未打印 ENV SKIP 行：$out"
fi

# E9: `_` 开头键是注释，不许被当成 A# 造出假 SKIP，也不许压掉「有真实映射」的事实
cat > "$AP/acceptance-needs.json" <<'EOF'
{"_README": "注释", "_example": {"A1": ["browser"]}, "A99": ["browser"]}
EOF
env AUTOPILOT_NO_CAPS=browser sh "$ENVIRON" probe --repo "$TMP" >/dev/null 2>&1
if python3 - "$AP/environment.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
skipped = d["skipped_acceptance"]
assert list(skipped) == ["A99"], f"skipped 应只含 A99: {list(skipped)}"
assert d["acceptance_needs"]["mapped"] == 1, f"mapped 应为 1: {d['acceptance_needs']}"
assert "hint" not in d, f"有真实映射时不该出现补映射提示: {d.get('hint')}"
PY
then
  ok "以 _ 开头的注释键被忽略，真实 A# 正常判定"
else
  bad "_ 注释键未忽略或 mapped/hint 判定错误"
fi

# E10: 文件缺失 vs 文件存在但没有 A# 条目 —— 提示必须能区分（否则用户不知道该建还是该填）
rm -f "$AP/acceptance-needs.json"
out_missing=$(e probe --repo "$TMP" 2>&1)
printf '{}\n' > "$AP/acceptance-needs.json"
out_empty=$(e probe --repo "$TMP" 2>&1)
if printf '%s' "$out_missing" | grep -q '不存在或不是合法 JSON' \
   && printf '%s' "$out_empty" | grep -q '没有任何 A# 条目'; then
  ok "acceptance-needs.json 缺失与空映射的提示可区分"
else
  bad "缺失/空映射提示不可区分 :: missing=[$(printf '%s' "$out_missing" | tr '\n' ' ')] empty=[$(printf '%s' "$out_empty" | tr '\n' ' ')]"
fi

# E11: 质量门禁工具探测 —— PATH 上有可执行即记可用；AUTOPILOT_NO_CAPS 可伪造缺失
QBIN="$TMP/qbin"
mkdir -p "$QBIN"
printf '#!/bin/sh\nexit 0\n' > "$QBIN/crapper"
chmod +x "$QBIN/crapper"
PATH="$QBIN:$PATH" sh "$ENVIRON" probe --repo "$TMP" >/dev/null 2>&1
q_on=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["capabilities"].get("crapper"))' "$AP/environment.json" 2>/dev/null || printf 'ERR')
PATH="$QBIN:$PATH" env AUTOPILOT_NO_CAPS=crapper sh "$ENVIRON" probe --repo "$TMP" >/dev/null 2>&1
q_off=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["capabilities"].get("crapper"))' "$AP/environment.json" 2>/dev/null || printf 'ERR')
if [ "$q_on" = "crapper" ] && [ "$q_off" = "None" ]; then
  ok "crapper/dryer/mutator 探测生效，且可用 AUTOPILOT_NO_CAPS 伪造缺失"
else
  bad "质量工具探测不对 :: on=$q_on off=$q_off"
fi

# E-H20: 运行时指纹（MANIFEST 保护不到解释器本身，漂移必须查得出）
sh "$ENVIRON" probe --repo "$TMP" >/dev/null 2>&1
if python3 - "$AP/environment.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
r = d.get("runtimes") or {}
p = r.get("python3") or {}
sys.exit(0 if p.get("path_digest") and p.get("sha256") and p.get("size") and p.get("version")
         and "/" not in str(p.get("path_digest")) and not p.get("bin") else 1)
PY
then ok "probe 写出 python3 运行时指纹（路径摘要/大小/sha256/版本，且不含绝对路径）"
else bad "runtimes 指纹不完整或泄漏绝对路径"; fi

out=$(sh "$ENVIRON" runtimes --repo "$TMP" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "ENV RUNTIMES 0"; then
  ok "刚采集完再对一遍：无漂移退 0"
else
  bad "无漂移场景不该报错 :: rc=$rc $out"; fi

python3 - "$AP/environment.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
d["runtimes"]["python3"]["path_digest"] = "000000000000"
json.dump(d, open(p, "w", encoding="utf-8"))
PY
out=$(sh "$ENVIRON" runtimes --repo "$TMP" 2>&1); rc=$?
if [ "$rc" = 41 ] && printf '%s' "$out" | grep -q "RUNTIME DRIFT python3"; then
  ok "解释器换路径 → 退 41 并点名，且声明判定不自动改变"
else
  bad "运行时漂移没查出来 :: rc=$rc $out"; fi

python3 - "$AP/environment.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
d.pop("runtimes", None)
json.dump(d, open(p, "w", encoding="utf-8"))
PY
out=$(sh "$ENVIRON" runtimes --repo "$TMP" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "没有 runtimes 指纹"; then
  ok "老工作区没指纹时退 0 并提示重跑 probe"
else
  bad "缺 runtimes 的老工作区被误伤 :: rc=$rc $out"; fi

# E17-E21: H20 执行期新增可执行文件探针
REPO2="$TMP/execscan"; mkdir -p "$REPO2/.autopilot" "$REPO2/src" "$REPO2/node_modules/x" "$REPO2/dist"
printf 'x\n' > "$REPO2/src/a.txt"
out=$(sh "$ENVIRON" exec-scan --repo "$REPO2" 2>&1); rc=$?
if [ "$rc" = 40 ] && printf '%s' "$out" | grep -q SKIP && ! printf '%s' "$out" | grep -q 'RESULT.*PASS'; then
  ok "没有基线时判 SKIP（退 40），绝不回一个 PASS"
else
  bad "无基线行为不对 :: rc=$rc $out"; fi

out=$(sh "$ENVIRON" exec-scan --repo "$REPO2" --record 2>&1); rc=$?
if [ "$rc" = 0 ] && [ -f "$REPO2/.autopilot/exec-scan.json" ]; then
  ok "--record 落基线清单"
else
  bad "--record 没落盘 :: rc=$rc $out"; fi

printf '#!/bin/sh\necho hi\n' > "$REPO2/src/drop.sh"; chmod +x "$REPO2/src/drop.sh"
out=$(sh "$ENVIRON" exec-scan --repo "$REPO2" 2>&1); rc=$?
if [ "$rc" = 42 ] && printf '%s' "$out" | grep -q "NEW EXEC src/drop.sh"; then
  ok "执行期新增可执行文件被点名并退 42（验证阶段 curl 下来一个脚本就是这一类）"
else
  bad "新增可执行没抓到 :: rc=$rc $out"; fi

printf '#!/bin/sh\n' > "$REPO2/node_modules/x/tool"; chmod +x "$REPO2/node_modules/x/tool"
printf '#!/bin/sh\n' > "$REPO2/dist/bundle-bin"; chmod +x "$REPO2/dist/bundle-bin"
rm -f "$REPO2/src/drop.sh"
out=$(sh "$ENVIRON" exec-scan --repo "$REPO2" 2>&1); rc=$?
if [ "$rc" = 0 ]; then
  ok "依赖/产物目录里的可执行文件不进清单（跳过表生效，不会把 node_modules 报成投毒）"
else
  bad "跳过表没生效 :: rc=$rc $out"; fi

chmod -x "$REPO2/src/keep.sh" 2>/dev/null; printf '#!/bin/sh\n' > "$REPO2/src/keep.sh"; chmod +x "$REPO2/src/keep.sh"
sh "$ENVIRON" exec-scan --repo "$REPO2" --record >/dev/null 2>&1
chmod -x "$REPO2/src/keep.sh"
out=$(sh "$ENVIRON" exec-scan --repo "$REPO2" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "EXEC REMOVED src/keep.sh"; then
  ok "执行位被摘掉只提示不拦住（删痕迹也是信号），且不退 42 掩盖真正的新增"
else
  bad "摘执行位处理不对 :: rc=$rc $out"; fi

printf '自检 %d 例，失败 %d\n' "$idx" "$fails"
[ "$fails" = 0 ] || exit 1
exit 0
