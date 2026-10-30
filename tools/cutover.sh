#!/bin/sh
# 0.8 → 0.9 切换器。默认 DRY-RUN（只打印将要做什么）；加 --apply 才动文件。
# 在真机执行前，先用一个临时副本彩排：cutover.sh --apply <副本目录> <草稿目录>
#
# 保证四件事：
#   1) 切换前 skill 目录必然入仓并打 v0.8-baseline tag（可回滚，D8）
#   2) 只覆盖/新增，绝不删除 0.8 的任何文件（切换后逐个核对原文件仍在）
#   3) 目录合并而非嵌套（cp -R src dst 在 dst 已存在时会造出 dst/src，经典坑）
#   4) 切换后自动跑一致性检查（xref + 残留 v09/ 扫描 + sh -n + py_compile），不绿就打印回滚命令
set -u

apply=0
if [ "${1:-}" = "--apply" ]; then apply=1; shift; fi
skill=${1:-}
draft=${2:-}
[ -n "$skill" ] && [ -n "$draft" ] || { echo "用法: cutover.sh [--apply] <skill-dir> <draft-dir>"; exit 2; }
[ -d "$skill" ] || { echo "CUTOVER BAD 2 skill 目录不存在: $skill"; exit 2; }
# 草稿主文件两个名字都认：草稿仓里叫 02-SKILL-0.9.md，切完的目录里叫 SKILL.md。
# 只认前者的话，本脚本在已切换的目录里就没法再跑（0.9→0.10、或迁移彩排复用）。
if [ -f "$draft/02-SKILL-0.9.md" ]; then
  MAIN_DOC=02-SKILL-0.9.md
elif [ -f "$draft/SKILL.md" ]; then
  MAIN_DOC=SKILL.md
else
  echo "CUTOVER BAD 2 草稿缺主文件（02-SKILL-0.9.md 或 SKILL.md）: $draft"; exit 2
fi

say() { printf '%s\n' "$*"; }
run() { if [ "$apply" = 1 ]; then "$@"; else say "  [dry] $*"; fi; }

say "== 0.9 切换：$skill ← $draft"

# 0) 先记下 0.8 的文件清单，切换后逐个核对"一个都没丢"
before=$(mktemp)
after=$(mktemp)
( cd "$skill" && find . -type f -not -path "./.git/*" -not -name ".DS_Store" -not -path "*__pycache__*" | LC_ALL=C sort ) >"$before"

# 1) 版本控制基线（可回滚的前提）
if [ -d "$skill/.git" ]; then
  say "[1/6] 已在版本控制下，跳过 init；当前 HEAD: $(git -C "$skill" log --oneline -1 2>/dev/null || echo '（无提交）')"
  # 已有仓但没打基线 tag 的话，切换后就没法回到 0.8 了 —— 这里补打。
  if ! git -C "$skill" rev-parse --verify v0.8-baseline >/dev/null 2>&1; then
    run sh -c "cd '$skill' && git add -A && git -c user.name=cutover -c user.email=cutover@local commit -qm 'baseline before 0.9 cutover' && git tag -f v0.8-baseline && git tag -f baseline-0.8"
    say "  [ok] 补打基线 tag（v0.8-baseline，兼容别名 baseline-0.8）"
  fi
else
  say "[1/6] 建仓 + 打 v0.8-baseline tag"
  run git -C "$skill" init -q
  # 基线提交前先落 .gitignore，否则 __pycache__/.DS_Store 会进基线，回滚时带回来
  run sh -c "printf '__pycache__/\n*.pyc\n.DS_Store\n' > '$skill/.gitignore'"
  # 正式名是 v0.8-baseline（与另一枚 tag v0.9-detour 同一套命名）。
  # baseline-0.8 只是历史别名，同指一个 commit —— 留着免得旧脚本 rev-parse --verify baseline-0.8 找不到。
  run sh -c "cd '$skill' && git add -A && git -c user.name=cutover -c user.email=cutover@local commit -qm 'baseline before 0.9 cutover' && git tag -f v0.8-baseline && git tag -f baseline-0.8"
