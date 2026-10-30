#!/usr/bin/env python3
"""M10 中断恢复：模拟"工人已写文件但执行器中断"，新会话读接续包后已关闭波次不重做。

规则来源：C1 执行器中断自愈 + 一轮一会话 + resume.py 接续。
本检查只用合成 fixture，绝不动真实项目。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def plan_resume(state):
    """接续包 → 剩余待办波次里的任务 ID 列表。已 closed 的波次一律不重做。"""
    remaining = []
    for wave in state.get("waves", []):
        if wave.get("status") == "closed":
            continue
        for tid in wave.get("tasks", []):
            t = state.get("tasks", {}).get(tid, {})
            if t.get("status") in ("pending", "doing", "blocked"):
                remaining.append(tid)
    return remaining


def main():
    tmp = C.new_tmp("m10-")
    try:
        # 工人已把 T-04 的代码写到盘上，但执行器在收轮前挂了：
        C.write(os.path.join(tmp, "src/T-04.js"), "// 工人产物已落盘\nexport const x = 1;\n")
        state = {
            "waves": [
                {"id": 1, "tasks": ["T-01", "T-02"], "status": "closed", "round_closed": 2},
                {"id": 2, "tasks": ["T-03", "T-04"], "status": "open"},
                {"id": 3, "tasks": ["T-05"], "status": "closed", "round_closed": 3},
                {"id": 4, "tasks": ["T-06"], "status": "open"},
            ],
            "closed_rounds": [2, 3],
            "tasks": {
                "T-01": {"status": "done"},
                "T-02": {"status": "done"},
                "T-03": {"status": "pending"},
                "T-04": {"status": "doing", "artifact": "src/T-04.js"},
                "T-05": {"status": "done"},
                "T-06": {"status": "pending"},
            },
        }
        C.write_json(os.path.join(tmp, "state.json"), state)
        s = C.read_json(os.path.join(tmp, "state.json"))
        remaining = plan_resume(s)

        # 已关闭波次 1 与 3 的 T-01/T-02/T-05 绝不重做
        redone = {"T-01", "T-02", "T-05"} & set(remaining)
        if redone:
            return C.emit(10, "FAIL", f"已关闭波次被重做: {sorted(redone)}")
        expected = {"T-03", "T-04", "T-06"}
        if set(remaining) != expected:
            return C.emit(10, "FAIL",
                          f"剩余待办不符：期望 {sorted(expected)} 实际 {sorted(remaining)}")
        # T-04 的工人产物在盘上（"工人已写文件但执行器中断"）
        if not os.path.isfile(os.path.join(tmp, s["tasks"]["T-04"]["artifact"])):
            return C.emit(10, "FAIL", "T-04 工人产物文件不在盘上，场景构造失效")
        return C.emit(10, "PASS",
                      f"接续包正确：剩余={sorted(remaining)}，已关闭波次未重做，T-04 产物保留在盘")
    finally:
        C.cleanup(tmp)


if __name__ == "__main__":
    sys.exit(main())
