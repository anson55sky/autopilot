#!/usr/bin/env python3
"""H33② 像素基线对照：把"截图字节数一样"换成"像素差在阈值内"。

为什么要有它：视觉类验收此前只断言截图字节数与探针 JSON，**抓不到渲染错乱**——
ContraRunner v1 报告 §4 的实证就是这类断言放过了 DOM 浮层压住 HUD。几何判据（①）由
`templates/checks/probe-geometry.mjs` 负责，本工具负责另一半：与基线图的像素差占比。

只用标准库：PNG 解码自己实现（8-bit RGB/RGBA、非隔行、过滤类型 0–4 全支持），
不引 PIL/numpy（全局约束：零第三方依赖）。**读不了的图就退 3，绝不判过**。

用法:
  python3 tools/pixel_diff.py --baseline a.png --current b.png \
      [--threshold 0.002] [--channel-tol 8] [--mask x,y,w,h [--mask ...]] [--json]

退出码：0 差占比 ≤ 阈值（PASS）· 1 超阈值（FAIL）· 2 用法 · 3 解不出图（判 SKIP，不判过）。
输出首行 `PIXEL <码> <说明>`，可直接被 run.sh 转成 RESULT 行。
"""

import argparse
import json
import struct
import sys
import zlib

E_OK, E_OVER, E_USAGE, E_UNDECODE = 0, 1, 2, 3
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_PIXELS = 40_000_000      # 4000 万像素封顶，超大图直接退 3，不把自己撑爆


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw, w, h, bpp):
    stride = w * bpp
    if len(raw) < h * (stride + 1):
        raise ValueError("IDAT 长度不足")
    out = bytearray(stride)
    rows = []
    for y in range(h):
        line = raw[y * (stride + 1): y * (stride + 1) + stride + 1]
        ft = line[0]
        cur = bytearray(line[1:])
        if ft == 1:
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
        elif ft == 2:
            prev = out
            for i in range(stride):
                cur[i] = (cur[i] + prev[i]) & 0xFF
        elif ft == 3:
            prev = out
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            prev = out
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + _paeth(a, prev[i], c)) & 0xFF
        elif ft != 0:
            raise ValueError("未知过滤类型 %d" % ft)
        out = cur
        rows.append(bytes(cur))
    return b"".join(rows)


def read_png(path):
    """返回 (width, height, channels, bytes)。只支持 8-bit、非隔行、colortype 2/6。"""
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(PNG_MAGIC):
        raise ValueError("不是 PNG")
    pos = len(PNG_MAGIC)
    ihdr = None
    idat = bytearray()
    while pos + 8 <= len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if ctype == b"IHDR":
            ihdr = chunk
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
    if ihdr is None or len(ihdr) < 13:
        raise ValueError("缺 IHDR")
    w, h, depth, color, interlace = struct.unpack(">IIBBB", ihdr[:11])
    if depth != 8 or interlace != 0:
        raise ValueError("只支持 8-bit 非隔行（当前 depth=%d interlace=%d）" % (depth, interlace))
    chan = {2: 3, 6: 4}.get(color)
    if chan is None:
        raise ValueError("只支持 colortype 2/6（当前 %d）" % color)
    if w * h > MAX_PIXELS:
        raise ValueError("图太大（%dx%d）" % (w, h))
    raw = zlib.decompress(bytes(idat))
    return w, h, chan, _unfilter(raw, w, h, chan)


def in_masks(x, y, masks):
    for (mx, my, mw, mh) in masks:
        if mx <= x < mx + mw and my <= y < my + mh:
            return True
    return False


def diff(baseline, current, masks, channel_tol):
    wb, hb, cb, pb = read_png(baseline)
    wc, hc, cc, pc = read_png(current)
    if (wb, hb) != (wc, hc):
        return None, None, "尺寸不一致 %dx%d vs %dx%d" % (wb, hb, wc, hc)
    total = wb * hb
    cmp_ch = min(cb, cc)
    differing = 0
    worst = 0
    for y in range(hb):
        for x in range(wb):
            if masks and in_masks(x, y, masks):
                continue
            i = (y * wb + x) * cb
            j = (y * wb + x) * cc
            md = max(abs(pb[i + k] - pc[j + k]) for k in range(cmp_ch))
            if md > worst:
                worst = md
            if md > channel_tol:
                differing += 1
    return float(differing) / total, worst, None


def main():
    ap = argparse.ArgumentParser(prog="pixel_diff.py")
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--current", required=True)
    ap.add_argument("--threshold", type=float, default=0.002)
    ap.add_argument("--channel-tol", type=int, default=8)
    ap.add_argument("--mask", action="append", default=[], help="x,y,w,h（可重复）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    masks = []
    for m in a.mask:
        parts = [p.strip() for p in m.split(",")]
        if len(parts) != 4:
            print("PIXEL 2 --mask 需要 4 个数 x,y,w,h，收到 %s" % m)
            return E_USAGE
        masks.append(tuple(int(p) for p in parts))
    try:
        ratio, worst, err = diff(a.baseline, a.current, masks, a.channel_tol)
    except (OSError, ValueError, zlib.error) as exc:
        print("PIXEL 3 解不出图，判 SKIP 不判过 :: %s" % exc)
        return E_UNDECODE
    if err:
        print("PIXEL 3 两图不可比，判 SKIP 不判过 :: %s" % err)
        return E_UNDECODE
    code = E_OK if ratio <= a.threshold else E_OVER
    verdict = "PASS" if code == E_OK else "FAIL"
    if a.json:
        print(json.dumps({"diff_ratio": round(ratio, 6), "worst_channel_delta": worst,
                          "threshold": a.threshold, "channel_tol": a.channel_tol,
                          "masks": len(masks), "verdict": verdict}, ensure_ascii=False))
    print("PIXEL %d %s 像素差占比 %.4f%%（阈值 %.4f%%）· 最大单通道差 %s · 遮罩 %d 块"
          % (code, verdict, ratio * 100.0, a.threshold * 100.0, worst, len(masks)))
    return code


if __name__ == "__main__":
    sys.exit(main())
