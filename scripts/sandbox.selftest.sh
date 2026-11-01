#!/bin/sh
# H13 + H27 沙箱探测与读拒绝自测：A-sb-01..08。全程在 mktemp -d 的假工作区里跑。
# 注意：$HOME 用 mktemp 的随机目录本身，不写死名字——隐私扫描按「家目录末段」匹配文件内容。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL=$(cd "$HERE/.." && pwd)
PY=${PYTHON:-python3}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM
export HOME="$TMP/home"
mkdir -p "$HOME"

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

REPO="$TMP/repo"
mkdir -p "$REPO/.autopilot/checks" "$REPO/.autopilot/rounds" "$REPO/src" "$REPO/sandbox"
SB="$SKILL/scripts/sandbox.py"
printf 'x\n' > "$REPO/.autopilot/checks/run.sh"
printf '{}\n' > "$REPO/.autopilot/rounds/r-01.json"
printf 'TOKEN=abc\n' > "$REPO/src/.env"
printf '{"schema":2,"rounds_used":1,"phase":"build"}\n' > "$REPO/.autopilot/state.json"

fp_repo() { (cd "$REPO" && find . -type f -not -name sandbox.json | LC_ALL=C sort | xargs shasum -a 256) | shasum -a 256; }

# ---------------------------------------------------------------- 1 关闭态：不探测、不写文件

out=$($PY "$SB" probe --repo "$REPO" 2>&1); rc=$?
out2=$($PY "$SB" check-read --repo "$REPO" --role builder --path "$HOME/.ssh/id_rsa" 2>&1); rc2=$?   # privacy-scan:allow 读拒绝用例本身
if [ "$rc" = 23 ] && [ "$rc2" = 23 ] && ! [ -f "$REPO/.autopilot/sandbox.json" ]; then
  pass 1 "GOAL 里没有 ## SANDBOX 时全部退 23，且不落 sandbox.json（等同没这个模块）"
else
  fail 1 "关闭态不干净：rc=$rc/$rc2 文件=$([ -f "$REPO/.autopilot/sandbox.json" ] && echo 有 || echo 无)"
fi

# ---------------------------------------------------------------- 2 启用后探测如实

cat >> "$REPO/.autopilot/GOAL.md" <<'EOF'
# GOAL — {REPO_ROOT}

## SANDBOX
enable = true
mode = auto
deny_net = true
EOF
out=$($PY "$SB" probe --repo "$REPO" 2>&1); rc=$?
mode=$(printf '%s' "$out" | sed -n 's/.*实得=\([a-z]*\).*/\1/p')
if [ "$rc" = 0 ] && [ -f "$REPO/.autopilot/sandbox.json" ] \
   && printf '%s' "$mode" | grep -qE '^(container|native|none)$'; then
  pass 2 "启用后 probe 落盘并给出实得模式（$mode），不假装隔离存在"
else
  fail 2 "探测不对：rc=$rc mode=[$mode] $out"
fi
if [ "$mode" = none ]; then
  if printf '%s' "$out" | grep -q DEGRADE; then pass 2 "无隔离时打印 DEGRADE，并指向 SKIP 口径（B3）"; else fail 2 "无隔离却没出降级声明"; fi
else
  pass 2 "本机有隔离能力（$mode）"
fi

# 把 PATH 抽干再探一次：which 什么都找不到，必须落到 none 并出降级声明（任何机器都能跑这条）。
# 解释器用绝对路径调，否则连 python3 都找不到，测的就是 shell 而不是探测逻辑。
dry=$(PATH="$TMP/emptybin" "$(command -v "$PY")" "$SB" probe --repo "$REPO" 2>&1); drc=$?
if [ "$drc" = 0 ] && printf '%s' "$dry" | grep -q "实得=none" && printf '%s' "$dry" | grep -q DEGRADE \
   && printf '%s' "$dry" | grep -q SKIP; then
  pass 2 "隔离能力被抽干时判 none 并打印降级声明（依赖隔离的条目须判 SKIP，不判 PASS）"
else
  fail 2 "none 分支不对：rc=$drc $dry"
fi

# ---------------------------------------------------------------- 3-4 读拒绝：凭据目录与穿越归一

out=$($PY "$SB" check-read --repo "$REPO" --role builder --path "$HOME/.ssh/authorized_keys" 2>&1); rc=$?   # privacy-scan:allow 读拒绝用例本身
if [ "$rc" = 24 ] && printf '%s' "$out" | grep -q "凭据/私密目录"; then
  pass 3 "读拒绝 ~/.ssh（外部沙箱默认读全开，这里显式关掉）"
