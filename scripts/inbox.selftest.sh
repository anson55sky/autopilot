#!/bin/sh
# inbox.py（0.9 / B8 审批签发者认证）自检：
# 在 mktemp -d 的 fixture 上真实跑通每一条认证与状态机规则。
# 用法: sh scripts/inbox.selftest.sh
# 每条一行 RESULT IB<n> PASS|FAIL <说明>；任何 FAIL 退出 1。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INBOX="$HERE/inbox.py"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/autopilot-inbox-selftest-XXXXXX")
trap 'printf "# fixture: %s\n" "$TMP"' EXIT
mkdir -p "$TMP/.autopilot"

idx=0
fails=0
expect() {
  want=$1; desc=$2; shift 2
  idx=$((idx + 1))
  out=$("$@" 2>&1)
  got=$?
  if [ "$got" = "$want" ]; then
    printf 'RESULT IB%s PASS %s (exit=%s)\n' "$idx" "$desc" "$got"
  else
    fails=$((fails + 1))
    printf 'RESULT IB%s FAIL %s :: want=%s got=%s :: %s\n' "$idx" "$desc" "$want" "$got" \
      "$(printf '%s' "$out" | tail -2 | tr '\n' ' ')"
  fi
}

i() { python3 "$INBOX" "$@"; }

# ---------------------------------------------------------------- 主 fixture
# IB1：add 正常落盘
expect 0 "add approval 条目" i add "$TMP" --kind approval --q "是否放行 T-05 的部署脚本改动" --task T-05

# 此刻 I-1 仍是 open（从未被 list/show 读取过）。
# IB2：自问自答被拒——add 之后没有任何 list/show，supervisor 带依据无 ref 也须被拦
expect 31 "自问自答被拒（open 状态 answer 缺 ref，supervisor 有 note 也不行）" \
  i answer "$TMP" I-1 --by supervisor --note "监督者认为可直接批" --answer "同意"

# IB3：同上，--by human 缺 ref 也被拒（退出码 31）
expect 31 "open 状态下 --by human 缺 ref 被拒" \
  i answer "$TMP" I-1 --by human --answer "同意"

# IB4：list --json 可被 json.load 解析（读取本身把 I-1 标记为 presented）
idx=$((idx + 1))
if i list "$TMP" --all --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d and d[0]["id"]=="I-1"' 2>/dev/null; then
  printf 'RESULT IB%s PASS list --json 可被 json.load 解析，且读取即 presented\n' "$idx"
else
  fails=$((fails + 1))
  printf 'RESULT IB%s FAIL list --json 解析失败\n' "$idx"
fi

# I-1 现在是 presented。认证规则逐条验证：
# IB5：presented 状态下 --by human 缺 ref → 31
expect 31 "--by human 缺 ref 被拒（退出码 31）" \
  i answer "$TMP" I-1 --by human --answer "口头批准"

# IB6：presented 状态下 --by supervisor 缺依据 → 31
expect 31 "--by supervisor 缺依据（note）被拒" \
  i answer "$TMP" I-1 --by supervisor --answer "同意"

# IB7：open 行字节不变（answer 前后对 inbox.jsonl 首行取和）
first_before=$(head -1 "$TMP/.autopilot/inbox.jsonl" | cksum | awk '{print $1}')

# IB8：正常 human + ref → 答复成功
expect 0 "human + ref 答复成功（含 --decision 与 --answer 并存）" \
  i answer "$TMP" I-1 --by human --ref "qoder-interaction-7f3a" --decision approve --answer "使用者会话内确认放行"

# IB9：is_approved 为真（approved 子命令退出码 0）
expect 0 "is_approved(I-1) 为真" i approved "$TMP" I-1

idx=$((idx + 1))
if [ "$(i approved "$TMP" I-1 --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["approved"])')" = "True" ]; then
  printf 'RESULT IB%s PASS approved --json 报 approved=true\n' "$idx"
else
  fails=$((fails + 1))
  printf 'RESULT IB%s FAIL approved --json 未报 true\n' "$idx"
fi

