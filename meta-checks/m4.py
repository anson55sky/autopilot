#!/usr/bin/env python3
"""M4 run 内提交的 relax 提案不得改变 MANIFEST.sha256。

在 fixture 上：先 freeze → 落一份 relax 提案到 sandbox/proposals/ →
再 freeze 一次，比对 MANIFEST 前后字节一致（提案文件本身不在 checks/ 下，
且 run 内不合并，判定标准不可被写者触碰）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

RELAX_BODY = """# CHANGE_PROPOSAL

```
proposal_id: CP-M4
base_epoch: 0
change_type: relax
affected_a: A1
evidence: sandbox/proposals/EV-M4.log
approved_by: supervisor
approved_at: 2026-01-01T00:00:00+00:00
confirm-A1: yes
```
"""


def main():
    tmp = C.new_tmp("m4-")
    try:
        ap, ch = C.build_checks_repo(tmp, extra={
            "sandbox/proposals/.keep": "",
            "sandbox/proposals/EV-M4.log": "last.log:2 A1 判定过严\n",
        })
        rc, out, err = C.environ("freeze", "--repo", tmp)
        if rc != 0:
            return C.emit(4, "FAIL", f"首次 freeze 未通过 :: {err.strip()[:100]}")
        before = open(os.path.join(ch, "MANIFEST.sha256"), encoding="utf-8").read()

        # run 内提交 relax 提案：只落盘，绝不合并
        C.write(os.path.join(tmp, "sandbox/proposals/CHANGE_PROPOSAL-CP-M4.md"), RELAX_BODY)

        # 提交后：live checks/ 与提案前完全一致 → MANIFEST 应字节不变
        after = open(os.path.join(ch, "MANIFEST.sha256"), encoding="utf-8").read()
        if before != after:
            return C.emit(4, "FAIL", "写提案后 MANIFEST 竟然漂移")

        # 再冻一次（走完整 freeze 路径）也必须给出同一份文本
        rc2, _, err2 = C.environ("freeze", "--repo", tmp)
        if rc2 != 0:
            return C.emit(4, "FAIL", f"重冻结失败 :: {err2.strip()[:100]}")
        again = open(os.path.join(ch, "MANIFEST.sha256"), encoding="utf-8").read()
        if again != before:
            return C.emit(4, "FAIL", "重冻结的 MANIFEST 与首冻不一致（判定被污染）")

        # 提案本身要留在 sandbox/proposals/，不进 checks/、不进 MANIFEST
        if "sandbox/proposals" in before or "CHANGE_PROPOSAL" in before:
            return C.emit(4, "FAIL", "提案文件被误纳入了冻结范围")
        return C.emit(4, "PASS", "run 内 relax 提案对 MANIFEST 零影响（三次冻结字节一致）")
    finally:
        C.cleanup(tmp)


if __name__ == "__main__":
    sys.exit(main())
