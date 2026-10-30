#!/bin/sh
# meta-checks 自测：搭一个合成 M1 样本，跑全套元验收并核对其退出码与 SKIP 分布。
# 用法: AUTOPILOT_BASELINE_CHECK=<基线 check.sh 路径> sh meta-checks/meta-checks.selftest.sh
#   基线查找顺序：$AUTOPILOT_BASELINE_CHECK → $AUTOPILOT_BASELINE_SKILL/scripts/check.sh
#                 → $HOME/.autopilot/baseline-0.8/scripts/check.sh（切换时留下的 0.8 快照）
#   一条路都找不到时 M1 会 SKIP（诚实：没对照不宣称等价），
#   其他 10 条必须真 PASS；出现任何 FAIL 或其他 SKIP 一律判自测失败。
# POSIX sh，零第三方依赖，不含任何绝对路径。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

SAMPLE=$(mktemp -d "${TMPDIR:-/tmp}/meta-checks-sample-XXXXXX")
trap 'rm -rf "$SAMPLE"' EXIT
mkdir -p "$SAMPLE/.autopilot/checks" "$SAMPLE/.autopilot/rounds"
printf '# GOAL\n\n（无 FLEX_RULES，等价基线）\n' > "$SAMPLE/.autopilot/GOAL.md"
cat > "$SAMPLE/.autopilot/tasks.json" <<'EOF'
{"epoch":0,"tasks":[
  {"id":"T-01","title":"x","role":"Builder","status":"pending","deps":[],
   "write_set":["src/a.js"],"acceptance":["A1","A2"],"card":".autopilot/tasks/T-01.md"}
]}
EOF
cat > "$SAMPLE/.autopilot/checks/run.sh" <<'EOF'
#!/bin/sh
echo "RESULT A1 PASS schema ok"
echo "RESULT A2 FAIL missing field (elapsed 0.12s)"
exit 0
EOF
chmod +x "$SAMPLE/.autopilot/checks/run.sh"

idx=0
fails=0
ok() { idx=$((idx + 1)); printf 'RESULT T%s PASS %s\n' "$idx" "$1"; }
nope() { idx=$((idx + 1)); fails=$((fails + 1)); printf 'RESULT T%s FAIL %s\n' "$idx" "$1"; }

out=$(AUTOPILOT_META_SAMPLE="$SAMPLE" sh "$HERE/run.sh" 2>&1)
rc=$?

# T1：run.sh 不能有 FAIL
if printf '%s\n' "$out" | grep -q '^RESULT M[0-9]\+ FAIL '; then
  nope "元验收出现 FAIL 判定行"
else
  ok "元验收无 FAIL 判定行"
fi

# T2：run.sh 汇总退出码必须为 0（既无 FAIL；M2-M11 全 PASS，M1 PASS 或 SKIP）
if [ "$rc" = "0" ]; then
  ok "run.sh 汇总退出码 0（无 FAIL）"
else
  nope "run.sh 退出码=$rc（应为 0）"
fi

bad_skip=$(printf '%s\n' "$out" \
  | grep -E '^RESULT M(2|3|4|5|6|7|8|9|10|11) SKIP' || true)
if [ -n "$bad_skip" ]; then
  nope "M2-M11 不应 SKIP :: $(printf '%s' "$bad_skip" | tr '\n' ';')"
else
  ok "M2-M11 全部实跑（无 SKIP）"
fi

# T3：11 条判定行齐备
nlines=$(printf '%s\n' "$out" | grep -Ec '^RESULT M[0-9]+ (PASS|FAIL|SKIP) ')
if [ "$nlines" = "11" ]; then
  ok "11 条判定行齐备"
else
  nope "判定行数=$nlines，应为 11"
fi

# T4：基线查找的三条路全掐断时，M1 必须 SKIP（没对照不宣称等价）
# 基线查找顺序：$AUTOPILOT_BASELINE_CHECK → $AUTOPILOT_BASELINE_SKILL/scripts/check.sh
#              → $HOME/.autopilot/baseline-0.8/scripts/check.sh
# 这里把三条都掐断：清掉两个环境变量，再把 HOME 指到一个空临时目录。
NOBASE_HOME=$(mktemp -d "${TMPDIR:-/tmp}/meta-checks-nobase-XXXXXX")
out_nobase=$(HOME="$NOBASE_HOME" AUTOPILOT_BASELINE_CHECK= AUTOPILOT_BASELINE_SKILL=/nonexistent-baseline \
             AUTOPILOT_META_SAMPLE="$SAMPLE" sh "$HERE/run.sh" 2>&1)
if printf '%s\n' "$out_nobase" | grep -q '^RESULT M1 SKIP'; then
  ok "无基线可用时 M1 走 SKIP（不假绿）"
else
  nope "无基线却非 SKIP：见 M1 行"
fi
rm -rf "$NOBASE_HOME"

# T5：有基线时 M1 必须走真对照（PASS），不能还是 SKIP
have_baseline=""
if [ -n "${AUTOPILOT_BASELINE_CHECK:-}" ] && [ -f "${AUTOPILOT_BASELINE_CHECK:-}" ]; then
  have_baseline="$AUTOPILOT_BASELINE_CHECK"
elif [ -n "${AUTOPILOT_BASELINE_SKILL:-}" ] && [ -f "${AUTOPILOT_BASELINE_SKILL:-}/scripts/check.sh" ]; then
  have_baseline="$AUTOPILOT_BASELINE_SKILL/scripts/check.sh"
elif [ -f "${HOME:-}/.autopilot/baseline-0.8/scripts/check.sh" ]; then
  have_baseline="$HOME/.autopilot/baseline-0.8/scripts/check.sh"
fi
if [ -z "$have_baseline" ]; then
  ok "本机无可用 0.8 基线，M1 走 SKIP（不假绿）"
elif printf '%s\n' "$out" | grep -q '^RESULT M1 PASS'; then
  ok "有基线时 M1 走 PASS（真对照）"
else
  nope "有基线却未 PASS：见 M1 行"
fi

printf '\n# 元验收输出（供人核对）\n'
printf '%s\n' "$out" | sed 's/^/    /'
printf '\n自测 %d 例，失败 %d\n' "$idx" "$fails"
[ "$fails" = 0 ] || exit 1
if [ -z "$have_baseline" ]; then
  printf '>>> 提示：本机没有可用的 0.8 基线，M1 走 SKIP。\n'
  printf '>>>      切换前线上目录就是 0.8；切换后请保留一份快照并指过去：\n'
  printf '>>>      export AUTOPILOT_BASELINE_SKILL=<0.8 技能目录>\n'
fi
exit 0
