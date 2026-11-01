#!/bin/sh
# H22 起步档位与英文文档自测：A-pz-01..05。在 mktemp -d 的假仓库里跑 init.sh，不碰真项目。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL=$(cd "$HERE/.." && pwd)

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

# ---------------------------------------------------------------- 1 三档都在，且写得可判定

missing=""
for p in quickfix feature longrun; do
    f="$SKILL/templates/presets/$p.md"
    if [ ! -s "$f" ]; then missing="$missing $p(缺文件)"; continue; fi
    grep -q "RESULT" "$f" || missing="$missing $p(无 RESULT 口径)"
    grep -q "非目标" "$f" || missing="$missing $p(无非目标)"
    grep -q "盲区" "$f" || missing="$missing $p(无盲区清单)"
done
if [ -z "$missing" ]; then
  pass 1 "三档范式齐备，且都带 RESULT 判定口径 / 非目标 / 盲区清单"
else
  fail 1 "范式不合格：$missing"
fi

# ---------------------------------------------------------------- 2 关闭态：不带 --preset 字节不变

mk_repo() { d="$1"; mkdir -p "$d"; (cd "$d" && git init -q && printf 'x\n' > a.md && git add -A && git -c user.name=t -c user.email=t@t commit -qm base); }

REPO_A="$TMP/a"; REPO_B="$TMP/b"; REPO_C="$TMP/c"
mk_repo "$REPO_A"; mk_repo "$REPO_B"; mk_repo "$REPO_C"
bash "$SKILL/scripts/init.sh" --goal "做 X" --repo "$REPO_A" --host generic-cli >"$TMP/ia.log" 2>&1 || true
bash "$SKILL/scripts/init.sh" --goal "做 X" --repo "$REPO_B" --host generic-cli --preset quickfix >"$TMP/ib.log" 2>&1 || true
out=$(bash "$SKILL/scripts/init.sh" --goal "做 X" --repo "$REPO_C" --host generic-cli --preset nosuchtier 2>&1); rc=$?
if [ -f "$REPO_A/.autopilot/GOAL.md" ] && [ -f "$REPO_B/.autopilot/GOAL.md" ]; then
  base_len=$(wc -c < "$REPO_A/.autopilot/GOAL.md" | tr -d ' ')
  # 两次 init 之间只有生成的时间戳会变（同长度），比对前把 ISO 戳归一掉
  norm() { sed -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\+00:00)?/TS/g' "$1"; }
  norm "$REPO_A/.autopilot/GOAL.md" > "$TMP/a.norm"
  head -c "$base_len" "$REPO_B/.autopilot/GOAL.md" > "$TMP/b-prefix"
  norm "$TMP/b-prefix" > "$TMP/b-prefix.norm"
  pre_len=$(wc -c < "$REPO_B/.autopilot/GOAL.md" | tr -d ' ')
  if [ "$pre_len" -gt "$base_len" ] && cmp -s "$TMP/b-prefix.norm" "$TMP/a.norm" \
     && grep -q "preset=quickfix" "$REPO_B/.autopilot/GOAL.md"; then
    pass 2 "--preset 只追加范式：GOAL.md 前半段与不带该参数时逐字节一致"
  else
    fail 2 "追加破坏了原渲染结果：base=$base_len preset=$pre_len"
  fi
else
  fail 2 "init.sh 没生成 GOAL.md（看 $TMP/ia.log）"
fi

# ---------------------------------------------------------------- 3 非法档位名要拦住

if [ "$rc" = 2 ] && printf '%s' "$out" | grep -q "quickfix | feature | longrun"; then
  pass 3 "写错的 --preset 退 2 并列出可选值，不会静默生成半份契约"
else
  fail 3 "非法档位没拦住：rc=$rc $out"
fi

# ---------------------------------------------------------------- 4 追加块不留占位符

res_a=$(grep -oE '\{\{[A-Z_]+\}\}' "$REPO_A/.autopilot/GOAL.md" | sort -u | tr '\n' ' ')
res_b=$(grep -oE '\{\{[A-Z_]+\}\}' "$REPO_B/.autopilot/GOAL.md" | sort -u | tr '\n' ' ')
if [ -z "$res_a" ] && [ -z "$res_b" ]; then
  pass 4 "生成的 GOAL.md 里没有残留 {{...}} 占位符（含不带 --preset 的默认路径）"
else
  fail 4 "占位符没被替换：默认路径[$res_a] preset路径[$res_b]"
fi

# ---------------------------------------------------------------- 5 英文入口文档不自曝本机信息

EN="$SKILL/dist/README.en.md"
if [ -s "$EN" ] && ! grep -q '/Users/' "$EN" && ! grep -q '~/\.' "$EN" \
   && grep -q 'freeze' "$EN" && grep -q 'RESULT' "$EN"; then
  pass 5 "英文 README 在位，含冻结/RESULT 口径，且不含本机绝对路径与家目录写法"
else
  fail 5 "英文 README 缺项或泄漏本机路径"
fi

# ---------------------------------------------------------------- 6 模板里每个占位符都得有人替换

unhandled=""
for k in $(grep -oE '\{\{[A-Z_]+\}\}' "$SKILL/templates/GOAL.md" | sort -u | tr -d '{}'); do
    grep -q "\"{{$k}}\"" "$SKILL/scripts/init.sh" || unhandled="$unhandled $k"
done
if [ -z "$unhandled" ]; then
  pass 6 "GOAL 模板里出现的每个 {{占位符}} 都在 init.sh 的替换表里有对应项"
else
  fail 6 "这些占位符没人替换（生成的契约里会留原文）：$unhandled"
fi

# ---------------------------------------------------------------- 7 可选开关必须默认关

on_live=""
for sec in CONCURRENT TOOLBOX VERIFY_ACL SANDBOX TRIGGER; do
    v=$(awk -v sec="$sec" '
        $0 ~ "^## " sec {inside=1; next}
        inside && /^## / {inside=0}
        inside && /^enable/ {print $3; exit}' "$SKILL/templates/GOAL.md")
    case "$v" in
      ""|false) ;;
      *) on_live="$on_live $sec=$v" ;;
    esac
done
if [ -z "$on_live" ]; then
  pass 7 "GOAL 模板里五个可选开关段（CONCURRENT/TOOLBOX/VERIFY_ACL/SANDBOX/TRIGGER）的 enable 全是 false —— 新特性不得默认开"
else
  fail 7 "这些开关在模板里默认就开着（违反『默认关 + 关闭态逐字节等价』）：$on_live"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
