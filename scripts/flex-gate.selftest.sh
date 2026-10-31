#!/bin/sh
# flex-gate 自检：搭一个临时项目，逐条验证闸门真的拦得住。
# 用法: sh scripts/flex-gate.selftest.sh
# 每条一行 RESULT S<n> PASS|FAIL <说明>；任何 FAIL 退出 1。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
GATE="$HERE/flex-gate.sh"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/flexgate-selftest-XXXXXX")
trap 'printf "# fixture: %s\n" "$TMP"' EXIT

mkdir -p "$TMP/.autopilot" "$TMP/sandbox/draft" "$TMP/src"
printf 'a\n' > "$TMP/sandbox/draft/a.txt"
printf 'b\n' > "$TMP/src/game.js"

# max_calls=20，flex_budget_ratio=0.20 → flex_calls>4 就该判预算耗尽
cat > "$TMP/.autopilot/state.json" <<'EOF'
{"rounds_used": 0, "budget": {"max_rounds": 5, "max_calls": 20, "max_minutes": 60}}
EOF

cat > "$TMP/.autopilot/tasks.json" <<'EOF'
{"tasks": [
  {"id":"T-01","title":"strict 单文件","role":"Builder","status":"pending","deps":[],
   "write_set":["src/game.js"],"acceptance":["A1"],"card":".autopilot/tasks/T-01.md"},
  {"id":"T-02","title":"flex 正常卡","role":"Builder","status":"pending","deps":[],
   "write_set":["sandbox/draft/a.txt"],"acceptance":[],"card":"c.md",
   "mode":"flex-light","sandbox_target":"sandbox/draft"},
  {"id":"T-03","title":"flex 越界写主目录","role":"Builder","status":"pending","deps":[],
   "write_set":["src/game.js"],"acceptance":[],"card":"c.md",
   "mode":"flex-light","sandbox_target":"sandbox/draft"},
  {"id":"T-04","title":"strict 多文件无令牌","role":"Builder","status":"pending","deps":[],
   "write_set":["src/game.js","src/audio.js"],"acceptance":["A2"],"card":"c.md"},
  {"id":"T-05","title":"flex 声明主验收项","role":"Builder","status":"pending","deps":[],
   "write_set":["sandbox/draft/a.txt"],"acceptance":["A3"],"card":"c.md",
   "mode":"flex-light","sandbox_target":"sandbox/draft"},
  {"id":"T-06","title":"另一张 flex 卡","role":"Builder","status":"pending","deps":[],
   "write_set":["sandbox/draft/b.txt"],"acceptance":[],"card":"c.md",
   "mode":"flex-light","sandbox_target":"sandbox/draft"},
  {"id":"T-07","title":"第三张 flex 卡","role":"Builder","status":"pending","deps":[],
   "write_set":["sandbox/draft/c.txt"],"acceptance":[],"card":"c.md",
   "mode":"flex-light","sandbox_target":"sandbox/draft"},
  {"id":"T-08","title":"第四张 flex 卡","role":"Builder","status":"pending","deps":[],
   "write_set":["sandbox/draft/d.txt"],"acceptance":[],"card":"c.md",
   "mode":"flex-light","sandbox_target":"sandbox/draft"}
]}
EOF

# GOAL 里故意：1) 试图把每轮额度从 2 放宽到 9（必须被忽略）
#             2) 试图把冷却从 2 收紧到 3（必须生效）
#             3) 试图改不可配项 heavy_in_run_effect（必须被忽略）
cat > "$TMP/.autopilot/GOAL.md" <<'EOF'
# GOAL

## FLEX_RULES

```
flex_per_round = 9              # 试图放宽，应被忽略（只许收紧）
flex_same_target_cool = 3       # 收紧，应生效
heavy_in_run_effect = allow     # 不在可配集合，应被忽略
```
EOF

idx=0
fails=0
expect() {
  want=$1; desc=$2; shift 2
  idx=$((idx + 1))
  out=$("$@" 2>&1)
  got=$?
  if [ "$got" = "$want" ]; then
    printf 'RESULT S%s PASS %s (exit=%s)\n' "$idx" "$desc" "$got"
  else
    fails=$((fails + 1))
    printf 'RESULT S%s FAIL %s :: want=%s got=%s :: %s\n' "$idx" "$desc" "$want" "$got" \
      "$(printf '%s' "$out" | tail -2 | tr '\n' ' ')"
  fi
}

g() { sh "$GATE" "$@"; }

expect 0  "strict 单文件放行"                 g check --repo "$TMP" --task T-01
expect 22 "flex 写主目录 → 红线"              g check --repo "$TMP" --task T-03
expect 22 "flex 声明主验收项 → 红线"          g check --repo "$TMP" --task T-05
expect 0  "flex 写 sandbox 且无验收项 → 放行" g check --repo "$TMP" --task T-02
expect 0  "spend 记账" g spend --repo "$TMP" --task T-02 --reason "验证跳越物理与手感差异是否值得做原型" --calls 1
expect 20 "同目标冷却期内重复 flex → 拒绝"    g check --repo "$TMP" --task T-02 --round 2

