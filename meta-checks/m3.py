#!/usr/bin/env python3
"""M3 r-XX.json 的 passed 若来自非冻结验收来源（如 sandbox/proposals/）→ 判 FAIL。

红线条款：`r-XX.passed` 只能来自冻结 run.sh 的 RESULT 行（Explorer 结论不得冒充主验收）。
检测器 passed_source_ok() 是纯函数，自测用构造的正/反例证明它有效。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

# 冻结 run.sh 的合法证据来源（项目相对）
FROZEN_SOURCES = ("checks/last-result.json", "checks/last.log",
                  ".autopilot/checks/last-result.json", ".autopilot/checks/last.log")


def passed_source_ok(doc):
    """返回 (ok:bool, reason:str)。ok=False 表示 passed 来源不可信（非冻结验收）。"""
    src = doc.get("passed_source")
    if src is None:
        # 没声明来源：只有当它完全不带 passed 时才安全；带 passed 却没来源 = 可疑
        if doc.get("passed"):
            return False, "passed 非空但缺 passed_source（来源不明）"
        return True, "无 passed，无需来源"
    s = str(src).strip()
    if s in FROZEN_SOURCES:
        return True, f"来源为冻结验收产物 {s}"
    # 明确的可疑来源
    low = s.lower()
    if low.startswith("sandbox/") or "proposals/" in low or "explorer" in low:
        return False, f"passed 引用非冻结来源（探索/提案）: {s}"
    return False, f"passed 来源不在冻结白名单: {s}"


def main():
    good = {"round": 1, "epoch": 0, "passed": ["A1", "A7"],
            "passed_source": "checks/last-result.json"}
    bad = {"round": 2, "epoch": 0, "passed": ["A1"],
           "passed_source": "sandbox/proposals/explorer-review.md"}
    no_src = {"round": 3, "epoch": 0, "passed": ["A1"]}

    ok_g, rg = passed_source_ok(good)
    ok_b, rb = passed_source_ok(bad)
    ok_n, rn = passed_source_ok(no_src)

    # 自测：检测器必须放行合法来源、拦下提案来源与无来源
    if ok_g and (not ok_b) and (not ok_n):
        # 再用它扫一遍 rounds/ 目录（若 fixture 里放了反例）
        tmp = C.new_tmp("m3-")
        try:
            ap, _ = C.build_checks_repo(tmp)
            rd = os.path.join(ap, "rounds")
            C.write_json(os.path.join(rd, "r-01.json"), good)
            C.write_json(os.path.join(rd, "r-02.json"), bad)
            offenders = []
            for fn in sorted(os.listdir(rd)):
                d = C.read_json(os.path.join(rd, fn), {}) or {}
                ok, reason = passed_source_ok(d)
                if not ok:
                    offenders.append((fn, reason))
            C.cleanup(tmp)
            if offenders and offenders[0][0] == "r-02.json":
                return C.emit(3, "PASS",
                              f"检测器有效：放行冻结来源、拦下 {len(offenders)} 个非冻结来源")
            return C.emit(3, "FAIL", f"目录扫描未准确拦下反例: {offenders}")
        finally:
            C.cleanup(tmp)
    detail = f"good_ok={ok_g}({rg}) bad_ok={ok_b}({rb}) nosrc_ok={ok_n}({rn})"
    return C.emit(3, "FAIL", f"passed_source 检测器判定错误 :: {detail}")


if __name__ == "__main__":
    sys.exit(main())
