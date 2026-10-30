#!/usr/bin/env python3
"""M9 close-round 幂等（含 flex 轮次，C4）：同一轮连收两次，轮次计数不变。

这里把 close_round 逻辑固化成纯函数（真实 skill 里它落在 supervisor 侧），
用合成 state.json 验证幂等：rounds_used 只在首次计入，flex_rounds_used 同理。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def close_round(state, round_id, kind="strict"):
    """幂等收轮：已收过则原样返回 (state, changed=False)。就地改 state 并返回 changed。"""
    bucket = "closed_strict" if kind == "strict" else "closed_flex"
    counter = "rounds_used" if kind == "strict" else "flex_rounds_used"
    state.setdefault("closed_strict", [])
    state.setdefault("closed_flex", [])
    state.setdefault("rounds_used", 0)
    state.setdefault("flex_rounds_used", 0)
    if round_id in state[bucket]:
        return state, False  # 已经收过，绝不重复计数
    state[bucket].append(round_id)
    state[counter] += 1
    return state, True


def main():
    tmp = C.new_tmp("m9-")
    try:
        state = {"rounds_used": 2, "flex_rounds_used": 1,
                 "closed_strict": [1, 2], "closed_flex": [1]}
        C.write_json(os.path.join(tmp, "state.json"), state)
        s = C.read_json(os.path.join(tmp, "state.json"))

        before_r = s["rounds_used"]
        _, ch1 = close_round(s, 3, "strict")
        after_first = s["rounds_used"]
        before_flex = s["flex_rounds_used"]
        _, ch2 = close_round(s, 3, "flex")
        after_flex_first = s["flex_rounds_used"]

        # 连收第二次：同一 strict 轮 + 同一 flex 轮，计数必须不变
        _, ch3 = close_round(s, 3, "strict")
        _, ch4 = close_round(s, 3, "flex")

        ok = (ch1 and not ch3 and not ch4 and ch2 and not ch4) \
            and after_first == before_r + 1 \
            and s["rounds_used"] == after_first \
            and after_flex_first == before_flex + 1 \
            and s["flex_rounds_used"] == after_flex_first \
            and s["closed_strict"].count(3) == 1 \
            and s["closed_flex"].count(3) == 1
        if ok:
            return C.emit(9, "PASS",
                          f"重复收轮不多计：rounds_used {before_r}→{s['rounds_used']}，"
                          f"flex_rounds_used {before_flex}→{s['flex_rounds_used']}")
        return C.emit(9, "FAIL",
                      f"幂等破坏 flags=({ch1},{ch2},{ch3},{ch4}) state={s}")
    finally:
        C.cleanup(tmp)


if __name__ == "__main__":
    sys.exit(main())
