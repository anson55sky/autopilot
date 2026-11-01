#!/bin/sh
# 生成「第 N 轮执行器」的完整提示词。用途：监督者把它交给 create_chat_session。
# 用法: round_prompt.sh <repo> [round]
# M6 红线：生成的提示词里绝不写死本机绝对路径。文本一律用 {SKILL_ROOT}/{REPO_ROOT}
# 占位；真实位置由执行器在自己那台机器上从 .autopilot/env.json 读，
# 提示词**不做展开** —— 展开会把本机路径写进历史产物，换机即断。
set -u

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

ENV_JSON="$REPO/.autopilot/env.json"
if [ ! -f "$ENV_JSON" ]; then
  # 提醒走 stderr，不混进提示词正文（正文只含占位符）
  echo "提醒: 没有 $ENV_JSON，执行器将无法解析 {SKILL_ROOT}/{REPO_ROOT}；先跑 init.sh" >&2
fi

SKILL_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# 只在 GOAL.CONCURRENT.enable=true 时追加并发段；关闭时输出必须与串行基线逐字节一致。
CONC_ENABLED=$(python3 "$SKILL_DIR/scripts/dag_scheduler.py" config --repo "$REPO" --enabled 2>/dev/null || printf '0')
case "$CONC_ENABLED" in
  1) ;;
  *) CONC_ENABLED=0 ;;
esac

PROMPT="$(cat <<EOF
你是 autopilot 的第 ${ROUND} 轮执行器，全新上下文。

路径解析（先做这一步，再执行下面任何命令）：
1. 读 .autopilot/env.json，取 skill_root 与 repo_root 两个键。
2. 下文所有 {SKILL_ROOT} / {REPO_ROOT} 占位符 = 这两个值。本提示词刻意不含绝对路径。
3. 若 .autopilot/env.json 不存在：不要猜路径，停下并报「缺 env.json，请重跑 init.sh」。

第一步（只读这些，别的不看）：
1. 跑 python3 {SKILL_ROOT}/scripts/resume.py {REPO_ROOT} —— 这是全部现状（目标、预算、验收、ready 任务、闸门、epoch、跳过、宿主形态、待决、记忆）。
2. 读 {REPO_ROOT}/.autopilot/GOAL.md、CHARTER.md，以及你要派发的任务卡。
不要回看上一轮对话，不要读 .autopilot/runs 里的历史回执全文，不要翻 git log 找上下文。

C1 中断恢复（先于一切派发）：如果 resume/ledger 显示上一会话已产出代码与回执但没收轮——
a. 复核：逐条核对遗留回执对应文件确实存在且内容有效，不许只看回执文字；
b. 置状态：把已完成的卡在 tasks.json 里置 done（status.py 的任务命令），没做完的保持原状；
c. 记账：每张复核过的卡补一条 ledger（status.py log），注明「C1 恢复补记」；
d. 续跑：只补剩余波次，已复核的不重做、不重派。

本轮只做一轮，按序执行：
1. 派发 resume 里 ready 的任务。写集不重叠才能并行；代码任务一张卡只写一个文件，多文件先拆卡；每张卡用 Agent 工具派一个全新上下文，提示词照 {SKILL_ROOT}/SKILL.md「派发协议」。工人只跑局部检查，全量验收一轮只跑一次（见第 4 步）。
2. 闸门四调用（python3 {SKILL_ROOT}/scripts/flexgate.py，每张卡派发前后都要走）：
   - check --task T-x：派发前预检。退出码 0=放行继续；20=配额耗尽→停本轮并记 ledger；21=预算耗尽→停；22=命中红线→立即停、不许绕过；23=需许可→走第 3 步的 permit；24=命中不可逆→按硬约束转待批，不停等、不自己执行；2=用法错误→核对命令行重试一次。
   - permit --task T-x：需要 schema/migration/rename/atomic 类许可时申请，拿到令牌再派发。
   - spend --task T-x：派发时核销额度；spend 非零回滚本轮派发计划。
   - revoke --permit-id <id>：收轮或改计划时吊销未用令牌。
   配额与上限一律以 python3 {SKILL_ROOT}/scripts/flexgate.py status 的输出为准，不要自己心算。
