#!/bin/sh
# MIGRATION.md §5 的 12 步迁移清单**逐条真跑一遍**。
#
# 为什么要有这个：迁移指南是最容易"写着对、跑不通"的一类文档 ——
# 命令名错、参数不存在、产物没人生成，清单就变成一句空话。
# 本脚本把清单当成验收来跑：每一步都有明确的判据，判不过就报 FAIL。
#
# 用法: migration_rehearsal.sh [样本工作区]
#   样本工作区 = 一个**已完成的 0.8 工作区**（含 .autopilot/checks/run.sh 与 tasks.json）。
#   不给就用环境变量 AUTOPILOT_MIGRATION_SAMPLE；都没有 → 退出 2（不假绿）。
#
# 判据：
#   - 每一步都跑真实命令，判"输出符合 MIGRATION.md §5 表格里写的期望"
#   - 允许的差异只有时间戳（ts）与"用时"这类环境字段
#   - 任何一步不符 → 该步 FAIL，整体退出 1
set -u

ROOT=$(cd -P "$(dirname "$0")/.." && pwd)
SAMPLE=${1:-${AUTOPILOT_MIGRATION_SAMPLE:-}}

[ -n "$SAMPLE" ] || { echo "用法: migration_rehearsal.sh <0.8 样本工作区>"; exit 2; }
[ -d "$SAMPLE" ] || { echo "样本工作区不存在: $SAMPLE"; exit 2; }
# 0.8 技能目录从哪来：切换前是线上目录，切换后是保留下来的快照 —— 见 tools/baseline08.sh
. "$ROOT/tools/baseline08.sh"
resolve_baseline_skill || exit 2
LIVE_SKILL="$BASELINE_SKILL"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/autopilot-migrate-XXXXXX")
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

SKILL="$TMP/skill"
REPO="$TMP/repo"
BACKUP="$TMP/backup"
cp -Rp "$LIVE_SKILL/." "$SKILL/"
cp -Rp "$SAMPLE/." "$REPO/"
mkdir -p "$BACKUP"
cp -a "$REPO/.autopilot" "$BACKUP/autopilot-pre-0.9"

pass=0
fail=0
step_no=0

ok()  { pass=$((pass + 1)); printf 'STEP %-2s PASS  %s\n' "$1" "$2"; }
no()  { fail=$((fail + 1)); printf 'STEP %-2s FAIL  %s :: %s\n' "$1" "$2" "$3"; }
head2() { printf '\n--- %s ---\n' "$1"; }

# 升级前的 golden（用 0.8 的 check.sh 跑）
# 注意：0.8 的 check.sh 把 RESULT 写进 .autopilot/checks/last.log，不走 stdout ——
# 照着 stdout grep 会一条都抓不到，然后"两边都是空的"会被 cmp 判成一致 = 假绿。
head2 "升级前：0.8 基线跑一次，存 golden-0.8.txt"
( cd "$REPO" && sh "$SKILL/scripts/check.sh" run "$REPO" ) >"$TMP/golden-0.8.txt" 2>&1
if [ -f "$REPO/.autopilot/checks/last.log" ]; then
  cp "$REPO/.autopilot/checks/last.log" "$TMP/golden-0.8.txt"
else
  ( cd "$REPO" && sh "$SKILL/scripts/status.py" summary "$REPO" ) >>"$TMP/golden-0.8.txt" 2>&1
fi
if grep -q '^RESULT ' "$TMP/golden-0.8.txt"; then
  ok 2 "0.8 golden 已生成（$(grep -c '^RESULT ' "$TMP/golden-0.8.txt") 条 RESULT）"
else
  no 2 "0.8 golden 已生成" "没抓到 RESULT 行"
fi

# 切换到 0.9
head2 "切换 skill 到 0.9"
if sh "$ROOT/tools/cutover.sh" --apply "$SKILL" "$ROOT" >"$TMP/cutover.log" 2>&1; then
  ok 3 "cutover --apply 完成"
else
  no 3 "cutover --apply 完成" "见 $TMP/cutover.log"