# IB11：answered_at 必须带时区偏移（禁止裸时间戳，C3）
idx=$((idx + 1))
if i show "$TMP" I-1 --json | python3 -c '
import json, re, sys
d = json.load(sys.stdin)
s = d.get("answered_at", "")
assert re.search(r"([+-]\d{2}:\d{2}|Z)$", s), s
' 2>/dev/null; then
  printf 'RESULT IB%s PASS answered_at 带时区偏移\n' "$idx"
else
  fails=$((fails + 1))
  printf 'RESULT IB%s FAIL answered_at 缺时区偏移\n' "$idx"
fi

# IB12：历史记录不被改写——answer 前后 open 行字节一致（只追加）
first_after=$(head -1 "$TMP/.autopilot/inbox.jsonl" | cksum | awk '{print $1}')
idx=$((idx + 1))
if [ "$first_before" = "$first_after" ]; then
  printf 'RESULT IB%s PASS 历史记录不被改写（open 行字节不变）\n' "$idx"
else
  fails=$((fails + 1))
  printf 'RESULT IB%s FAIL open 行被改写\n' "$idx"
fi

# supervisor 通道：show 读取 → presented → supervisor + note 可签
expect 0 "add 第二条（decision）" i add "$TMP" --kind decision --q "是否把验收矩阵 A3 阈值收紧"
expect 0 "show I-2（读取即 presented）" i show "$TMP" I-2
expect 0 "supervisor + note 无 ref 答复成功" \
  i answer "$TMP" I-2 --by supervisor --note "依据 r-04 实测日志与冻结矩阵，监督者签" --decision reject
idx=$((idx + 1))
if i approved "$TMP" I-2 --json | grep -q '"approved": true'; then
  printf 'RESULT IB%s PASS supervisor 签署后 is_approved 为真\n' "$idx"
else
  fails=$((fails + 1))
  printf 'RESULT IB%s FAIL supervisor 签署未判为批准\n' "$idx"
fi

# ---------------------------------------------------------------- legacy fixture
# 模拟 0.8 时代落盘的历史记录：answer 事件只有 by，没有 answered_by。
TMP2=$(mktemp -d "${TMPDIR:-/tmp}/autopilot-inbox-legacy-XXXXXX")
mkdir -p "$TMP2/.autopilot"
cat > "$TMP2/.autopilot/inbox.jsonl" <<'EOF'
{"type": "open", "id": "I-1", "kind": "approval", "question": "执行器自称已获口头批准的操作", "options": [], "recommend": "", "task": "T-09", "cost": "", "round": "3", "ts": "2026-10-30T11:00:00+08:00"}
{"type": "answer", "id": "I-1", "answer": "用户会话内口头批准", "by": "human", "ts": "2026-10-30T11:02:00+08:00"}
EOF

idx=$((idx + 1))
if i list --repo "$TMP2" --all --json | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d and d[0]["auth"] == "legacy-unauthenticated", d
' 2>/dev/null; then
  printf 'RESULT IB%s PASS 0.8 旧记录 list 标注 legacy-unauthenticated\n' "$idx"
else
  fails=$((fails + 1))
  printf 'RESULT IB%s FAIL 旧记录未标注 legacy-unauthenticated\n' "$idx"
fi

expect 30 "旧记录 is_approved 为假（未批准）" i approved "$TMP2" I-1

idx=$((idx + 1))
if i list "$TMP2" --all | grep -q 'legacy-unauthenticated'; then
  printf 'RESULT IB%s PASS 文本 list 同样可见 legacy 标注\n' "$idx"
else
  fails=$((fails + 1))
  printf 'RESULT IB%s FAIL 文本 list 未显示 legacy 标注\n' "$idx"
fi

# legacy 历史不被改写：上面若干次 list/approved 读取后，两行原始事件仍在
idx=$((idx + 1))
if [ "$(head -2 "$TMP2/.autopilot/inbox.jsonl" | cksum | awk '{print $1}')" = \
     "$(printf '%s\n%s\n' \
        '{"type": "open", "id": "I-1", "kind": "approval", "question": "执行器自称已获口头批准的操作", "options": [], "recommend": "", "task": "T-09", "cost": "", "round": "3", "ts": "2026-10-30T11:00:00+08:00"}' \
        '{"type": "answer", "id": "I-1", "answer": "用户会话内口头批准", "by": "human", "ts": "2026-10-30T11:02:00+08:00"}' | cksum | awk '{print $1}')" ]; then
  printf 'RESULT IB%s PASS legacy 历史行读取后字节不变（只追加不改写）\n' "$idx"