else
  fail 3 "凭据目录没拦住：rc=$rc $out"
fi
out=$($PY "$SB" check-read --repo "$REPO" --role builder --path "$HOME/.ssh/../.ssh/id_rsa" 2>&1); rc=$?   # privacy-scan:allow 穿越写法用例本身
out2=$($PY "$SB" check-read --repo "$REPO" --role builder --path "$HOME/.aws/../.aws/config" 2>&1); rc2=$?
if [ "$rc" = 24 ] && [ "$rc2" = 24 ]; then
  pass 4 "用 ../ 穿越写法的凭据路径被归一后仍拦住，绕不过去"
else
  fail 4 "穿越写法漏了：rc=$rc/$rc2"
fi

# ---------------------------------------------------------------- 5 角色分档读权限

out=$($PY "$SB" check-read --repo "$REPO" --role builder --path "$REPO/.autopilot/checks/run.sh" 2>&1); rc=$?
out2=$($PY "$SB" check-read --repo "$REPO" --role verifier --path "$REPO/.autopilot/rounds/r-01.json" 2>&1); rc2=$?
out3=$($PY "$SB" check-read --repo "$REPO" --role verifier --path "$REPO/.autopilot/checks/run.sh" 2>&1); rc3=$?
if [ "$rc" = 24 ] && [ "$rc2" = 0 ] && [ "$rc3" = 24 ]; then
  pass 5 "Builder 读不到冻结验收；Verifier 只许读 rounds/，也读不到 checks/"
else
  fail 5 "角色分档不对：builder=$rc verifier-rounds=$rc2 verifier-checks=$rc3"
fi

# ---------------------------------------------------------------- 6 私密文件形态

out=$($PY "$SB" check-read --repo "$REPO" --role builder --path "$REPO/src/.env" 2>&1); rc=$?
if [ "$rc" = 24 ] && printf '%s' "$out" | grep -q "私密文件形态"; then
  pass 6 "仓库里的 .env / *.pem / cookies 这类形态一律读拒绝"
else
  fail 6 "私密形态没拦住：rc=$rc $out"
fi

# ---------------------------------------------------------------- 7 写拒绝与受保护面

a=$($PY "$SB" check-write --repo "$REPO" --role explorer --path "$REPO/src/a.py" 2>&1; echo "rc=$?")
b=$($PY "$SB" check-write --repo "$REPO" --role explorer --path "$REPO/sandbox/x.py" 2>&1; echo "rc=$?")
c=$($PY "$SB" check-write --repo "$REPO" --role builder --path "$REPO/src/b.py" --allow src/a.py 2>&1; echo "rc=$?")
d=$($PY "$SB" check-write --repo "$REPO" --role builder --path "$REPO/.autopilot/checks/run.sh" --allow . 2>&1; echo "rc=$?")
if printf '%s' "$a" | grep -q 'rc=22' && printf '%s' "$b" | grep -q 'rc=0' \
   && printf '%s' "$c" | grep -q 'rc=22' && printf '%s' "$d" | grep -q 'rc=24'; then
  pass 7 "flex 只能写 sandbox/；builder 越写集退 22；受保护面任何角色都退 24"
else
  fail 7 "写矩阵不对：a=$a b=$b c=$c d=$d"
fi

# ---------------------------------------------------------------- 8 plan 只渲染不执行

before=$(fp_repo)
out=$($PY "$SB" plan --repo "$REPO" --role builder --allow src/a.py --render \
        --sample-read "$HOME/.ssh/known_hosts" --sample-write "$REPO/src/a.py" 2>&1); rc=$?   # privacy-scan:allow 读拒绝用例本身
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "绝不代你执行" \
   && printf '%s' "$out" | grep -q -- "--read-only" && printf '%s' "$out" | grep -q -- "--network none" \
   && printf '%s' "$out" | grep -q "DENY-READ" && [ "$(fp_repo)" = "$before" ]; then
  pass 8 "plan 产出带读/写判定与容器模板（拒网、只读根），但一个文件都没写、一条命令都没执行"
else
  fail 8 "plan 行为不对：rc=$rc 指纹变=$([ "$before" = "$(fp_repo)" ] && echo 否 || echo 是)"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
