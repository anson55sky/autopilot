#!/bin/sh
# H14 升级入口：把"备份 → 同步 → 全量复验 → 给出回滚指令"合成一条命令，
# 取代此前散着的 cutover.sh / 手工 rsync（两条升级路径迟早漂移，H28 单一实现源）。
#
# 用法:
#   tools/upgrade.sh --from <新技能目录> --into <线上技能目录>
#                    [--quick] [--dry-run] [--allow-dirty] [--backup-dir <目录>]
#
# 铁律：
#   - 目标必须是 git 仓（没有 HEAD 就没有可回滚基线），否则拒绝。
#   - 目标工作树有未提交改动时默认拒绝；--allow-dirty 会先把**当前工作树整体**
#     快照成 worktree.tar，再同步——手改不会凭空消失，但会被覆盖，所以必须显式声明。
#   - 只同步、只复验：**绝不 commit、绝不 push**（铁律 5）。回滚命令打印出来交给人执行。
#   - 任何一项验证失败 → 立刻打印回滚指令并以非零退出，不把半成品留在"已升级"状态。
#   - --quick 只跑秒级套件（自测 + schema + xref + 隐私 + 命令冒烟），
#     全量升级不加该参数（还要跑 e2e、元验收、迁移彩排）。
set -u
# 复验会 import 包内 python 模块；不让它把 __pycache__ 写进分发包（迁移彩排第 10 步判"包内不留 .pyc"）。
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE

FROM="" ; INTO="" ; QUICK=0 ; DRY=0 ; ALLOW_DIRTY=0 ; BACKUP_ROOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from) [ $# -ge 2 ] || { echo "UPGRADE 2 --from 缺参数"; exit 2; }; FROM="$2"; shift 2 ;;
    --into) [ $# -ge 2 ] || { echo "UPGRADE 2 --into 缺参数"; exit 2; }; INTO="$2"; shift 2 ;;
    --backup-dir) [ $# -ge 2 ] || { echo "UPGRADE 2 --backup-dir 缺参数"; exit 2; }; BACKUP_ROOT="$2"; shift 2 ;;
    --quick) QUICK=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --allow-dirty) ALLOW_DIRTY=1; shift ;;
    *) echo "UPGRADE 2 未知参数 $1"; exit 2 ;;
  esac
done
[ -n "$FROM" ] && [ -n "$INTO" ] || { echo "用法: upgrade.sh --from <新目录> --into <线上目录> [--quick] [--dry-run] [--allow-dirty]"; exit 2; }
[ -d "$FROM" ] || { echo "UPGRADE 2 源目录不存在：$FROM"; exit 2; }
[ -f "$FROM/SKILL.md" ] || { echo "UPGRADE 2 源目录不像技能包（缺 SKILL.md）"; exit 2; }
INTO=$(cd "$INTO" 2>/dev/null && pwd) || { echo "UPGRADE 2 目标目录不存在"; exit 2; }
[ -d "$INTO/.git" ] || { echo "UPGRADE 24 目标不是 git 仓（$INTO）：没有可回滚基线，拒绝升级"; exit 24; }

DIRTY=$(git -C "$INTO" status --porcelain 2>/dev/null)
if [ -n "$DIRTY" ] && [ "$ALLOW_DIRTY" = 0 ]; then
  echo "UPGRADE 24 目标工作树不干净——先 commit，或确认手改可被覆盖后加 --allow-dirty（会先整体快照工作树）："
  printf '%s\n' "$DIRTY" | sed 's/^/  /' | head -10
  exit 24
fi

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
# 备份默认落在技能目录**之外**：放技能目录下会被技能加载器当成新技能索引出重复条目（实测踩过）。
[ -n "$BACKUP_ROOT" ] || BACKUP_ROOT="${HOME}/.autopilot/upgrade-archive"
ARCHIVE="$BACKUP_ROOT/pre-upgrade-$STAMP"
HEAD_BEFORE=$(git -C "$INTO" rev-parse --short HEAD 2>/dev/null || echo unknown)

