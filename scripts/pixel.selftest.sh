#!/bin/sh
# H33② 像素基线对照自测：A-px-01..07。图片全部现场生成（zlib + 手写 chunk），不引第三方库。
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

PD="$SKILL/tools/pixel_diff.py"

# 生成器：$1 路径 $2 宽 $3 高 $4 改动像素数 $5 过滤类型 $6 colortype(6=RGBA,0=灰度)
gen() {
$PY - "$@" <<'PY'
import struct, sys, zlib
path, w, h, changed, ftype, color = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
chan = 4 if color == 6 else 1
rows = []
for y in range(h):
    row = bytearray()
    for x in range(w):
        v = 10 if (y * w + x) < changed else 0
        row += bytes([v, 60, 120, 255][:chan] if chan == 4 else [v])
    rows.append(bytes(row))
stride = w * chan
raw = bytearray()
prev = bytes(stride)
for i, r in enumerate(rows):
    if ftype == 0:
        line = r
    elif ftype == 2:                     # Up：与上一行相加还原
        line = bytes((r[k] - prev[k]) & 0xFF for k in range(stride))
    elif ftype == 4:                     # Paeth：按预测差写，解码端能还原即可
        line = bytearray(stride)
        for k in range(stride):
            a = r[k - chan] if k >= chan else 0
            b = prev[k]
            c = prev[k - chan] if k >= chan else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            line[k] = (r[k] - pr) & 0xFF
        line = bytes(line)
    else:
        raise SystemExit("bad filter")
    raw.append(ftype)
    raw += line
    prev = r
def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, color, 0, 0, 0)) \
      + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")
open(path, "wb").write(png)
PY
}

# ---------------------------------------------------------------- 1 完全相同 → 0 差

gen "$TMP/a.png" 20 10 0 0 6
cp "$TMP/a.png" "$TMP/b.png"
out=$($PY "$PD" --baseline "$TMP/a.png" --current "$TMP/b.png" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "PASS 像素差占比 0.0000%"; then
  pass 1 "同图比对差占比为 0（而不是「字节相同才算同」）"
else
  fail 1 "同图判错：rc=$rc $out"
fi

# ---------------------------------------------------------------- 2 改动被算出来

gen "$TMP/c.png" 20 10 40 0 6            # 200 像素里改了 40 个 = 20%
out=$($PY "$PD" --baseline "$TMP/a.png" --current "$TMP/c.png" --threshold 0.002 2>&1); rc=$?
if [ "$rc" = 1 ] && printf '%s' "$out" | grep -q "FAIL 像素差占比 20.0000%"; then
  pass 2 "改动占比真算出来了（20%），并且超阈值退 1"
else
  fail 2 "差值算错：rc=$rc $out"
fi

# ---------------------------------------------------------------- 3 阈值内放行

gen "$TMP/d.png" 20 10 1 0 6             # 只改 1 个像素 = 0.5%
out=$($PY "$PD" --baseline "$TMP/a.png" --current "$TMP/d.png" --threshold 0.01 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "PASS"; then
  pass 3 "阈值内放行（0.5% ≤ 1%），噪声不炸红"
else
  fail 3 "阈值判定不对：rc=$rc $out"
fi

# ---------------------------------------------------------------- 4 遮罩排除动态区

out=$($PY "$PD" --baseline "$TMP/a.png" --current "$TMP/c.png" --mask 0,0,20,1 --threshold 0.002 2>&1); rc=$?
if [ "$rc" = 1 ] && printf '%s' "$out" | grep -q "遮罩 1 块" \
   && printf '%s' "$out" | grep -q "占比 10.0000%"; then
  pass 4 "遮罩块内的差异被排除：改动 40 像素遮掉一行后占比从 20% 降到 10%"
else
  fail 4 "遮罩不生效：rc=$rc $out"
fi

# ---------------------------------------------------------------- 5 过滤类型都能解

gen "$TMP/e.png" 20 10 0 2 6
out=$($PY "$PD" --baseline "$TMP/a.png" --current "$TMP/e.png" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "0.0000%"; then
  pass 5 "Up 过滤的 PNG 解码正确（与 filter0 编码的同内容图零差）"
else
  fail 5 "Up 过滤解错：rc=$rc $out"
fi
gen "$TMP/f.png" 20 10 0 4 6
out=$($PY "$PD" --baseline "$TMP/a.png" --current "$TMP/f.png" 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "0.0000%"; then
  pass 6 "Paeth 过滤的 PNG 解码正确"
else
  fail 6 "Paeth 过滤解错：rc=$rc $out"
fi

# ---------------------------------------------------------------- 7 解不了/不可比 → SKIP，绝不判过

gen "$TMP/g.png" 20 10 0 0 0             # 灰度：本工具不支持
out=$($PY "$PD" --baseline "$TMP/a.png" --current "$TMP/g.png" 2>&1); rc=$?
printf 'not a png\n' > "$TMP/h.png"
out2=$($PY "$PD" --baseline "$TMP/a.png" --current "$TMP/h.png" 2>&1); rc2=$?
gen "$TMP/i.png" 30 10 0 0 6
out3=$($PY "$PD" --baseline "$TMP/a.png" --current "$TMP/i.png" 2>&1); rc3=$?
if [ "$rc" = 3 ] && [ "$rc2" = 3 ] && [ "$rc3" = 3 ] \
   && printf '%s' "$out" | grep -q "判 SKIP 不判过" && printf '%s' "$out3" | grep -q "尺寸不一致"; then
  pass 7 "不支持的色深、坏文件、尺寸不一致统统退 3 并明写「判 SKIP 不判过」"
else
  fail 7 "异常输入处理不对：rc=$rc/$rc2/$rc3"
fi

if [ "$FAILED" -gt 0 ]; then
  printf '== 失败 %s 项（通过 %s 项）==\n' "$FAILED" "$PASSED"
  exit 1
fi
printf '== 全部通过（%s 项断言）==\n' "$PASSED"
exit 0