else
  fails=$((fails + 1))
  printf 'RESULT IB%s FAIL legacy 历史行被改写\n' "$idx"
fi

# ---------------------------------------------------------------- H3 二期：宿主回执对账

TMP3=$(mktemp -d "${TMPDIR:-/tmp}/autopilot-inbox-receipts-XXXXXX")
mkdir -p "$TMP3/.autopilot"
expect 0 "对账 fixture：add 两条待批" i add "$TMP3" --kind approval --q "是否执行 git push" --task T-12
i add "$TMP3" --kind approval --q "是否删掉生产数据" --task T-13 >/dev/null
i list "$TMP3" >/dev/null
expect 0 "对账 fixture：真回执答复" i answer "$TMP3" I-1 --by human --answer "同意" --ref int-7
expect 0 "对账 fixture：伪造回执答复" i answer "$TMP3" I-2 --by human --answer "同意" --ref int-not-exist

printf '{"receipts":[{"interaction_id":"int-7","decision":"approve","by":"human"}]}\n' > "$TMP3/receipts.json"
out=$(i verify "$TMP3" --receipts "$TMP3/receipts.json" 2>&1); got=$?
idx=$((idx + 1))
if [ "$got" = 24 ] && printf '%s' "$out" | grep -q "VERIFIED    I-1" \
   && printf '%s' "$out" | grep -q "GHOST-REF   I-2"; then
  printf 'RESULT IB%s PASS 对账：真回执判 VERIFIED、编造的 ref 判 GHOST-REF 并退 24\n' "$idx"
else
  fails=$((fails + 1))
  printf 'RESULT IB%s FAIL 对账判定不对 :: got=%s :: %s\n' "$idx" "$got" "$(printf '%s' "$out" | tr '\n' ' ')"
fi

# 回执显示的不是肯定答复 → MISMATCH（"我批了"但宿主记录是拒绝）
printf '{"receipts":[{"interaction_id":"int-7","decision":"reject","by":"human"},{"interaction_id":"int-not-exist","decision":"approve"}]}\n' > "$TMP3/receipts2.json"
out=$(i verify "$TMP3" --receipts "$TMP3/receipts2.json" 2>&1); got=$?
idx=$((idx + 1))
if [ "$got" = 24 ] && printf '%s' "$out" | grep -q "MISMATCH    I-1"; then
  printf 'RESULT IB%s PASS 回执内容与声称相反时判 MISMATCH，不认执行器的一面之词\n' "$idx"
else
  fails=$((fails + 1))
  printf 'RESULT IB%s FAIL MISMATCH 没生效 :: got=%s :: %s\n' "$idx" "$got" "$(printf '%s' "$out" | tr '\n' ' ')"
fi

# 没有任何 ref 的历史/口头批准 → NOT-VERIFIED（退 30），不算批准
printf '{"receipts":[]}\n' > "$TMP3/receipts3.json"
out=$(i verify "$TMP3" --receipts "$TMP3/receipts3.json" 2>&1); got=$?
idx=$((idx + 1))
if [ "$got" = 24 ] && printf '%s' "$out" | grep -q "GHOST-REF"; then
  printf 'RESULT IB%s PASS 空回执集下所有声称批准都掉出 VERIFIED（要么 GHOST-REF 要么 NOT-VERIFIED）\n' "$idx"
else
  fails=$((fails + 1))
  printf 'RESULT IB%s FAIL 空回执集判定不对 :: got=%s :: %s\n' "$idx" "$got" "$(printf '%s' "$out" | tr '\n' ' ')"
fi

# 回执文件坏掉 → 用法错（退 2），不静默当成"全部已核对"
printf 'not json\n' > "$TMP3/bad.json"
expect 2 "回执文件不是合法 JSON 时退 2，不假装核对过" i verify "$TMP3" --receipts "$TMP3/bad.json"

printf '自检 %d 例，失败 %d\n' "$idx" "$fails"
[ "$fails" = 0 ] || exit 1
exit 0