# 把本轮 light 额度打到上限（默认 2；GOAL 里的 9 必须没生效）
g spend --repo "$TMP" --task T-02 --reason "第二轮探索记账，确认额度按默认 2 计算" --calls 1 --round 3 >/dev/null
expect 20 "每轮 light 达上限 2 → 拒绝"        g check --repo "$TMP" --task T-06 --round 3
expect 23 "strict 多文件但无 batch 令牌"      g check --repo "$TMP" --task T-04
expect 0  "发放 batch 令牌（原子改动）" \
  g permit --repo "$TMP" --task T-04 --files src/game.js,src/audio.js --kind atomic \
    --rounds 1 --reason "两处签名必须同时改否则调用方编译不过，属原子不可拆"
expect 23 "已有活跃令牌时不得再发第二枚" \
  g permit --repo "$TMP" --task T-06 --files sandbox/draft/b.txt --kind schema --rounds 1 \
    --reason "试图绕过单令牌限制"
expect 0  "strict 多文件 + 有效令牌 → 放行"   g check --repo "$TMP" --task T-04
expect 0  "回收令牌"                          g revoke --repo "$TMP" --permit-id P-01
expect 23 "令牌回收后 strict 多文件重新被拒"  g check --repo "$TMP" --task T-04

# 令牌必须绑定写集：发牌后改 write_set 不能继续放行
expect 0 "发放写集不符的令牌" \
  g permit --repo "$TMP" --task T-04 --files src/game.js --kind atomic --rounds 1 \
    --reason "故意只绑定一个文件，验证检查时必须比对写集指纹"
expect 23 "令牌写集与任务卡不符 → 拒绝"       g check --repo "$TMP" --task T-04
expect 0  "回收写集不符令牌"                   g revoke --repo "$TMP" --permit-id P-02
expect 2  "spend 负数次数 → 用法错误"          g spend --repo "$TMP" --task T-04 --reason "试图倒扣额度" --calls -5 --round 5

# 状态数字被手改坏：闸门不得崩，按 0 处理
TMP3=$(mktemp -d "${TMPDIR:-/tmp}/flexgate-corrupt-XXXXXX")
mkdir -p "$TMP3/.autopilot"
cat > "$TMP3/.autopilot/state.json" <<'EOF'
{"rounds_used": "x", "no_progress_streak": "x", "budget": {"max_calls": "many"}}
EOF
cat > "$TMP3/.autopilot/tasks.json" <<'EOF'
{"epoch": 0, "tasks": [
  {"id": "T-F", "mode": "flex-light", "write_set": ["sandbox/draft/a.txt"]}
]}
EOF
expect 0 "状态数字损坏时 flex 预检不崩"       g check --repo "$TMP3" --task T-F
rm -rf "$TMP3"

# 零进展连击 → flex 应被禁（连击数来自 state.json，闸门只读不猜）
g spend --repo "$TMP" --task T-06 --reason "重置每轮计数以单独验证零进展规则" --calls 0 --round 5 --new-round >/dev/null
# --new-round 必须先清零再记账：本轮第一次 spend 不能被自己吞掉（曾把 light_used 记成 0）
if python3 - "$TMP" <<'PY'
import json, sys
st = json.load(open(sys.argv[1] + "/sandbox/.gate/state.json", encoding="utf-8"))
ok = st.get("light_used") == 1 and st.get("round") == 5
print(json.dumps({"light_used": st.get("light_used"), "round": st.get("round")}))
sys.exit(0 if ok else 1)
PY
then
  idx=$((idx + 1)); printf 'RESULT S%s PASS --new-round 先清零再记账，首次 spend 计入 1\n' "$idx"
else
  idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT S%s FAIL --new-round 吞掉了首次 spend\n' "$idx"
fi
python3 - "$TMP" <<'PY'
import json, sys
p = sys.argv[1] + "/.autopilot/state.json"
d = json.load(open(p, encoding="utf-8")); d["no_progress_streak"] = 2
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
expect 20 "零进展连击达阈值 → flex 被禁"      g check --repo "$TMP" --task T-07 --round 5
python3 - "$TMP" <<'PY'
import json, sys
p = sys.argv[1] + "/.autopilot/state.json"
d = json.load(open(p, encoding="utf-8")); d["no_progress_streak"] = 0
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
expect 0  "连击归零后同一张 flex 卡恢复放行"  g check --repo "$TMP" --task T-07 --round 6

# 别名必须收敛到更严值（fail-closed），放宽的那行要被忽略
TMP2=$(mktemp -d "${TMPDIR:-/tmp}/flexgate-alias-XXXXXX")
mkdir -p "$TMP2/.autopilot"
cat > "$TMP2/.autopilot/GOAL.md" <<'EOF'
# GOAL

## FLEX_RULES