fi

# 2) 拷贝映射：草稿里的实现物 → skill 里的正式位置
say "[2/6] 覆盖与新增（不删除任何 0.8 文件）"
copy_file() { # src dst
  if [ -e "$draft/$1" ]; then
    run mkdir -p "$(dirname "$skill/$2")"
    # -p：连权限一起覆盖。不加 -p 时 cp 保留**目标**文件的旧权限，
    # 0.8 里某个脚本若不是可执行位，切过来就变成"Permission denied"。
    run cp -p "$draft/$1" "$skill/$2"
  else
    say "  [warn] 草稿缺少 $1 —— 该步跳过，切换后必须人工确认"
  fi
}
copy_dir() { # src dst   合并语义：dst 已存在时不能 cp -R（会造出 dst/src）
  if [ -d "$draft/$1" ]; then
    run mkdir -p "$skill/$2"
    run cp -Rp "$draft/$1/." "$skill/$2/"
  else
    say "  [warn] 草稿缺少目录 $1 —— 该步跳过，切换后必须人工确认"
  fi
}
copy_file "$MAIN_DOC"                      "SKILL.md"
copy_dir  "scripts"                        "scripts"
copy_dir  "schema"                         "schema"
copy_dir  "specs"                          "specs"
copy_dir  "templates"                      "templates"
copy_dir  "tools"                          "tools"
copy_dir  "meta-checks"                    "meta-checks"
copy_dir  "dist"                           "dist"
copy_dir  "config"                         "config"
copy_file "LICENSE"      "LICENSE"
copy_file "00-DECISIONS.md" "00-DECISIONS.md"
copy_file "01-SPEC-0.9.md"  "01-SPEC-0.9.md"
copy_file "MIGRATION.md"    "MIGRATION.md"
copy_file "AWAITING.md"     "AWAITING.md"
copy_file ".gitignore"      ".gitignore"
copy_file ".gitattributes"  ".gitattributes"

# 3) 扁平化后修正引用：scripts/ → scripts/
#    只用 python 改写：`sed -i` 在 BSD 与 GNU 上参数不同（BSD 要 `-i ''`），跨平台脚本不能依赖它。
#    草稿已按最终扁平布局组织，正常情况下这里是空操作；保留它是为了兜住"还有文件留在 v09/"的情况。
say "[3/6] 清理与引用改写（python，跨平台）"
if [ "$apply" = 1 ]; then
  python3 - "$skill" <<'PY'
