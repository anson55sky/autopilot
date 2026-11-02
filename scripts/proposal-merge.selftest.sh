#!/bin/sh
# proposal-merge 自检：在 mktemp fixture 上覆盖
#   add / tighten 自动合并、relax 缺逐条确认被拒、relax 带确认通过、
#   remove 无批准被拒、epoch 不匹配被拒、旧基线归档且哈希一致、changelog 追加一行。
# 用法: sh scripts/proposal-merge.selftest.sh
# 每条一行 RESULT P<n> PASS|FAIL <说明>；任何 FAIL 退出 1。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MERGE="$HERE/proposal-merge.sh"
ENVIRON="$HERE/environ.sh"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/propmerge-selftest-XXXXXX")
trap 'printf "# fixture: %s\n" "$TMP"' EXIT
AP="$TMP/.autopilot"
CH="$AP/checks"
PROP="$TMP/sandbox/proposals"

mkdir -p "$CH" "$AP/rounds" "$PROP" "$TMP/src"

# --- 初始 epoch 0 契约 ---
printf '# GOAL\n\n- 契约 epoch：0\n\n冻结目标：跑通示例。\n' > "$AP/GOAL.md"
cat > "$AP/tasks.json" <<'EOF'
{"epoch": 0, "tasks": [
  {"id":"T-01","title":"x","role":"Builder","status":"pending","deps":[],
   "write_set":["src/game.js"],"acceptance":["A1","A7"],"card":".autopilot/tasks/T-01.md"}
]}
EOF
printf '#!/bin/sh\nRESULT A1 PASS ok\nRESULT A7 PASS ok\nexit 0\n' > "$CH/run.sh"
chmod +x "$CH/run.sh"
# 先冻结出 epoch-0 的 MANIFEST，并造一份 environment.json 让归档捕获
sh "$ENVIRON" freeze --repo "$TMP" >/dev/null
sh "$ENVIRON" probe  --repo "$TMP" >/dev/null
# 证据文件（validate 要求 evidence 指向的文件真实存在）
printf 'line1 last.log:9\nrepro: sh checks/run.sh\n' > "$PROP/EV-add.log"
printf 'tighten evidence\n' > "$PROP/EV-tighten.log"
printf 'relax evidence\n' > "$PROP/EV-relax.log"
printf 'remove evidence\n' > "$PROP/EV-remove.log"

# 记录归档前的活文件内容哈希（用于 P7 校验"归档 == 归档前"）
PRE_MANIFEST=$(cat "$CH/MANIFEST.sha256")
PRE_GOAL=$(sh "$ENVIRON" hash --repo "$TMP" --file .autopilot/GOAL.md --impl python | awk '{print $1}')

# 写一份提案：$1=输出路径，其余为字段。relax/remove 的逐条确认由调用方传 confirm 段。
make_proposal() {
  out=$1; shift
  {
    echo "# CHANGE_PROPOSAL"
    echo ""
    echo '```'
    for kv in "$@"; do
      printf '%s\n' "$kv" | sed 's/=/: /'
    done
    echo '```'
  } > "$out"
}

idx=0
fails=0
expect() {
  want=$1; desc=$2; shift 2
  idx=$((idx + 1))
  out=$("$@" 2>&1)
  got=$?
  if [ "$got" = "$want" ]; then
    printf 'RESULT P%s PASS %s (exit=%s)\n' "$idx" "$desc" "$got"
  else
    fails=$((fails + 1))
    printf 'RESULT P%s FAIL %s :: want=%s got=%s :: %s\n' "$idx" "$desc" "$want" "$got" \
      "$(printf '%s' "$out" | tail -2 | tr '\n' ' ')"
  fi
}

m() { sh "$MERGE" "$@"; }

# P1: add 自动合并（base_epoch 0）
make_proposal "$PROP/P-add.md" \
  "proposal_id = CP-add" "base_epoch = 0" "change_type = add" \
  "affected_a = A1" "evidence = sandbox/proposals/EV-add.log" \
  "approved_by = supervisor" "approved_at = 2026-01-01T00:00:00+00:00"
expect 0 "add 合并通过（epoch 0→1）" \
  m merge --repo "$TMP" --proposal "$PROP/P-add.md"
ep=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["epoch"])' "$AP/tasks.json")
if [ "$ep" = "1" ]; then
  idx=$((idx + 1)); printf 'RESULT P%s PASS 合并后 epoch 递增为 1\n' "$idx"
else
  idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT P%s FAIL epoch 未递增，得到 %s\n' "$idx" "$ep"
fi

# P2: tighten 自动合并（base_epoch 1）
make_proposal "$PROP/P-tighten.md" \
  "proposal_id = CP-tighten" "base_epoch = 1" "change_type = tighten" \
  "affected_a = A7" "evidence = sandbox/proposals/EV-tighten.log" \
  "approved_by = supervisor" "approved_at = 2026-01-02T00:00:00+00:00"
expect 0 "tighten 合并通过（epoch 1→2）" \
  m merge --repo "$TMP" --proposal "$PROP/P-tighten.md"

# P3: relax 缺逐条确认被拒（validate 31）
make_proposal "$PROP/P-relax-noc.md" \
  "proposal_id = CP-relax-noc" "base_epoch = 2" "change_type = relax" \
  "affected_a = A7" "evidence = sandbox/proposals/EV-relax.log" \
  "approved_by = supervisor" "approved_at = 2026-01-03T00:00:00+00:00"
expect 31 "relax 缺 confirm-A7 被拒" \
  m validate --repo "$TMP" --proposal "$PROP/P-relax-noc.md"
expect 31 "relax 缺确认时 merge 也拒绝，不改动 epoch" \
  m merge --repo "$TMP" --proposal "$PROP/P-relax-noc.md"

