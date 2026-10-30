#!/bin/sh
# 命令级冒烟：把文档里承诺的命令**真跑一遍**，抓「文档写了但实现不支持」。
#
# 为什么要有这个：xref 只能查文件存不存在，查不出参数对不对。
# 实例：SKILL.md 写 `status.py metrics $REPO --round N`，实现只收位置参数 —— 读文档看不出来，跑一下就炸。
#
# 判定标准：命令跑完不能出现 Python traceback；退出码 1/2 属"参数不足或前置条件缺失"，算通过
#（那是可预期的用法错误，不是崩溃）；退出码 ≥3 或出现 traceback 判失败。
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/autopilot-cmdsmoke-XXXXXX")
REPO="$TMP/repo"
mkdir -p "$REPO"
fail=0
pass=0

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

say() { printf '%s\n' "$*"; }
ok() { pass=$((pass + 1)); printf 'PASS C%s %s\n' "$1" "$2"; }
no() { fail=$((fail + 1)); printf 'FAIL C%s %s :: %s\n' "$1" "$2" "$3"; }

# 抽取 sh 代码块里的命令：先接续行（行尾 \ 的并成一条），再滤掉注释、空行、纯赋值与文件系统操作
# 每个代码块打一个块号（B1、B2…）：不同块是**各自独立**的上手流程（同一份文档里中英文两段
# quickstart 就是两块），块之间必须换干净仓库，否则第二块的 init.sh 会撞上"已存在一次运行"。
extract() { # file
  awk '
    /^```sh/ { f=1; blk++; next }
    /^```/   { f=0; next }
    !f      { next }
    {
      line = $0
      if (line ~ /\\$/) { buf = buf line " "; next }
      printf "B%d\t%s%s\n", blk, buf, line
      buf = ""
    }
    END { if (buf != "") printf "B%d\t%s\n", blk, buf }
  ' "$1" \
    | sed 's/^\(B[0-9]*\)\t[[:space:]]*/\1\t/; s/[[:space:]]*\\$//' \
    | grep -v $'B[0-9]*\t#' | grep -v $'B[0-9]*\t$' \
    | grep -vE $'B[0-9]*\t[A-Za-z_][A-Za-z0-9_]*=' \
    | grep -vE $'B[0-9]*\t(cat|echo|cd|mkdir|touch|cp|mv|rm|ls|printf .*>|git )'
}

run_one() { # idx name cmd
  idx=$1; name=$2; cmd=$3
  out=$TMP/out.$idx
  # 文档里的占位符替换成真实路径（分发包用 {SKILL_ROOT}/{REPO_ROOT}，规范用 $SKILL/$REPO）
  cmd=$(printf '%s' "$cmd" | sed "s|{SKILL_ROOT}|$ROOT|g; s|{REPO_ROOT}|$REPO|g")
  # shellcheck disable=SC2086
  # stdin 接 /dev/null：命令清单是从文件里 while read 出来的，任何读 stdin 的命令
  # （比如文档里的 ${EDITOR:-vi}）都会把剩下的清单当输入吃掉，导致后面的命令一条都没真跑。
  ( cd "$REPO" && eval "SKILL='$ROOT' REPO='$REPO' $cmd" </dev/null ) >"$out" 2>&1
  rc=$?
  if grep -q "Traceback (most recent call last)" "$out"; then
    no "$idx" "$name" "python traceback：$(grep -m1 Traceback "$out")"
    return
  fi
  if [ "$rc" -ge 3 ] || [ "$rc" -lt 0 ]; then
    no "$idx" "$name" "退出码 $rc：$(head -1 "$out")"
    return
  fi
  ok "$idx" "$name"
}

idx=0
# 草稿里协议文档叫 02-SKILL-0.9.md；切到线上后它就是 SKILL.md。两个名字都认。
for f in "$ROOT/SKILL.md" "$ROOT/02-SKILL-0.9.md" "$ROOT/dist/README.md"; do
  [ -f "$f" ] || continue
  # 同一个文档只跑一次（草稿与分发包可能同时存在两个名字，内容一致）
  key=$(basename "$f")
  case "$key" in
    02-SKILL-0.9.md) [ -f "$ROOT/SKILL.md" ] && continue ;;
  esac
  # 用临时文件逐行读：管道会起子 shell，变量就丢了
  extract "$f" > "$TMP/cmds.$$"
  blk=""
  while IFS="$(printf '\t')" read -r cur_blk cmd; do
    [ -n "$cur_blk" ] || continue
    if [ "$cur_blk" != "$blk" ]; then
      # 换块 = 换干净仓库：每块都是独立上手流程，不能共用工作区
      blk="$cur_blk"
      rm -rf "$REPO"
      mkdir -p "$REPO"
    fi
    idx=$((idx + 1))
    name=$(printf '%s' "$cmd" | cut -c1-70)
    run_one "$idx" "$name" "$cmd"
  done < "$TMP/cmds.$$"
  rm -f "$TMP/cmds.$$"
done

say ""
say "命令冒烟：PASS $pass / FAIL $fail"
[ "$fail" -eq 0 ] || exit 1
exit 0
