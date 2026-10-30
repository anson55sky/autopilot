#!/usr/bin/env python3
"""M7 三哈希实现对同一文件产出逐字节相同的一行（复用 environ 实现）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

IMPLS = ("shasum", "sha256sum", "python")


def main():
    tmp = C.new_tmp("m7-")
    try:
        C.build_checks_repo(tmp)
        target = os.path.join(tmp, "src", "blob.bin")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(bytes(range(256)) * 37)
        lines, available = [], []
        for impl in IMPLS:
            rc, out, _ = C.environ("hash", "--repo", tmp,
                                   "--file", os.path.relpath(target, tmp),
                                   "--impl", impl,
                                   "--display", "./blob.bin")
            if rc == 0:
                available.append(impl)
                lines.append(out.strip())
        if len(available) < 2:
            return C.emit(7, "SKIP",
                          f"本机可用哈希实现不足（{available}），不做一致性宣称")
        uniq = set(lines)
        if len(uniq) == 1 and len(available) == len(IMPLS):
            return C.emit(7, "PASS", f"{len(available)}/3 实现逐字节相同: {lines[0][:80]}")
        if len(uniq) == 1:
            return C.emit(7, "PASS",
                          f"可用 {len(available)} 实现逐字节相同（本机缺 "
                          f"{set(IMPLS)-set(available)}）: {lines[0][:60]}")
        return C.emit(7, "FAIL", f"哈希实现产出不一致: {sorted(uniq)}")
    finally:
        C.cleanup(tmp)


if __name__ == "__main__":
    sys.exit(main())
