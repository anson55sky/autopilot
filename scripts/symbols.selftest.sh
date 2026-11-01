#!/bin/sh
# H21 只读符号快照自测：A-sy-01..07。全程在 mktemp -d 的假仓库里跑，不碰真项目。
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL=$(cd "$HERE/.." && pwd)
PY=${PYTHON:-python3}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() { FAILED=$((FAILED + 1)); printf 'FAIL %s %s\n' "$1" "$2"; }

REPO="$TMP/repo"
mkdir -p "$REPO/src" "$REPO/.autopilot" "$REPO/node_modules/js" "$REPO/dist"
cat > "$REPO/src/app.py" <<'EOF'
def alpha(x):
    return x

class Beta:
    def gamma(self):
        pass
EOF
cat > "$REPO/src/util.ts" <<'EOF'
export function delta(a: number) { return a }
export class Epsilon {}
EOF
cat > "$REPO/node_modules/js/dep.js" <<'EOF'
function shouldNotAppear() {}
EOF
cat > "$REPO/dist/bundle.js" <<'EOF'
function alsoShouldNotAppear() {}
EOF
cat > "$REPO/.autopilot/goal.md" <<'EOF'
# 目标
终结目标：做出 X
## 验收
- A1 能跑
EOF
printf '{"epoch":0,"tasks":[]}\n' > "$REPO/.autopilot/tasks.json"
printf '{"rounds_used":1,"phase":"build","budget":{"max_rounds":9,"max_calls":90}}\n' \
  > "$REPO/.autopilot/state.json"

SY="$SKILL/scripts/symbols.py"
sum_src() {  # 被测代码指纹：只算 src/，与 .autopilot 无关
    (cd "$REPO" && find src -type f | LC_ALL=C sort | xargs shasum -a 256) | shasum -a 256
}

# ---------------------------------------------------------------- 1 关闭态等价

before=$($PY "$SKILL/scripts/resume.py" "$REPO" 2>&1)
before2=$($PY "$SKILL/scripts/resume.py" "$REPO" 2>&1)
if [ "$before" = "$before2" ] && ! printf '%s' "$before" | grep -q "符号:"; then
  pass 1 "没跑过 scan 时接续包里没有「符号:」这一行，且两次输出逐字节一致"
else
  fail 1 "关闭态不干净：$(printf '%s' "$before" | grep '符号:' | head -1)"
fi

# ---------------------------------------------------------------- 2 只写 .autopilot

src_fp=$(sum_src)
out=$($PY "$SY" scan --repo "$REPO" 2>&1); rc=$?
if [ "$rc" = 0 ] && [ "$(sum_src)" = "$src_fp" ] \
   && [ -f "$REPO/.autopilot/symbols.json" ]; then
  pass 2 "scan 只往 .autopilot 写快照，被测代码指纹一字未动"
else
  fail 2 "scan 动了被测代码或没落快照：rc=$rc $out"
fi

# ---------------------------------------------------------------- 3 确定性与跳过目录

$PY "$SY" scan --repo "$REPO" >/dev/null 2>&1
cp "$REPO/.autopilot/symbols.json" "$TMP/first.json"
$PY "$SY" scan --repo "$REPO" >/dev/null 2>&1
if cmp -s "$TMP/first.json" "$REPO/.autopilot/symbols.json"; then
  pass 3 "同一份代码连扫两次，快照逐字节一致（无时间戳、全排序）"
else
  fail 3 "快照不可复现"
fi
if ! grep -q 'shouldNotAppear' "$REPO/.autopilot/symbols.json" \
   && ! grep -q 'alsoShouldNotAppear' "$REPO/.autopilot/symbols.json"; then
  pass 3 "node_modules / dist 这类产物目录不进快照"
else
  fail 3 "跳过的目录被索引进来了"
fi

# ---------------------------------------------------------------- 4 无 DB / 无常驻

leftovers=$(find "$REPO/.autopilot" -type f \( -name '*.sqlite3*' -o -name '*.db' -o -name '*.lock' \) | wc -l | tr -d ' ')
if [ "${leftovers:-0}" = "0" ] && ! grep -qE '^\s*(import|from)\s+sqlite3' "$SY"; then
  pass 4 "零 DB：不落 .sqlite3/.db/.lock，实现里没有 sqlite3（全局约束 4）"
else
  fail 4 "引入了数据库形态的产物"
fi

# ---------------------------------------------------------------- 5 find 可定位

out=$($PY "$SY" find --repo "$REPO" --symbol gamma 2>&1); rc=$?
loc=$(printf '%s' "$out" | sed -n 's/.*  *\(src\/app.py:[0-9]*\).*/\1/p' | head -1)
line_no=$(printf '%s' "$loc" | cut -d: -f2)
srcfile=$(printf '%s' "$loc" | cut -d: -f1)
if [ "$rc" = 0 ] && [ -n "$loc" ] \
   && sed -n "${line_no:-0}p" "$REPO/$srcfile" 2>/dev/null | grep -q 'def gamma'; then
  pass 5 "find 给出的 file:line 真的指向定义那一行"
else
  fail 5 "find 定位不了：rc=$rc loc=$loc"
fi

mkdir -p "$TMP/emptyrepo/.autopilot"
miss=$($PY "$SY" find --repo "$TMP/emptyrepo" --symbol whatever 2>&1); rc2=$?
if [ "$rc2" = 2 ] && printf '%s' "$miss" | grep -q "没有符号快照"; then
  pass 5 "没有快照时退 2 并说明原因，绝不假装扫过"
else
  fail 5 "无快照时没拦住：rc=$rc/$rc2 $miss"
fi

# ---------------------------------------------------------------- 6 上限截断要声明

out=$($PY "$SY" scan --repo "$REPO" --max-defs 2 2>&1)
brief=$($PY "$SY" brief --repo "$REPO" 2>&1)
if printf '%s' "$out" | grep -q "已截断" && printf '%s' "$brief" | grep -q "⚠"; then
  pass 6 "触到 --max-defs 时快照声明 truncated，brief 把「不完整」带到接续包口径里"
else
  fail 6 "截断没声明：$out / $brief"
fi

# ---------------------------------------------------------------- 7 打开态才多一行

$PY "$SY" scan --repo "$REPO" >/dev/null 2>&1
after=$($PY "$SKILL/scripts/resume.py" "$REPO" 2>&1)
if printf '%s' "$after" | grep -q "^符号:" \
   && [ "$(printf '%s' "$after" | grep -v '^符号:')" = "$before" ]; then
  pass 7 "跑过 scan 后接续包只多一行「符号:」，其余内容与关闭态逐字节相同"
else
  fail 7 "打开态改动超出了一行"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