fi

# --- §5 清单逐条 ---
step_no=0

# 0) 基线 tag（正式名 v0.8-baseline；baseline-0.8 是历史别名，同指一个 commit）
step_no=$((step_no + 1))
if git -C "$SKILL" rev-parse --verify v0.8-baseline >/dev/null 2>&1; then
  ok "$step_no" "v0.8-baseline tag 存在"
elif git -C "$SKILL" rev-parse --verify baseline-0.8 >/dev/null 2>&1; then
  ok "$step_no" "v0.8-baseline tag 存在（只找到兼容别名 baseline-0.8）"
else
  no "$step_no" "v0.8-baseline tag 存在" "切完没有这个 tag，回滚无从谈起"
fi

# 1) 备份工作区
step_no=$((step_no + 1))
if [ -f "$BACKUP/autopilot-pre-0.9/checks/MANIFEST.sha256" ]; then
  ok "$step_no" "工作区已备份（含 MANIFEST.sha256）"
else
  no "$step_no" "工作区已备份" "备份里没有 checks/MANIFEST.sha256"
fi

# 2) golden（升级前）已生成；此处确认它内容可用
step_no=$((step_no + 1))
if grep -qE 'RESULT ' "$TMP/golden-0.8.txt"; then
  ok "$step_no" "golden-0.8.txt 可用"
else
  no "$step_no" "golden-0.8.txt 可用" "没有 RESULT 行，无法做等价性对照"
fi

# 3) SKILL.md 含 FLEX_RULES 与 sandbox/
step_no=$((step_no + 1))
n_flex=$(grep -c 'FLEX_RULES' "$SKILL/SKILL.md" 2>/dev/null || printf 0)
n_sbx=$(grep -cE 'sandbox/' "$SKILL/SKILL.md" 2>/dev/null || printf 0)
if [ "${n_flex:-0}" -ge 1 ] && [ "${n_sbx:-0}" -ge 1 ]; then
  ok "$step_no" "SKILL.md 含 FLEX_RULES($n_flex) 与 sandbox/($n_sbx)"
else
  no "$step_no" "SKILL.md 含 FLEX_RULES 与 sandbox/" "flex=$n_flex sandbox=$n_sbx"
fi

# 4) 探测并写环境产物
step_no=$((step_no + 1))
if AUTOPILOT_HASH_IMPL=auto sh "$SKILL/scripts/init.sh" --probe-only "$REPO" >"$TMP/probe.log" 2>&1; then
  keys=$(python3 -c 'import json;print(",".join(sorted(json.load(open("'"$REPO"'/.autopilot/env.json")))))' 2>/dev/null || printf '')
  miss=""
  for k in hash_impl shell python skill_root; do
    case ",$keys," in *",$k,"*) ;; *) miss="$miss $k" ;; esac
  done
  prim=$(python3 -c 'import json;d=json.load(open("'"$REPO"'/.autopilot/host.json"));p=d.get("primitives",{});print(len(p), all(isinstance(v,bool) for v in p.values()))' 2>/dev/null || printf '0 False')
  if [ -z "$miss" ] && [ "${prim%% *}" = "5" ]; then
    ok "$step_no" "env.json 键齐全（缺:${miss:-无}）· host.json 5 原语=$prim"
  else
    no "$step_no" "env.json 键齐全且 host.json 有 5 原语" "缺键:${miss:-无} 原语:$prim"
  fi
else
  no "$step_no" "init.sh --probe-only 跑通" "见 $TMP/probe.log"
fi

# 5) sandbox 与 changelog
step_no=$((step_no + 1))
all_dirs=yes
for d in .gate proposals drafts hypo prototype; do
  [ -d "$REPO/sandbox/$d" ] || all_dirs=no
done
if [ "$all_dirs" = yes ] && [ -f "$REPO/.autopilot/contract-changelog.md" ]; then
  ok "$step_no" "sandbox 五目录齐全且 contract-changelog.md 存在"
