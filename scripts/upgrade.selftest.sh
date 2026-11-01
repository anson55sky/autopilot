#!/bin/sh
# H14 升级入口自测：A-ug-01..06。全程在 mktemp -d 里造"假线上目录"（git 仓），绝不碰真技能目录。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL=$(cd "$HERE/.." && pwd)
UP="$SKILL/tools/upgrade.sh"

TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPROOT"' EXIT INT TERM

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

mk_skill() {  # 造一份最小技能包（复制真包，去掉 .git 与产物）
    _s_dst="$1"
    mkdir -p "$_s_dst"
    (cd "$SKILL" && tar -cf - --exclude .git --exclude __pycache__ --exclude '*.pyc' .) | tar -xf - -C "$_s_dst"
}

export AUTOPILOT_UPGRADE_SKIP_SELFTESTS=1 AUTOPILOT_UPGRADE_SKIP_SMOKE=1 GIT_AUTHOR_NAME=t \
       GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
# 默认备份根取自 $HOME——测试里把 HOME 指到临时目录，绝不往真 ~/.autopilot 写东西。
# 用 mktemp 的随机目录本身当 HOME，不要起 "fakehome" 这类固定名字：隐私扫描按
# 「家目录末段」匹配文件内容，本文件里写死的那个名字会被它自己判成个人标识。
export HOME="$TMPROOT"

# ---------------------------------------------------------------- 1 无基线 / 脏目标

plain="$TMPROOT/plain"
mkdir -p "$plain"
out=$(sh "$UP" --from "$SKILL" --into "$plain" --dry-run 2>&1); rc=$?
if [ "$rc" = "24" ] && printf '%s' "$out" | grep -q "不是 git 仓"; then
  pass 1 "目标不是 git 仓直接拒（没有可回滚基线就不升级）"
else
  fail 1 "非 git 目标没拦住：rc=$rc $out"
fi

tgt="$TMPROOT/target"
mk_skill "$tgt"
git -C "$tgt" init -q
git -C "$tgt" add -A >/dev/null 2>&1
git -C "$tgt" commit -qm base
printf 'dirty\n' > "$tgt/SKILL.md"
out=$(sh "$UP" --from "$SKILL" --into "$tgt" --dry-run 2>&1); rc=$?
if [ "$rc" = "24" ] && printf '%s' "$out" | grep -q "工作树不干净" \
   && [ "$(cat "$tgt/SKILL.md")" = "dirty" ]; then
  pass 2 "目标有未提交改动时默认拒绝，并且没碰那份手改"
else
  fail 2 "脏工作树没拦住：rc=$rc $out"
fi

# ---------------------------------------------------------------- 2 dry-run 不落盘

git -C "$tgt" checkout -- SKILL.md
src="$TMPROOT/src"
mk_skill "$src"
printf '\n<!-- 本次变更说明 -->\n' >> "$src/SKILL.md"
before=$(git -C "$tgt" rev-parse HEAD)
out=$(sh "$UP" --from "$src" --into "$tgt" --dry-run 2>&1); rc=$?
if [ "$rc" = "0" ] && ! cmp -s "$src/SKILL.md" "$tgt/SKILL.md" \
   && [ "$(git -C "$tgt" rev-parse HEAD)" = "$before" ]; then
  pass 3 "dry-run 只列改动清单，目标一字未动、HEAD 不变"
else
  fail 3 "dry-run 却写了东西：rc=$rc $out"
fi

# ---------------------------------------------------------------- 3 正常升级

out=$(sh "$UP" --from "$src" --into "$tgt" --quick 2>&1); rc=$?
if [ "$rc" = 0 ] && cmp -s "$src/SKILL.md" "$tgt/SKILL.md" \
   && [ "$(git -C "$tgt" rev-parse HEAD)" = "$before" ]; then
  pass 4 "同步 + 复验通过，且没有偷偷 commit（HEAD 不变）"
else
  fail 4 "升级主流程不对：rc=$rc $(printf '%s' "$out" | tail -3)"
fi
if printf '%s' "$out" | grep -q "未做任何 commit/push"; then
  pass 4 "输出里明写不 commit、不 push（铁律 5）"
else
  fail 4 "缺不可逆声明"
fi
n=$(find "$HOME" -type d -path '*pre-upgrade-*/head' | wc -l | tr -d ' ')
m=$(find "$tgt" -type d -name 'pre-upgrade-*' | wc -l | tr -d ' ')
if [ "${n:-0}" -ge 1 ] && [ "${m:-0}" = "0" ]; then
  pass 4 "HEAD 快照落在技能目录**之外**（放里面会被技能加载器索引成重复技能）"
else
  fail 4 "备份位置不对：目录外 $n 个、目标内 $m 个"
fi

# ---------------------------------------------------------------- 4 --allow-dirty 连升

printf '\n<!-- 手改 -->\n' >> "$tgt/MIGRATION.md"
out=$(sh "$UP" --from "$src" --into "$tgt" --quick 2>&1); rc=$?
if [ "$rc" = "24" ]; then
  pass 5 "上一次升级没 commit 时再升一次仍被拦住，必须显式 --allow-dirty"
else
  fail 5 "该拦住连升却放过了：rc=$rc"
fi
src2="$TMPROOT/src2"
mk_skill "$src2"
printf '\n<!-- 第二次变更 -->\n' >> "$src2/SKILL.md"
out=$(sh "$UP" --from "$src2" --into "$tgt" --quick --allow-dirty 2>&1); rc=$?
snap=$(find "$TMPROOT" -type f -name 'worktree.tar' | head -1)
if [ "$rc" = 0 ] && cmp -s "$src2/SKILL.md" "$tgt/SKILL.md" \
   && [ -n "$snap" ] && tar -xOf "$snap" ./MIGRATION.md 2>/dev/null | grep -q "手改"; then
  pass 5 "--allow-dirty 先把未提交手改整体快照成 worktree.tar 再同步"
else
  fail 5 "--allow-dirty 没留下工作树快照或没同步：rc=$rc snap=$snap $(printf '%s' "$out" | tail -2)"
fi

# ---------------------------------------------------------------- 5 复验失败要能回滚

git -C "$tgt" add -A >/dev/null 2>&1
git -C "$tgt" commit -qm upgraded
bad="$TMPROOT/bad"
mk_skill "$bad"
printf 'echo 没有 shebang\n' > "$bad/tools/no-shebang.sh"   # 让 xref X6 判 FAIL
out=$(sh "$UP" --from "$bad" --into "$tgt" --quick --allow-dirty 2>&1); rc=$?
rb=$(printf '%s' "$out" | sed -n 's/.*\(rsync -a --delete[^ ]*.*\)/\1/p' | head -1)
if [ "$rc" = 1 ] && [ -n "$rb" ] && [ -f "$tgt/tools/no-shebang.sh" ]; then
  pass 6 "复验不过时退 1，并给出可用回滚命令（坏包确实已写进目标）"
else
  fail 6 "坏包没被拦下：rc=$rc rb=$rb $(printf '%s' "$out" | tail -3)"
fi
sh -c "$rb" >/dev/null 2>&1
if [ -z "$(git -C "$tgt" status --porcelain)" ] && ! [ -f "$tgt/tools/no-shebang.sh" ] \
   && cmp -s "$src2/SKILL.md" "$tgt/SKILL.md"; then
  pass 6 "照它给的命令回滚后：新增文件被删掉、跟踪文件逐字节回到上一版"
else
  fail 6 "回滚路径不成立：$(git -C "$tgt" status --porcelain | head -3)"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
