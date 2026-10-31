#!/usr/bin/env python3
"""M9 close-round 幂等 + 审计文件隔离：直接跑真实 scripts/status.py。

历史版本用纯函数复刻 close-round，测不出生产者/消费者漂移（例如审计文件被当成轮次记录）。
现在搭临时工作区调用真实脚本：连收两次幂等，且 r-NN.flex.json 不参与轮次发现。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

STATUS = os.path.join(C.SCRIPTS, "status.py")


def close(tmp, path):
    return C.sh([sys.executable, STATUS, "close-round", tmp, path])


def main():
    tmp = C.new_tmp("m9-")
    try:
        ap = os.path.join(tmp, ".autopilot")
        os.makedirs(os.path.join(ap, "rounds"), exist_ok=True)
        os.makedirs(os.path.join(tmp, "sandbox", ".gate"), exist_ok=True)
        C.write_json(os.path.join(ap, "state.json"), {
            "started_at": "2026-01-01T00:00:00+00:00",
            "phase": "execute",
            "rounds_used": 0,
            "closed_rounds": [],
            "no_progress_streak": 0,
            "last_passed": [],
            "budget": {"max_rounds": 10},
        })
        C.write_json(os.path.join(tmp, "sandbox", ".gate", "state.json"),
                     {"light_used": 1, "heavy_used": 0, "flex_calls": 1})

        r1 = os.path.join(ap, "rounds", "r-01.json")
        C.write_json(r1, {"round": 1, "epoch": 0, "verdict": "pass",
                          "passed": ["A1"], "failed": [], "tasks_closed": 1})
        rc, out, err = close(tmp, r1)
        if rc != 0:
            return C.emit(9, "FAIL", f"真实 status.py 收第 1 轮失败 rc={rc}: {out}{err}")

        C.write_json(os.path.join(ap, "rounds", "r-01.flex.json"),
                     {"round": 1, "epoch": 0, "flex_used": {"light": 1, "calls": 1}})
        r2 = os.path.join(ap, "rounds", "r-02.json")
        C.write_json(r2, {"round": 2, "epoch": 0, "verdict": "pass",
                          "passed": ["A1"], "failed": [], "tasks_closed": 0})
        rc, out, err = close(tmp, r2)
        if rc != 0:
            return C.emit(9, "FAIL", f"真实 status.py 收第 2 轮失败 rc={rc}: {out}{err}")

        doc = C.read_json(r2) or {}
        flex = doc.get("flex") or {}
        cum = flex.get("cumulative") or {}
        state = C.read_json(os.path.join(ap, "state.json")) or {}
        metrics = C.read_json(os.path.join(ap, "rounds", "r-02.metrics.json")) or {}
        need = ["round", "calls_used", "elapsed_minutes", "max_parallel",
                "rework_rate", "flex_usage_rate"]
        missing = [k for k in need if k not in metrics]
        if missing:
            return C.emit(9, "FAIL", f"r-02.metrics.json 缺字段 {missing}")
        if flex.get("light") != 0 or cum.get("light_used") != 1:
            return C.emit(9, "FAIL",
                          f"r-01.flex.json 被当成轮次记录：light={flex.get('light')} "
                          f"cumulative.light_used={cum.get('light_used')}")
        if flex.get("usage_rate") is not None or "均为 0" not in (flex.get("usage_rate_basis") or ""):
            return C.emit(9, "FAIL", "第 2 轮无调用无决策时占比应记为不适用")
        if state.get("rounds_used") != 2:
            return C.emit(9, "FAIL", f"rounds_used 记成 {state.get('rounds_used')}（应为 2）")

        before = open(r2, encoding="utf-8").read()
        rc, out, err = close(tmp, r2)
        if rc != 0:
            return C.emit(9, "FAIL", f"重复收轮失败 rc={rc}: {out}{err}")
        after = open(r2, encoding="utf-8").read()
        state = C.read_json(os.path.join(ap, "state.json")) or {}
        if before != after or state.get("rounds_used") != 2:
            return C.emit(9, "FAIL",
                          f"重复收轮不幂等：文件变={before != after} "
                          f"rounds_used={state.get('rounds_used')}")

        return C.emit(9, "PASS",
                      "真实 status.py 连收两次幂等；r-01.flex.json 不污染第 2 轮")
    finally:
        C.cleanup(tmp)


if __name__ == "__main__":
    sys.exit(main())