3. 收执 → 更新 tasks.json → 每个工人/每次验证都记一条 ledger（status.py log）。
4. 冻结验收：跑 bash {SKILL_ROOT}/scripts/check.sh run {REPO_ROOT}。全量验收一轮只跑一次；出现 MANIFEST 漂移立即停。
5. 独立验证者出 {REPO_ROOT}/.autopilot/rounds/r-$(printf '%02d' "$ROUND").json（不许自己验自己），必填：round/verdict/passed/failed/skipped/tasks_closed/evidence/blind_spots/notes；有并行派发时补 parallel_peak（同时运行的工人峰值）。resume 若提示有未判定项（跳过 N>0），verdict 不得为 pass。
6. python3 {SKILL_ROOT}/scripts/status.py close-round {REPO_ROOT} {REPO_ROOT}/.autopilot/rounds/r-$(printf '%02d' "$ROUND").json
7. 复盘 1–3 条，写进记忆：python3 {SKILL_ROOT}/scripts/playbook.py add {REPO_ROOT} --kind pitfall|skill|check|command|rule --text "一句话结论"
8. 结束。不要开下一轮，不要写 REPORT.md（除非 resume 显示已触发停止条件）。

硬约束：
- 不可逆动作一律不执行：push / 部署 / 发布 / 付费调用 / 发消息 / 删数据 / 改系统配置 / 装依赖。
  闸门 check 返回 24 或动作本身命中不可逆清单时：立即写收件箱转待批（不停等，不重试，不换姿势执行）：
  python3 {SKILL_ROOT}/scripts/inbox.py add {REPO_ROOT} --kind approval --q "要批准什么" --options "允许|拒绝" --recommend 拒绝 --cost "代价" --task T-xx
- 需要自建浏览器做验证时，启动参数必须带 --mute-audio；不许用宿主已登录的浏览器 profile。
- 不改 GOAL 的验收矩阵、不改 checks/、不改 baseline/、不动写集外文件、不改既有测试基线。
- 不顺手重构，不因为「顺便」扩大范围；新发现写 BACKLOG.md。
- 卡住不猜：写 inbox + BACKLOG，然后 BLOCKED 退出。

最后一行只输出：ROUND ${ROUND} DONE 或 ROUND ${ROUND} BLOCKED <一句话原因>
EOF
)"

if [ "$CONC_ENABLED" = "1" ]; then
  CONC_BLOCK=$(cat <<'EOF'
并发调度（GOAL.CONCURRENT.enable=true，P2）——以下覆盖上面第 1–3 步的派发方式：

1. 先跑 python3 {SKILL_ROOT}/scripts/dag_scheduler.py recover --repo {REPO_ROOT}（超时只记账标 failed，不杀工人），再跑 plan --repo {REPO_ROOT}。
2. 只派发 READY 行；DEFER 是写集冲突，BLOCKED 是依赖/epoch/Triage 未满足。每张卡：闸门 check → spend → dag_scheduler.py start --task T-x → 再用 Agent 派发；同一消息可并行多个工人。
3. 工人只写卡内写集，绝不手改 tasks.json；每个 Agent 返回后先核对文件与回执，再 dag_scheduler.py finish --task T-x --status done|failed --note "..."。
4. 并发数不得超过 plan 输出的 limit；退出码 21=槽位或并发上限，停止派发并等运行中的完成；22=写集冲突；23=开关未启用；24=状态或依赖不合法；20=锁超时。
5. 所有 RUNNING 结束后（status 里 VERIFY-WINDOW open）才开验证窗口：批量验证 + 全量验收一轮只跑一次。
6. flex 卡仍按原串行流程，不进调度器。
EOF
)
  # 不能用 awk -v 传多行块：BSD awk 会报 "newline in string" 并吞掉整段提示词。
  # 用 python 按标记插入，失败时保留原 PROMPT，绝不输出空提示词。
  NEW_PROMPT=$(CONC_BLOCK="$CONC_BLOCK" PROMPT="$PROMPT" python3 - <<'PY'
import os
prompt = os.environ.get("PROMPT", "")
block = os.environ.get("CONC_BLOCK", "")
marker = "硬约束："
if block and marker in prompt:
    prompt = prompt.replace(marker, block + "\n\n" + marker, 1)
print(prompt, end="")
PY
) || NEW_PROMPT=""
  if [ -n "$NEW_PROMPT" ]; then
    PROMPT="$NEW_PROMPT"
  fi
