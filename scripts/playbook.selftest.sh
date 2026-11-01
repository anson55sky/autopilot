#!/bin/sh
# playbook.py 自检（H2/H24/H3）：老格式兼容、元数据召回、字符硬上限、失效链、角色写权限。
# 全部在 mktemp -d 里跑；AUTOPILOT_HOME 也指到临时目录，绝不碰家目录的全局 playbook。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PB="$HERE/playbook.py"
PY=${PYTHON:-python3}

TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPROOT"' EXIT INT TERM
export AUTOPILOT_HOME="$TMPROOT/home"
mkdir -p "$AUTOPILOT_HOME"

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

repo="$TMPROOT/pb"
mkdir -p "$repo/.autopilot"

run() { $PY "$PB" "$@"; }

# ---------------------------------------------------------------- 1 老格式零迁移

cat > "$repo/.autopilot/playbook.md" <<'EOF'
# Playbook

只记「下次还会踩 / 下次还能用」的结论，一条一行。

- [pitfall] 2026-01-01 ×3 · 大卡派给子代理会撞输出上限且零落盘
- [command] 2026-01-02 ×1 · check.sh 是 bash 脚本，必须 bash 而不是 python3
EOF

out=$(run show "$repo" 2>&1)
if printf '%s' "$out" | grep -q "^\[pitfall\] 2026-01-01 ×3  大卡派给子代理会撞输出上限且零落盘$" \
   && printf '%s' "$out" | grep -q "^\[command\] 2026-01-02 ×1  check.sh 是 bash 脚本"; then
  pass 1 "老格式条目 show 输出与 0.9.5 一致（新增元数据是可选的）"
else
  fail 1 "老格式 show 漂移：$out"
fi

out=$(run add "$repo" --kind pitfall --text "大卡派给子代理会撞输出上限且零落盘" 2>&1)
cnt=$(grep -c "×4 · 大卡派给子代理" "$repo/.autopilot/playbook.md")
if printf '%s' "$out" | grep -q "已合并（×4）" && [ "$cnt" = "1" ]; then
  pass 1 "同名去重合并仍然生效（×3 → ×4，不新增行）"
else
  fail 1 "去重合并坏了：$out / ×4 行数=$cnt"
fi

# ---------------------------------------------------------------- 2 元数据与召回

run add "$repo" --kind pitfall --text "护盾计时必须验自然递减" \
    --tags boss,shield --ref A22,A18 >/dev/null 2>&1
out=$(run recall "$repo" --tags shield 2>&1)
if printf '%s' "$out" | grep -q "护盾计时必须验自然递减" && printf '%s' "$out" | grep -q "RECALL 1 条"; then
  pass 2 "按 tags 召回命中且计数正确"
else
  fail 2 "tags 召回不对：$out"
fi
out=$(run recall "$repo" --ref A22 2>&1)
if printf '%s' "$out" | grep -q "护盾计时必须验自然递减"; then
  pass 2 "按 A# 反查召回命中"
else
  fail 2 "ref 召回没命中：$out"
fi
out=$(run recall "$repo" --tags 不存在的标签 2>&1)
if printf '%s' "$out" | grep -q "RECALL 0 命中"; then
  pass 2 "没命中时明确报 0，不假装召回"
else
  fail 2 "空召回文案不对：$out"
fi

# ---------------------------------------------------------------- 3 字符硬上限

run add "$repo" --kind skill --text "$(printf '长文本%.0s' $(seq 1 300))" --tags long >/dev/null 2>&1
out=$(run recall "$repo" --limit 5 --max-chars 20 2>&1)
if printf '%s' "$out" | grep -q "RECALL 0 命中"; then
  pass 3 "预算放不下任何一条时如实报 0，不硬塞"
else
  fail 3 "字符上限没兜住：$out"
fi
out=$(run recall "$repo" --limit 5 --max-chars 120 2>&1)
if printf '%s' "$out" | grep -q "被截断 [1-9]"; then
  pass 3 "超预算的条目计入「被截断」，不静默丢弃"
else
  fail 3 "截断计数缺失：$out"
fi

# ---------------------------------------------------------------- 4 失效链