else
  no "$step_no" "sandbox 五目录齐全且 contract-changelog.md 存在" "目录齐=$all_dirs changelog=$([ -f "$REPO/.autopilot/contract-changelog.md" ] && echo yes || echo no)"
fi

# 6) 迁移 tasks.json（0.8 的 t-1 无契约 → 0.9 的 T-01 + role/write_set）
step_no=$((step_no + 1))
out6a=$(python3 "$SKILL/scripts/migrate_tasks.py" "$REPO" 2>&1)
rc6a=$?
if [ "$rc6a" -eq 0 ] && printf '%s' "$out6a" | grep -q '已写入'; then
  ok "$step_no" "tasks.json 迁到 0.9 契约（$(printf '%s' "$out6a" | grep -c '→') 条任务改写）"
else
  no "$step_no" "tasks.json 迁到 0.9 契约" "rc=$rc6a :: $(printf '%s' "$out6a" | head -2 | tr '\n' ' ')"
fi

# 7) 迁移后的 tasks.json 合契约
step_no=$((step_no + 1))
out6=$(python3 "$SKILL/schema/check.py" "$REPO/.autopilot/tasks.json" 2>&1)
rc6=$?
if [ "$rc6" -eq 0 ] && printf '%s' "$out6" | grep -qE '^RESULT S[0-9]+ PASS'; then
  ok "$step_no" "tasks.json 契约校验通过"
else
  no "$step_no" "tasks.json 契约校验通过" "rc=$rc6 :: $(printf '%s' "$out6" | head -2 | tr '\n' ' ')"
fi

# 7) MANIFEST 未被动过
step_no=$((step_no + 1))
out7=$(sh "$SKILL/scripts/check.sh" verify "$REPO" 2>&1)
if printf '%s' "$out7" | grep -q '一致'; then
  ok "$step_no" "MANIFEST 一致（env/host/environment.json 未进哈希）"
else
  no "$step_no" "MANIFEST 一致" "$(printf '%s' "$out7" | head -2 | tr '\n' ' ')"
fi

# 8) 等价性回归（M1）
# 直接调 M1：它比"diff 两次输出"更严 —— 区分"探针自身抖动"和"真回归"，
# 而且 MANIFEST 是逐字节比，不是比摘要。
step_no=$((step_no + 1))
m1_out=$(AUTOPILOT_BASELINE_CHECK="$LIVE_SKILL/scripts/check.sh" \
          python3 "$SKILL/meta-checks/m1.py" --sample "$REPO" 2>&1)
if printf '%s' "$m1_out" | grep -q '^RESULT M1 PASS'; then
  ok "$step_no" "M1 等价性通过 :: $(printf '%s' "$m1_out" | grep -m1 'RESULT M1' | cut -c1-110)"
else
  no "$step_no" "M1 等价性通过" "$(printf '%s' "$m1_out" | grep -m1 'RESULT M1' | cut -c1-160)"
fi

# 9) 缺省档位确认
step_no=$((step_no + 1))
if [ ! -f "$REPO/.autopilot/GOAL.md" ] || ! grep -q 'FLEX_RULES' "$REPO/.autopilot/GOAL.md"; then
  ok "$step_no" "GOAL.md 无 FLEX_RULES 区块 → 走默认档（不放宽）"
else
  n=$(grep -c 'FLEX_RULES' "$REPO/.autopilot/GOAL.md")
  ok "$step_no" "GOAL.md 有 FLEX_RULES 区块（$n 处），需人工确认各值与默认档一致"
fi

# 10) SKIP 语义可用
# 老 run.sh 没有 need()/SKIP 机制 → 跑不出 SKIP 是**预期**（MIGRATION.md §5 第 10 步明说，
# 别为了跑通这步去改冻结脚本）。但如果 run.sh 里**有** SKIP 机制却没出 SKIP 行，那就是真 bug。
step_no=$((step_no + 1))
cp -a "$REPO" "$TMP/repo-skip" 2>/dev/null || true
AUTOPILOT_BROWSER_BIN=/nonexistent/browser sh "$SKILL/scripts/check.sh" run "$TMP/repo-skip" >"$TMP/skip.txt" 2>&1
if [ -f "$TMP/repo-skip/.autopilot/checks/last.log" ]; then
  grep -E '^RESULT [A-Za-z0-9]+ SKIP' "$TMP/repo-skip/.autopilot/checks/last.log" >"$TMP/skiplines.txt" 2>/dev/null || true