```
flex_no_progress_stop = 5                  # 试图放宽，应被忽略
flex_consecutive_no_progress_stop = 1      # 同一项的别名，更严，应生效
```
EOF
st2=$(g status --repo "$TMP2")
printf '%s\n' "$st2" | grep -q '"flex_no_progress_stop": 1' \
  && { idx=$((idx + 1)); printf 'RESULT S%s PASS 别名收敛到更严值，放宽行被忽略\n' "$idx"; } \
  || { idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT S%s FAIL 别名未收敛 :: %s\n' "$idx" "$(printf '%s' "$st2" | tr '\n' ' ')"; }

expect 24 "黑名单: git push"        g deny-list --check "git push origin main"
expect 24 "黑名单: sudo rm -rf"     g deny-list --check "sudo rm -rf /Users/x/project"
expect 24 "黑名单: npm install"     g deny-list --check "npm install left-pad"
expect 24 "黑名单: curl POST"       g deny-list --check "curl -X POST https://api.example.com/x"
expect 24 "黑名单: 读凭据"          g deny-list --check "cat ~/.ssh/id_rsa"  # privacy-scan:allow 黑名单用例本身
expect 0  "普通命令不误伤"          g deny-list --check "ls -la && node --version"

g spend --repo "$TMP" --task T-07 --reason "把 flex_calls 打满以触发预算闸" --calls 20 --round 9 --new-round >/dev/null
mkdir -p "$TMP/sandbox/hypo" && printf 'x\n' > "$TMP/sandbox/hypo/HYPOTHESIS_CHECK.md"
mkdir -p "$TMP/sandbox/proposals"
cat > "$TMP/sandbox/proposals/CHANGE_PROPOSAL-001.md" <<'EOF'
proposal_id: CP-001
status: draft（待批）
EOF
cat > "$TMP/sandbox/proposals/CHANGE_PROPOSAL-002.md" <<'EOF'
---
status: merged（epoch 0→1）
---
# CP-002
EOF
expect 21 "flex 预算超比例 → 拒绝"            g check --repo "$TMP" --task T-08 --round 9
printf '{"broken": \n' >> "$TMP/sandbox/.gate/gate.jsonl"
expect 0  "audit 生成 flex 审计"              g audit --repo "$TMP" --round 9

# 审计文件必须存在且带 sandbox 树指纹 + 探索产物清单（hypo/proposals/artifacts 三键）
if [ -f "$TMP/.autopilot/rounds/r-09.flex.json" ] \
   && grep -q '"sandbox_tree_sha256"' "$TMP/.autopilot/rounds/r-09.flex.json" \
   && grep -q '"artifacts"' "$TMP/.autopilot/rounds/r-09.flex.json" \
   && grep -q '"hypo_checks"' "$TMP/.autopilot/rounds/r-09.flex.json" \
   && grep -q 'sandbox/hypo/HYPOTHESIS_CHECK.md' "$TMP/.autopilot/rounds/r-09.flex.json"; then
  idx=$((idx + 1)); printf 'RESULT S%s PASS r-09.flex.json 落盘并含树指纹与探索产物清单\n' "$idx"
else
  idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT S%s FAIL flex 审计未落盘或缺字段\n' "$idx"
fi
# gate_version 必须是可读的 skill 版本，而不是占位符
if grep -q '"gate_version": "autopilot 0\.9' "$TMP/.autopilot/rounds/r-09.flex.json"; then
  idx=$((idx + 1)); printf 'RESULT S%s PASS gate_version 带 skill 版本号\n' "$idx"
else
  idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT S%s FAIL gate_version 不是 skill 版本号\n' "$idx"
fi

# 提案状态必须读文件头 status 字段，不能只看文件名
if python3 - "$TMP/.autopilot/rounds/r-09.flex.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
st = d.get("proposal_state") or {}
op = d.get("open_proposals") or []
draft = "sandbox/proposals/CHANGE_PROPOSAL-001.md"
merged = "sandbox/proposals/CHANGE_PROPOSAL-002.md"
sys.exit(0 if st.get(draft) == "draft" and st.get(merged) == "merged"
         and draft in op and merged not in op else 1)
PY
then
  idx=$((idx + 1)); printf 'RESULT S%s PASS 提案 status 解析（draft 计积压、merged 不计）\n' "$idx"
else
  idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT S%s FAIL 提案 status 未解析\n' "$idx"
fi

# 配置收紧生效、放宽被忽略
st=$(g status --repo "$TMP")
printf '%s\n' "$st" | grep -q '"flex_per_round": 2' \
  && { idx=$((idx + 1)); printf 'RESULT S%s PASS GOAL 放宽额度被忽略（仍为 2）\n' "$idx"; } \
  || { idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT S%s FAIL 放宽额度未被忽略 :: %s\n' "$idx" "$(printf '%s' "$st" | tr '\n' ' ')"; }
printf '%s\n' "$st" | grep -q '"flex_same_target_cool": 3' \
  && { idx=$((idx + 1)); printf 'RESULT S%s PASS GOAL 收紧冷却被采纳（3）\n' "$idx"; } \
  || { idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT S%s FAIL 收紧冷却未被采纳\n' "$idx"; }

printf '自检 %d 例，失败 %d\n' "$idx" "$fails"
[ "$fails" = 0 ] || exit 1
exit 0
