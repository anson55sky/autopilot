#!/usr/bin/env bash
# 生成「第 N 轮执行器」的完整提示词。用途：监督者把它交给 create_chat_session。
# 用法: round_prompt.sh <repo> [round]
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "${1:-.}" && pwd)"
ROUND="${2:-}"
if [ -z "$ROUND" ]; then
  ROUND="$(python3 - "$REPO" <<'PY'
import json, os, sys
p = os.path.join(sys.argv[1], ".autopilot", "state.json")
try:
    s = json.load(open(p, encoding="utf-8"))
    print(int(s.get("rounds_used", 0)) + 1)
except Exception:
    print(1)
PY
)"
fi

cat <<EOF
你是 autopilot 的第 ${ROUND} 轮执行器，全新上下文。仓库 ${REPO}，技能目录 ${SKILL_DIR}。

第一步（只读这些，别的不看）：
1. 跑 python3 ${SKILL_DIR}/scripts/resume.py ${REPO} —— 这是全部现状（目标、预算、验收、ready 任务、待决、记忆）。
2. 读 ${REPO}/.autopilot/GOAL.md、CHARTER.md，以及你要派发的任务卡。
不要回看上一轮对话，不要读 .autopilot/runs 里的历史回执全文，不要翻 git log 找上下文。

本轮只做一轮，按序执行：
1. 派发 resume 里 ready 的任务。写集不重叠才能并行；代码任务一张卡只写一个文件，多文件先拆卡；每张卡用 Agent 工具派一个全新上下文，提示词照 ${SKILL_DIR}/SKILL.md「派发协议」。
2. 收执 → 更新 tasks.json → 每个工人/每次验证都记一条 ledger（status.py log）。
3. 跑 bash ${SKILL_DIR}/scripts/check.sh run ${REPO}。出现 MANIFEST 漂移立即停。
4. 独立验证者出 ${REPO}/.autopilot/rounds/r-$(printf '%02d' "$ROUND").json（不许自己验自己），必填：round/verdict/passed/failed/tasks_closed/evidence/blind_spots/notes。
5. python3 ${SKILL_DIR}/scripts/status.py close-round ${REPO} ${REPO}/.autopilot/rounds/r-$(printf '%02d' "$ROUND").json
6. 复盘 1–3 条，写进记忆：python3 ${SKILL_DIR}/scripts/playbook.py add ${REPO} --kind pitfall|skill|check|command|rule --text "一句话结论"
7. 结束。不要开下一轮，不要写 REPORT.md（除非 resume 显示已触发停止条件）。

硬约束：
- 不可逆动作一律不执行：push / 部署 / 发布 / 付费调用 / 发消息 / 删数据 / 改系统配置 / 装依赖。
  需要人拍的，写收件箱而不是自己决定：
  python3 ${SKILL_DIR}/scripts/inbox.py add ${REPO} --kind approval --q "要批准什么" --options "允许|拒绝" --recommend 拒绝 --cost "代价" --task T-xx
- 不改 GOAL 的验收矩阵、不改 checks/、不改 baseline/、不动写集外文件、不改既有测试基线。
- 不顺手重构，不因为「顺便」扩大范围；新发现写 BACKLOG.md。
- 卡住不猜：写 inbox + BACKLOG，然后 BLOCKED 退出。

最后一行只输出：ROUND ${ROUND} DONE 或 ROUND ${ROUND} BLOCKED <一句话原因>
EOF
