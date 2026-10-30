#!/usr/bin/env python3
"""M11 host.json 缺 intercept_permission 时，REPORT 生成器必须包含降级声明字段。

规格：host-adapter §3/§4/§6 —— 无高危拦截原语时，REPORT 的"环境声明"必须写明
`intercept_permission: absent`（缺能力必须显式降级，不许假装全保）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

PRIMITIVES = ("spawn_session", "await_turn", "ask_human",
              "intercept_permission", "kill_session")

REPORT_TEMPLATE = (
    "# REPORT\n\n"
    "## 环境声明\n"
    "- host: {host}\n"
    "- version: {version}\n"
    "{degrade_clauses}"
)


def degrade_clauses(host):
    """据 host.json 生成降级声明行；缺某个必须全保的原语 → 产出一行 `<prim>: absent`。"""
    prims = host.get("primitives", {}) or {}
    lines = []
    for name in PRIMITIVES:
        if not prims.get(name):
            # intercept_permission 缺失最严重（脚本级 deny-list 兜底也要显式声明）
            lines.append(f"- {name}: absent")
    extra = host.get("degraded_rules") or []
    for r in extra:
        lines.append(f"- rule: {r}")
    body = "".join(ln + "\n" for ln in lines)
    return lines, (body if body else "- 无降级项（全原语可用）\n")


def render_report(host):
    lines, block = degrade_clauses(host)
    return REPORT_TEMPLATE.format(
        host=host.get("host", "unknown"),
        version=host.get("version", "n/a"),
        degrade_clauses=block), lines


def main():
    tmp = C.new_tmp("m11-")
    try:
        degraded_host = {"host": "generic-cli", "version": "0.0",
                         "primitives": {"spawn_session": False, "await_turn": False,
                                        "ask_human": True}}  # 无 intercept_permission
        good_host = {"host": "qoder", "version": "1.0",
                     "primitives": {p: True for p in PRIMITIVES}}
        C.write_json(os.path.join(tmp, "host.degraded.json"), degraded_host)
        C.write_json(os.path.join(tmp, "host.good.json"), good_host)

        dh = C.read_json(os.path.join(tmp, "host.degraded.json"))
        gh = C.read_json(os.path.join(tmp, "host.good.json"))
        rpt_d, cl_d = render_report(dh)
        rpt_g, cl_g = render_report(gh)

        # 降级 host：REPORT 必须含 intercept_permission: absent 这一行
        has_ip_absent = any(l.strip().startswith("- intercept_permission: absent")
                            for l in rpt_d.splitlines())
        if not has_ip_absent:
            return C.emit(11, "FAIL", f"降级 REPORT 缺 intercept_permission 声明 :: {rpt_d!r}")
        # 全原语 host：不得出现任何降级声明（防止生成器把默认也当缺）
        if any("absent" in l for l in rpt_g.splitlines()):
            return C.emit(11, "FAIL", f"全原语 REPORT 竟出现 absent :: {rpt_g!r}")
        if cl_g != []:
            return C.emit(11, "FAIL", f"全原语降级列表应空，实际 {cl_g}")
        return C.emit(11, "PASS",
                      "降级 host → REPORT 含 intercept_permission: absent；全原语 host → 无降级声明")
    finally:
        C.cleanup(tmp)


if __name__ == "__main__":
    sys.exit(main())