run add "$repo" --kind pitfall --text "旧结论：连跑两次就够" >/dev/null 2>&1
lst=$(run list "$repo" 2>&1)
last_id=$(printf '%s' "$lst" | tail -1 | awk '{print $1}')
out=$(run invalidate "$repo" --id "$last_id" --note "被 15 次实测推翻" 2>&1)
if printf '%s' "$out" | grep -q "已标失效"; then
  pass 4 "invalidate 能按序号打失效标记"
else
  fail 4 "失效标记失败：$out / $lst"
fi
out=$(run recall "$repo" --kind pitfall 2>&1)
if printf '%s' "$out" | grep -q "旧结论" ; then
  fail 4 "失效条目仍被默认召回"
else
  pass 4 "默认召回过滤失效条目"
fi
out=$(run recall "$repo" --kind pitfall --include-invalid 2>&1)
if printf '%s' "$out" | grep -q "旧结论"; then
  pass 4 "--include-invalid 可审计回溯，失效记录没被删掉"
else
  fail 4 "失效条目被删了而不是标记"
fi
if run list "$repo" --json | $PY -c '
import json, sys
rows = json.load(sys.stdin)
bad = [r for r in rows if r.get("invalid")]
sys.exit(0 if bad else 1)
'; then
  pass 4 "list --json 能查出带失效标记的条目"
else
  fail 4 "list --json 没暴露失效状态"
fi

# ---------------------------------------------------------------- 5 角色写权限

out=$(run add "$repo" --kind pitfall --text "验证者越权写的记忆" --by verifier 2>&1); rc=$?
if [ "$rc" = "31" ] && printf '%s' "$out" | grep -q "不得直接写共享记忆"; then
  pass 5 "Verifier 直接写被拒（退 31），并给出 --suggest 出路"
else
  fail 5 "Verifier 写权限没拦：rc=$rc $out"
fi
out=$(run add "$repo" --kind check --text "验证者提的建议" --by verifier --suggest 2>&1); rc=$?
if [ "$rc" = "0" ] && grep -q "note=suggest" "$repo/.autopilot/playbook.md"; then
  pass 5 "Verifier 可以 --suggest，落盘标成建议态"
else
  fail 5 "建议态写入不对：rc=$rc $out"
fi
out=$(run add "$repo" --kind pitfall --text "builder 直接写" --by builder 2>&1); rc=$?
if [ "$rc" = "31" ]; then
  pass 5 "Builder 也只读（记忆由 Planner/Triage/监督者落笔）"
else
  fail 5 "Builder 写权限没拦：rc=$rc $out"
fi
out=$(run add "$repo" --kind rule --text "监督者写的规则" --by supervisor 2>&1); rc=$?
if [ "$rc" = "0" ]; then
  pass 5 "Planner/Triage/Supervisor 正常写入"
else
  fail 5 "允许角色被误伤：rc=$rc $out"
fi
out=$(run add "$repo" --kind pitfall --text "角色乱写" --by ghost 2>&1); rc=$?
if [ "$rc" = "2" ]; then
  pass 5 "非法角色名退 2，不静默接受"
else
  fail 5 "非法角色没拦：rc=$rc $out"
fi

# ---------------------------------------------------------------- 6 正文不被元数据误吞

run add "$repo" --kind command --text "用法是 a | b 两种写法都行" >/dev/null 2>&1
out=$(run recall "$repo" --kind command --include-invalid 2>&1)
if printf '%s' "$out" | grep -q "用法是 a | b 两种写法都行"; then
  pass 6 "正文里的 \" | \" 不被当成元数据吞掉"
else
  fail 6 "正文被元数据解析误伤：$out"
fi

# ---------------------------------------------------------------- 7 全局层仍可用

run add "$repo" --kind rule --text "跨项目通用约定" --global >/dev/null 2>&1
if [ -f "$AUTOPILOT_HOME/playbook.md" ] && grep -q "跨项目通用约定" "$AUTOPILOT_HOME/playbook.md"; then
  pass 7 "--global 仍写 AUTOPILOT_HOME，不污染项目层"
else
  fail 7 "全局层写入位置不对"
fi
out=$(run show "$repo" --global-only 2>&1)
if printf '%s' "$out" | grep -q "跨项目通用约定" && ! printf '%s' "$out" | grep -q "护盾计时"; then
  pass 7 "--global-only 只看全局层"
else
  fail 7 "global-only 口径不对：$out"
fi

if [ "$FAILED" -gt 0 ]; then
    printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
    exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