fi
# H31：只在 GOAL.VERIFY_ACL.enable=true 时追加验证者权限段；关闭时输出与基线逐字节一致。
VA_ENABLED=$(python3 "$SKILL_DIR/scripts/verifier.py" config --repo "$REPO" --enabled 2>/dev/null || printf '0')
if [ "$VA_ENABLED" = "1" ]; then
  VA_BLOCK=$(cat <<'EOF'
验证者权限分级（GOAL.VERIFY_ACL.enable=true，H31）——补在上面第 5 步"独立验证者"之前：

1. 每个 Verifier 在写 rounds/r-XX.json 之前先声明自己这一会话的权限档位：
   python3 {SKILL_ROOT}/scripts/verifier.py declare --repo {REPO_ROOT} --task T-x --mode <只读档> --session <会话id>
2. 出结论前必跑 verifier.py check --repo {REPO_ROOT} --task T-x；它退 24 时该卡结论**不得**写进 r-XX.json（没声明 / 声明是上一轮的 / 档位不在白名单）。
3. check 打印 DEGRADED 说明宿主没有 session_mode 原语、档位只是执行器自报（提示词级）：REPORT 必须原样写降级声明，不许写成"权限已隔离"。
4. 收轮前跑 verifier.py audit --repo {REPO_ROOT} --round N：有验证结论却没有对应声明 = 判定来源不明，本轮不得记 passed。
EOF
)
  NEW_PROMPT=$(VA_BLOCK="$VA_BLOCK" PROMPT="$PROMPT" python3 - <<'PY'
import os
prompt = os.environ.get("PROMPT", "")
block = os.environ.get("VA_BLOCK", "")
marker = "硬约束："
if block and marker in prompt:
    prompt = prompt.replace(marker, block + "\n\n" + marker, 1)
print(prompt, end="")
PY
) || NEW_PROMPT=""
  if [ -n "$NEW_PROMPT" ]; then
    PROMPT="$NEW_PROMPT"
  fi
fi

# H39：只在 state.json 的 profile=lite 时追加「一屏结论页」要求；非 lite 工作区输出逐字节不变。
LITE_ON=$(python3 - "$REPO" <<'PY' 2>/dev/null || printf '0'
import json, os, sys
p = os.path.join(sys.argv[1], ".autopilot", "state.json")
try:
    print("1" if json.load(open(p, encoding="utf-8")).get("profile") == "lite" else "0")
except (OSError, ValueError):
    print("0")
PY
)
if [ "$LITE_ON" = "1" ]; then
  LITE_BLOCK=$(cat <<'EOF'
lite 档收尾要求（state.profile=lite，H39）——补在第 8 步"结束"之前：

1. 给用户看的必须是一屏结论，先取盘面真值，别凭印象写：
   python3 {SKILL_ROOT}/scripts/intake.py brief {REPO_ROOT}
2. brief 的第一行就是那句「我按下面这些标准判的，觉得不对你说」——不许改写、不许省略，
   也不许在它后面补没有判定来源的好话。
3. brief 里列了「待你确认」条目时必须原样转给用户，并说清这些不算通过；
   一条真 PASS 都没有时只能写"未完成"，不许写"做完了 / 验收全绿"。
4. 验收矩阵是 intake.py 从一句话起草的：要改判定标准 = 改契约，走提案 + 人批准，
   工人不许自己放宽，也不许为了让结论好看把 SKIP 改成 PASS。
EOF
)
  NEW_PROMPT=$(LITE_BLOCK="$LITE_BLOCK" PROMPT="$PROMPT" python3 - <<'PY'
import os
prompt = os.environ.get("PROMPT", "")
block = os.environ.get("LITE_BLOCK", "")
marker = "硬约束："
if block and marker in prompt:
    prompt = prompt.replace(marker, block + "\n\n" + marker, 1)
print(prompt, end="")
PY
) || NEW_PROMPT=""
  if [ -n "$NEW_PROMPT" ]; then
    PROMPT="$NEW_PROMPT"
  fi
fi

# 不做占位符展开：展开会把本机绝对路径写进提示词产物（换机即断，且违反 M6）。
printf '%s\n' "$PROMPT"