EXCLUDES="--exclude .git --exclude __pycache__ --exclude *.pyc"
echo "UPGRADE 目标=$INTO HEAD=$HEAD_BEFORE 备份=$ARCHIVE 模式=$([ "$QUICK" = 1 ] && echo quick || echo full)$([ "$ALLOW_DIRTY" = 1 ] && echo " allow-dirty" || true)$([ "$DRY" = 1 ] && echo " (dry-run)" || true)"
if [ "$DRY" = 1 ]; then
  rsync -an --itemize-changes $EXCLUDES "$FROM/" "$INTO/" | sed 's/^/  /'
  echo "UPGRADE 0 dry-run 完成：未写任何文件"
  exit 0
fi

mkdir -p "$ARCHIVE/head" || { echo "UPGRADE 3 备份目录建不出来：$ARCHIVE"; exit 3; }
git -C "$INTO" archive HEAD | tar -x -C "$ARCHIVE/head" \
  || { echo "UPGRADE 3 备份失败（git archive），中止且不覆盖线上"; exit 3; }
echo "UPGRADE 备份 OK（HEAD 快照 $(find "$ARCHIVE/head" -type f | wc -l | tr -d ' ') 个文件）"
if [ -n "$DIRTY" ]; then
  tar -cf "$ARCHIVE/worktree.tar" -C "$INTO" --exclude .git --exclude __pycache__ . \
    || { echo "UPGRADE 3 工作树快照失败，中止且不覆盖线上"; exit 3; }
  echo "UPGRADE 未提交改动已整体快照：$ARCHIVE/worktree.tar"
fi

rsync -a $EXCLUDES "$FROM/" "$INTO/" \
  || { echo "UPGRADE 3 rsync 失败；回滚：rsync -a --delete --exclude .git $ARCHIVE/head/ $INTO/"; exit 3; }

fails=0
run_suite() {  # 名称 命令…
  label="$1"; shift
  out=$("$@" 2>&1); rc=$?
  if [ "$rc" = 0 ]; then
    printf 'UPGRADE-VERIFY OK   %s\n' "$label"
  else
    printf 'UPGRADE-VERIFY FAIL %s（rc=%s）:: %s\n' "$label" "$rc" "$(printf '%s' "$out" | tail -n 1)"
    fails=$((fails + 1))
  fi
}

cd "$INTO" || exit 3
# AUTOPILOT_UPGRADE_SKIP_SELFTESTS=1 只用于本脚本自己的回归测试（避免自测套自测套娃）；
# 真实升级一律跑全部套件。
if [ "${AUTOPILOT_UPGRADE_SKIP_SELFTESTS:-0}" != "1" ]; then
  for f in scripts/*.selftest.sh; do
    run_suite "$(basename "$f")" sh "$f"
  done
fi
run_suite "schema 自检" python3 schema/check.py --self-test
run_suite "xref 自洽" python3 tools/xref.py "$INTO"
run_suite "隐私扫描" python3 tools/privacy_scan.py "$INTO"
if [ "${AUTOPILOT_UPGRADE_SKIP_SMOKE:-0}" != "1" ]; then
  run_suite "命令冒烟" sh tools/cmd_smoke.sh
fi
if [ "$QUICK" = 0 ]; then
  run_suite "端到端" sh tools/e2e-smoke.sh
  run_suite "元验收" sh meta-checks/run.sh    # M1 需要 AUTOPILOT_META_SAMPLE，缺项判 SKIP 不算 FAIL
  run_suite "迁移彩排" sh tools/migration_rehearsal.sh "${AUTOPILOT_META_SAMPLE:-/tmp/autopilot-v08-sample}"
fi

echo "UPGRADE 未做任何 commit/push（HEAD 仍是 $HEAD_BEFORE）"
ROLLBACK_HEAD="rsync -a --delete --exclude .git --exclude __pycache__ $ARCHIVE/head/ $INTO/"
if [ "$fails" -gt 0 ]; then
  echo "UPGRADE 1 $fails 项复验未过。回滚（恢复 HEAD 快照）："
  echo "  $ROLLBACK_HEAD"
  if [ -f "$ARCHIVE/worktree.tar" ]; then
    echo "若要连未提交手改一起找回（不删除升级新增的文件）："
    echo "  tar -xf $ARCHIVE/worktree.tar -C $INTO"
  fi
  exit 1
fi
echo "UPGRADE 0 同步并复验通过。要固化就自己 commit；要回滚："
echo "  $ROLLBACK_HEAD"
exit 0