import io, os, shutil, sys
root = sys.argv[1]
n = 0
for dp, dns, fns in os.walk(root):
    dns[:] = [d for d in dns if d not in {".git", "__pycache__"}]
    for f in fns:
        if not f.endswith((".md", ".sh", ".py", ".json")):
            continue
        p = os.path.join(dp, f)
        try:
            s = io.open(p, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        if "scripts/" in s:
            io.open(p, "w", encoding="utf-8").write(s.replace("scripts/", "scripts/"))
            n += 1
print("  改写 %d 个文件" % n)
# 生成的缓存不进包
for dp, dns, fns in os.walk(root):
    for d in list(dns):
        if d == "__pycache__":
            shutil.rmtree(os.path.join(dp, d), ignore_errors=True)
    # .DS_Store 是 Finder 元数据，不是产物 —— 分发包里不该有它
    for f in list(fns):
        if f == ".DS_Store":
            try:
                os.remove(os.path.join(dp, f))
            except OSError:
                pass
PY
  [ -d "$skill/scripts/v09" ] && say "  [FAIL] 仍存在 scripts/v09 暂存目录（草稿未完成扁平化）"
fi

# 4) 切换后检查
say "[4/6] 一致性检查"
if [ "$apply" = 1 ]; then
  leftover=$(grep -rn "scripts/" "$skill" --include='*.md' --include='*.sh' --include='*.py' --include='*.json' 2>/dev/null | grep -v '/\.git/' | wc -l | tr -d ' ')
  [ "$leftover" = 0 ] && say "  [ok] 无 v09 残留引用" || say "  [FAIL] 仍有 $leftover 处 v09 引用"
  bad=0
  for s in "$skill"/scripts/*.sh; do
    [ -e "$s" ] || continue
    sh -n "$s" 2>/dev/null || { say "  [FAIL] 语法不通过: $(basename "$s")"; bad=1; }
  done
  [ "$bad" = 0 ] && say "  [ok] 全部 shell 语法通过"
  if python3 -m py_compile "$skill"/scripts/*.py 2>/dev/null; then say "  [ok] 全部 python 编译通过"; else say "  [FAIL] python 编译不通过"; fi
  crlf=$(python3 - "$skill" <<'PY'
import os, sys
root = sys.argv[1]
bad = []
for dp, dns, fns in os.walk(root):
    dns[:] = [d for d in dns if d not in {".git", "__pycache__"}]
    for fn in fns:
        if not fn.endswith((".sh", ".py", ".json", ".md", ".txt")):
            continue
        p = os.path.join(dp, fn)
        try:
            if b"\r\n" in open(p, "rb").read():
                bad.append(os.path.relpath(p, root))
        except OSError:
            pass
print(len(bad))
PY
)
  [ "$crlf" = 0 ] && say "  [ok] 无 CRLF 文件（分发打包门禁 P10）" || say "  [FAIL] $crlf 个文件含 CRLF"
  dsstore=$(find "$skill" -name ".DS_Store" -not -path "*/.git/*" 2>/dev/null | wc -l | tr -d ' ')
  [ "$dsstore" = 0 ] && say "  [ok] 无 .DS_Store（Finder 元数据不进包）" || say "  [FAIL] $dsstore 个 .DS_Store 残留"
  python3 "$skill/tools/xref.py" "$skill" 2>&1 | tail -4
  # 0.8 文件零丢失核对
  ( cd "$skill" && find . -type f -not -path "./.git/*" -not -name ".DS_Store" -not -path "*__pycache__*" | LC_ALL=C sort ) >"$after"
  lost=$(LC_ALL=C comm -23 "$before" "$after")
  if [ -z "$lost" ]; then say "  [ok] 0.8 原文件零丢失"; else say "  [FAIL] 丢失文件:"; printf '%s\n' "$lost"; fi
  # 嵌套目录自检：templates/templates 这类 cp -R 陷阱
  for d in schema specs templates tools meta-checks dist config; do
    [ -d "$skill/$d/$d" ] && say "  [FAIL] 出现嵌套目录 $d/$d（cp -R 语义出错）"
  done
  # 上面的 py_compile 会重新生成 __pycache__；分发包里不留 .pyc
  python3 - "$skill" <<'PY'
import os, shutil, sys
root = sys.argv[1]
for dp, dns, fns in os.walk(root):
    for d in list(dns):
        if d == "__pycache__":
            shutil.rmtree(os.path.join(dp, d), ignore_errors=True)
    for f in list(fns):
        if f == ".DS_Store":
            try:
                os.remove(os.path.join(dp, f))
            except OSError:
                pass
PY
fi

# 5/6) 提交与回滚提示
say "[5/6] 提交切换结果"
if [ "$apply" = 1 ]; then
  ( cd "$skill" && git add -A && git -c user.name=cutover -c user.email=cutover@local commit -qm "cutover to 0.9 detour" && git tag -f v0.9-detour ) \
    && say "  [ok] 已提交并打 tag v0.9-detour" || say "  [warn] 提交失败（不影响文件已就位）"
fi
say "[6/6] 回滚方式（如需）："
say "  git -C $skill checkout v0.8-baseline -- . && git -C $skill status"
rm -f "$before" "$after"
[ "$apply" = 1 ] || say "  （以上是 DRY-RUN，未改动任何文件；加 --apply 才执行）"
exit 0