# P4: relax 带逐条确认通过（epoch 2→3）
make_proposal "$PROP/P-relax-ok.md" \
  "proposal_id = CP-relax-ok" "base_epoch = 2" "change_type = relax" \
  "affected_a = A7" "evidence = sandbox/proposals/EV-relax.log" \
  "approved_by = supervisor" "approved_at = 2026-01-03T00:00:00+00:00" \
  "confirm-A7 = yes"
expect 0 "relax 带 confirm-A7 合并通过（epoch 2→3）" \
  m merge --repo "$TMP" --proposal "$PROP/P-relax-ok.md"

# P5: remove 无批准记录被拒（validate 31）
cat > "$PROP/P-remove-noapproval.md" <<EOF
# CHANGE_PROPOSAL
proposal_id: CP-remove
base_epoch: 3
change_type: remove
affected_a: A7
evidence: sandbox/proposals/EV-remove.log
confirm-A7: yes
EOF
expect 31 "remove 缺 approved_by/approved_at 被拒" \
  m validate --repo "$TMP" --proposal "$PROP/P-remove-noapproval.md"

# P6: epoch 不匹配被拒（merge 32，且不覆写历史）
make_proposal "$PROP/P-badepoch.md" \
  "proposal_id = CP-badepoch" "base_epoch = 99" "change_type = add" \
  "affected_a = A1" "evidence = sandbox/proposals/EV-add.log" \
  "approved_by = supervisor" "approved_at = 2026-02-01T00:00:00+00:00"
expect 32 "epoch 不匹配（当前 3 vs 提案 99）被拒" \
  m merge --repo "$TMP" --proposal "$PROP/P-badepoch.md"

# P7: 旧基线确实被归档且内容哈希与归档前一致
ARCH0="$AP/baseline/epoch-0"
if [ -f "$ARCH0/MANIFEST.sha256" ] \
   && [ "$(cat "$ARCH0/MANIFEST.sha256")" = "$PRE_MANIFEST" ] \
   && [ -f "$ARCH0/checks/MANIFEST.sha256" ] \
   && [ -f "$ARCH0/environment.json" ]; then
  idx=$((idx + 1)); printf 'RESULT P%s PASS baseline/epoch-0 归档 MANIFEST 逐字节等于归档前\n' "$idx"
else
  idx=$((idx + 1)); fails=$((fails + 1))
  printf 'RESULT P%s FAIL 归档 MANIFEST 与原内容不一致或缺文件\n' "$idx"
fi
ARCH_GOAL_HASH=$(sh "$ENVIRON" hash --repo "$TMP" --file .autopilot/baseline/epoch-0/GOAL.md --impl python | awk '{print $1}')
if [ -n "$PRE_GOAL" ] && [ "$ARCH_GOAL_HASH" = "$PRE_GOAL" ]; then
  idx=$((idx + 1)); printf 'RESULT P%s PASS 归档 GOAL.md 哈希与归档前一致\n' "$idx"
else
  idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT P%s FAIL 归档 GOAL.md 哈希不一致\n' "$idx"
fi
# 永不删除：原活文件仍在
if [ -f "$CH/run.sh" ] && [ -f "$AP/GOAL.md" ]; then
  idx=$((idx + 1)); printf 'RESULT P%s PASS 合并为复制归档，活文件未被删除\n' "$idx"
else
  idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT P%s FAIL 活文件被删除\n' "$idx"
fi

# P8: changelog 每合并一次追加一行（成功合并 = add/tighten/relax = 3 条）
CL="$AP/contract-changelog.md"
rows=$(grep -Ec '^\| [0-9]+ ' "$CL" 2>/dev/null || echo 0)
if [ -f "$CL" ] && [ "$rows" = "3" ] && grep -q 'CP-relax-ok' "$CL"; then
  idx=$((idx + 1)); printf 'RESULT P%s PASS changelog 恰追加 3 行数据（每次合并一行）\n' "$idx"
else
  idx=$((idx + 1)); fails=$((fails + 1))
  printf 'RESULT P%s FAIL changelog 行数=%s（期望 3）或缺 CP-relax-ok\n' "$idx" "$rows"
fi

# P13 GOAL 的「契约 epoch：N」声明行必须随合并同步推进
#      （ContraRunner 实测：merge 只加 tasks.json 的 epoch，声明行留在旧值，两处差 1，
#       于是「跨 epoch 的历史绿不并入当轮结论」这条规则失去可核对的锚点）
ACT_EPOCH=$(grep -oE '契约 epoch：[0-9]+' "$AP/GOAL.md" | grep -oE '[0-9]+')
ARCH_EPOCH=$(grep -oE '契约 epoch：[0-9]+' "$AP/baseline/epoch-0/GOAL.md" | grep -oE '[0-9]+' || echo missing)
TASKS_EPOCH=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["epoch"])' "$AP/tasks.json")
idx=$((idx + 1))
if [ "$ACT_EPOCH" = "3" ] && [ "$TASKS_EPOCH" = "3" ] && [ "$ARCH_EPOCH" = "0" ]; then
  printf 'RESULT P%s PASS 合并后活 GOAL 声明行同步到 3（与 tasks.json 一致），归档仍是合并前的 0\n' "$idx"
else
  printf 'RESULT P%s FAIL GOAL 声明行未同步：active=%s tasks=%s archive0=%s\n' "$idx" "$ACT_EPOCH" "$TASKS_EPOCH" "$ARCH_EPOCH"
  fails=$((fails + 1))
fi

printf '自检 %d 例，失败 %d\n' "$idx" "$fails"
[ "$fails" = 0 ] || exit 1
exit 0
