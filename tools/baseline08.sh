#!/bin/sh
# 找一个**0.8 技能目录**。被 migration_rehearsal.sh 与 make_v08_sample.sh 共同引用。
#
# 为什么需要它：这两个工具干的事都是"拿一份 0.8 当起点"，而 0.8 的技能目录
# **只在切换之前存在于线上**（$HOME/.qoder-cn/skills/autopilot）。一旦切到 0.9，
# 线上目录就是 0.9 了，"0.8 基线从哪来"必须有个稳定的答案，否则分发包切完之后
# 自己的迁移彩排就废了（会退化成"0.9 → 0.9"，判据全错）。
#
# 0.8 的识别特征（三个都满足才是 0.8）：
#   1) 有 SKILL.md
#   2) 没有 tools/cutover.sh（0.9 才有的切换器）
#   3) SKILL.md 里没有 FLEX_RULES（0.9 才有的弹性档）
#
# 查找顺序（先到先用，全都不是 0.8 就返回失败）：
#   1) $AUTOPILOT_LIVE_SKILL     —— 显式指定（当前语义：线上技能目录）
#   2) $AUTOPILOT_BASELINE_SKILL —— 显式指定 0.8 基线位置
#   3) $HOME/.autopilot/baseline-0.8 —— 切换时保留下来的 0.8 快照（推荐做法）
#   4) $HOME/.qoder-cn/skills/autopilot —— 线上目录（切换前它就是 0.8）
#
# 用法：source 这个文件，然后调 resolve_baseline_skill；结果在变量 BASELINE_SKILL 里。
#        找不到时返回 1，并往 stderr 打一句能照着做的提示。

looks_like_08() { # dir
  [ -f "$1/SKILL.md" ] || return 1
  [ ! -f "$1/tools/cutover.sh" ] || return 1
  grep -q 'FLEX_RULES' "$1/SKILL.md" 2>/dev/null && return 1
  return 0
}

resolve_baseline_skill() {
  BASELINE_SKILL=""
  for cand in \
      "${AUTOPILOT_LIVE_SKILL:-}" \
      "${AUTOPILOT_BASELINE_SKILL:-}" \
      "${HOME:-}/.autopilot/baseline-0.8" \
      "${HOME:-}/.qoder-cn/skills/autopilot"
  do
    [ -n "$cand" ] || continue
    [ -d "$cand" ] || continue
    if looks_like_08 "$cand"; then
      BASELINE_SKILL="$cand"
      return 0
    fi
  done
  echo "找不到 0.8 技能目录（迁移彩排与 0.8 样本造样都需要它）。" >&2
  echo "  切换前：线上目录 \$HOME/.qoder-cn/skills/autopilot 就是 0.8。" >&2
  echo "  切换后：先保留一份 0.8 快照，再指向它 ——" >&2
  echo "    mkdir -p \$HOME/.autopilot/baseline-0.8" >&2
  echo "    cp -R <0.8技能目录>/. \$HOME/.autopilot/baseline-0.8/" >&2
  echo "  或用环境变量指定：export AUTOPILOT_BASELINE_SKILL=<0.8技能目录>" >&2
  return 1
}
