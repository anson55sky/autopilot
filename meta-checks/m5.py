#!/usr/bin/env python3
"""M5 伪造"无浏览器"环境 → 相关 A# 走 SKIP 且全绿判定不成立（调 environ 的 probe/require）。"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

NO_BROWSER = {"AUTOPILOT_NO_CAPS": "browser"}


def all_green(result_lines):
    """B3 定义：无 FAIL 且无 SKIP。"""
    return (not any(s == "FAIL" for _, s in result_lines)) \
        and (not any(s == "SKIP" for _, s in result_lines))


def simulate_run_with_skip(run_log, skipped):
    """把 skipped_acceptance 里的 A# 转成 SKIP 行、其余沿用 run.sh 的 RESULT。"""
    lines = run_log.splitlines()
    out = []
    seen = set()
    for ln in lines:
        m = re.match(r"^\s*RESULT\s+(\S+)\s+(PASS|FAIL|SKIP)\b", ln)
        if m:
            out.append((m.group(1), m.group(2)))
            seen.add(m.group(1))
    for aid in skipped:
        if aid not in seen:
            out.append((aid, "SKIP"))
    return out


def main():
    tmp = C.new_tmp("m5-")
    try:
        ap, ch = C.build_checks_repo(
            tmp,
            run_sh_body="#!/bin/sh\nRESULT A1 PASS ok\nexit 0\n",
            extra={".autopilot/acceptance-needs.json":
                       json.dumps({"A99": ["browser"]})})
        # probe with fake no-browser
        rc, out, err = C.environ("probe", "--repo", tmp, env=NO_BROWSER)
        if rc != 0:
            return C.emit(5, "FAIL", f"probe 失败 :: {err.strip()[:100]}")
        env_doc = C.read_json(os.path.join(os.path.dirname(ch), "environment.json"), {}) or {}
        caps = env_doc.get("capabilities", {})
        skipped = env_doc.get("skipped_acceptance", {})
        if caps.get("browser"):
            return C.emit(5, "FAIL", f"browser 未被伪造为缺失：{caps.get('browser')!r}")
        if "A99" not in skipped:
            return C.emit(5, "FAIL", f"A99 未进入 skipped_acceptance: {skipped}")

        # require 也必须拒（40）
        rc2, _, _ = C.environ("require", "--repo", tmp, "--need", "browser", env=NO_BROWSER)
        if rc2 != 40:
            return C.emit(5, "FAIL", f"缺能力时 require 应退出 40，得到 {rc2}")

        # 模拟"全绿"判定：A1 PASS + A99 SKIP → 全绿必须不成立
        log = "#!/bin/sh -> RESULT A1 PASS\nRESULT A1 PASS ok\n"
        res = simulate_run_with_skip(log, skipped)
        if all_green(res):
            return C.emit(5, "FAIL", "有 SKIP 却判为全绿（假绿）")
        return C.emit(5, "PASS",
                      f"browser=null → A99 SKIP → 全绿不成立（results={res}）")
    finally:
        C.cleanup(tmp)


if __name__ == "__main__":
    sys.exit(main())
