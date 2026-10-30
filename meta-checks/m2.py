#!/usr/bin/env python3
"""M2 flex 写主目录被拒且退出码非 0（复用 flex-gate）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def main():
    tmp = C.new_tmp("m2-")
    try:
        ap, ch = C.build_checks_repo(tmp, extra={
            "src/game.js": "console.log(1)\n",
            "sandbox/draft/a.txt": "a\n",
        })
        # 一张 flex-light 卡，写集越界到 src/
        C.write_json(os.path.join(ap, "tasks.json"), {
            "epoch": 0,
            "tasks": [
                {"id": "T-FLX", "title": "flex 越界写主目录", "role": "Builder",
                 "status": "pending", "deps": [], "write_set": ["src/game.js"],
                 "acceptance": [], "card": "c.md", "mode": "flex-light",
                 "sandbox_target": "sandbox/draft"},
            ],
        })
        C.write_json(os.path.join(ap, "state.json"),
                     {"rounds_used": 0, "budget": {"max_calls": 100}})
        rc, out, err = C.flex("check", "--repo", tmp, "--task", "T-FLX")
        if rc == 0:
            return C.emit(2, "FAIL", f"flex 写主目录被放行（应拒）:: {out.strip()[:120]}")
        if rc == 22:
            return C.emit(2, "PASS", f"flex 写主目录 → 红线拒（exit={rc}，非 0）")
        return C.emit(2, "PASS", f"flex 写主目录被拒（exit={rc}，非 0），码={rc}")
    finally:
        C.cleanup(tmp)


if __name__ == "__main__":
    sys.exit(main())