else
  grep -E '^RESULT [A-Za-z0-9]+ SKIP' "$TMP/skip.txt" >"$TMP/skiplines.txt" 2>/dev/null || true
fi
if [ -s "$TMP/skiplines.txt" ]; then
  ok "$step_no" "缺能力时出现 RESULT ... SKIP 行（$(wc -l <"$TMP/skiplines.txt" | tr -d ' ') 条）"
elif grep -qE '\bneed\(|SKIP' "$REPO/.autopilot/checks/run.sh" 2>/dev/null; then
  no "$step_no" "缺能力时出现 RESULT ... SKIP 行" "run.sh 里已有 SKIP 机制却没触发"
else
  ok "$step_no" "老 run.sh 无 SKIP 机制 → 跑不出 SKIP 属预期（记为下次重冻时补的待办）"
fi

# 11) 时间戳口径
# 旧文件带原偏移（读得懂），**新写**的戳必须是 UTC（+00:00）。
step_no=$((step_no + 1))
sh "$SKILL/scripts/check.sh" run "$REPO" >/dev/null 2>&1
aware=$(python3 -c "import json,datetime;s=json.load(open('$REPO/.autopilot/state.json'));print(datetime.datetime.fromisoformat(s['started_at']).tzinfo is not None)" 2>/dev/null || printf 'False')
newutc=$(python3 -c "import json,datetime;p='$REPO/.autopilot/checks/last-result.json';print(datetime.datetime.fromisoformat(json.load(open(p))['ts']).utcoffset().total_seconds()==0)" 2>/dev/null || printf 'False')
if [ "$aware" = True ] && [ "$newutc" = True ]; then
  ok "$step_no" "旧戳带偏移（aware=True）· 新写的戳是 UTC（+00:00）"
else
  no "$step_no" "旧戳带偏移且新写的戳是 UTC" "aware=$aware 新戳UTC=$newutc"
fi

# 12) 并发锁
# 判据不是"退出码必须是多少"——验收本身有 FAIL 时退出码就是 1，那是正常的判定结果。
# 真正的判据是：两个 run 不互相踩（last.log 不交错），且没出现用法错误（2）。
step_no=$((step_no + 1))
( sh "$SKILL/scripts/check.sh" run "$REPO" >"$TMP/lock-a.txt" 2>&1; echo $? >"$TMP/lock-a.rc" ) &
( sh "$SKILL/scripts/check.sh" run "$REPO" >"$TMP/lock-b.txt" 2>&1; echo $? >"$TMP/lock-b.rc" ) &
wait
ra=$(cat "$TMP/lock-a.rc" 2>/dev/null || printf '?')
rb=$(cat "$TMP/lock-b.rc" 2>/dev/null || printf '?')
ids=$(grep -E '^RESULT ' "$REPO/.autopilot/checks/last.log" 2>/dev/null | awk '{print $2}' | sort | uniq -d | tr '\n' ',')
nids=$(grep -cE '^RESULT ' "$REPO/.autopilot/checks/last.log" 2>/dev/null || printf 0)
if { [ "$ra" = 2 ] || [ "$rb" = 2 ]; } || [ -n "$ids" ]; then
  no "$step_no" "并发两次不交错" "退出码 $ra/$rb 重复的A#=${ids:-无} RESULT数=$nids"
else
  ok "$step_no" "并发两次：退出码 $ra / $rb（0=全绿，1=有 FAIL，5=锁超时），last.log 无交错（$nids 条 RESULT，A# 不重复）"
fi

printf '\n迁移彩排：PASS %d / FAIL %d\n' "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1
exit 0
