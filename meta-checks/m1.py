#!/usr/bin/env python3
"""M1 字节等价回归：FLEX_RULES 留空时 0.9 冻结 == 基线冻结。

用法: m1.py --sample <dir>
缺 --sample / 缺基线脚本 → SKIP（不假绿）。

关于抖动：回归样本里有一项验收探针本身不稳定（headless 浏览器 + 时间预算竞争），
同一份代码连跑两次可能一次 PASS 一次 FAIL。所以：
  - 首次两侧结果一致 → 直接 PASS（常见路径，不额外耗时）
  - 首次不一致 → 两侧各再跑一次，逐项分类：
      * 两侧各自稳定且取值相同 → 计入「稳定项一致」
      * 至少一侧自身抖动，且两侧取值有交集 → 判为探针抖动，单独点名，不进等价结论
      * 两侧取值无交集 → 真回归，FAIL
  - 抖动项不混进「逐字节相等」的结论里，但必须在 PASS 文本里点名。
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def as_map(results):
    return {aid: verdict for aid, verdict in results}


# 不一致时两侧最多各采几次。2 次太少：一个 60% PASS 的探针连采 2 次全落同一边
# 的概率约 36%，会被误判成"真回归"。按需加采样，到 5 次时误判率已降到 1% 以内。
MAX_SAMPLES = max(2, int(os.environ.get("AUTOPILOT_M1_MAX_SAMPLES", "5")))


def observed(runs):
    """汇总多次运行里每个 A# 出现过的判定值。"""
    obs = {}
    for r in runs:
        for aid, verdict in as_map(r).items():
            obs.setdefault(aid, []).append(verdict)
    return obs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default="")
    args = ap.parse_args()

    sample = args.sample
    if not sample or not os.path.isdir(sample):
        return C.emit(1, "SKIP",
                      "缺 --sample 回归样本工作区（未提供或不存在），不宣称等价")

    baseline = os.environ.get("AUTOPILOT_BASELINE_CHECK", "")
    if not baseline:
        # 没显式给基线就自己找，顺序与 tools/baseline08.sh 一致：
        #   $AUTOPILOT_BASELINE_SKILL/scripts/check.sh → $HOME/.autopilot/baseline-0.8/scripts/check.sh
        # 切换到 0.9 之后线上目录不再是 0.8，唯一还能拿来对照的就是切换时留下的那份快照。
        cands = []
        skill = os.environ.get("AUTOPILOT_BASELINE_SKILL", "")
        if skill:
            cands.append(os.path.join(skill, "scripts", "check.sh"))
        cands.append(os.path.join(os.path.expanduser("~"), ".autopilot",
                                  "baseline-0.8", "scripts", "check.sh"))
        for cand in cands:
            if os.path.isfile(cand):
                baseline = cand
                break
    if not baseline or not os.path.isfile(baseline):
        return C.emit(1, "SKIP",
                      "缺基线冻结脚本路径 AUTOPILOT_BASELINE_CHECK，无法做对照")

    for must in (".autopilot/checks/run.sh", ".autopilot/tasks.json"):
        if not os.path.isfile(os.path.join(sample, must)):
            return C.emit(1, "FAIL", f"样本缺 {must}，非合格回归样本")

    tmpA = C.new_tmp("m1-baseline-")
    tmpB = C.new_tmp("m1-v09-")
    try:
        dirA = os.path.join(tmpA, "repo")
        dirB = os.path.join(tmpB, "repo")
        shutil.copytree(sample, dirA, symlinks=False)
        shutil.copytree(sample, dirB, symlinks=False)

        # --- 基线：freeze + run ---
        rc_f, of, ef = C.sh(["sh", baseline, "freeze", dirA])
        if rc_f != 0:
            return C.emit(1, "SKIP", f"基线 freeze 未跑通（环境缺 shasum？），不做判定 :: {ef.strip()[:80]}")
        manA = os.path.join(dirA, ".autopilot/checks/MANIFEST.sha256")
        logA = os.path.join(dirA, ".autopilot/checks/last.log")
        if not os.path.isfile(manA):
            return C.emit(1, "FAIL", "基线未产出 MANIFEST.sha256")
        manifest_base = open(manA, encoding="utf-8").read()

        # --- 0.9：environ freeze ---
        rc_fr, of2, ef2 = C.environ("freeze", "--repo", dirB)
        if rc_fr != 0:
            return C.emit(1, "FAIL", f"0.9 freeze 失败 :: {ef2.strip()[:80]}")
        manB = os.path.join(dirB, ".autopilot/checks/MANIFEST.sha256")
        manifest_v09 = open(manB, encoding="utf-8").read()

        if manifest_base != manifest_v09:
            return C.emit(1, "FAIL",
                          "MANIFEST 不逐字节相等：基线/0.9 冻结漂移")

        def run_base():
            C.sh(["sh", baseline, "run", dirA])
            if not os.path.isfile(logA):
                return []
            return C.result_lines(open(logA, encoding="utf-8").read())

        def run_v09():
            chB = os.path.join(dirB, ".autopilot/checks")
            rc_run, runout, _ = C.sh(["sh", "run.sh"], cwd=chB)
            return C.result_lines(runout)

        base_runs = [run_base()]
        v09_runs = [run_v09()]

        if not base_runs[0] or not v09_runs[0]:
            return C.emit(1, "FAIL",
                          f"RESULT 序列为空 base={base_runs[0]} v09={v09_runs[0]}")

        if base_runs[0] != v09_runs[0]:
            # 首次不一致：判定是探针抖动还是真回归。
            # 只有"两侧各自一致、但取值不同"这一种情形才需要更多样本 —— 那是唯一
            # 分不清"抖动"和"真回归"的情况（一个 60% PASS 的探针连采 2 次全落同一边
            # 的概率约 36%，会被误判成回归）。只要有一侧采出第二个取值，就说明是抖动。
            # 所以这里按需加采样：两侧都还一致且不同就继续采，采到有一侧抖出第二值就停。
            while len(base_runs) < MAX_SAMPLES:
                obs_a, obs_b = observed(base_runs), observed(v09_runs)
                ambiguous = False
                for aid in sorted(obs_a):
                    va, vb = set(obs_a[aid]), set(obs_b[aid])
                    if len(va) == 1 and len(vb) == 1 and va != vb:
                        ambiguous = True
                        break
                if not ambiguous:
                    break
                base_runs.append(run_base())
                v09_runs.append(run_v09())

        obs_a, obs_b = observed(base_runs), observed(v09_runs)

        if set(obs_a) != set(obs_b):
            return C.emit(1, "FAIL",
                          f"RESULT 条目集合不一致 :: 基线={sorted(obs_a)} 0.9={sorted(obs_b)}")

        mismatch = {}
        flaky = {}
        compared = 0
        for aid in sorted(obs_a):
            vals_a, vals_b = set(obs_a[aid]), set(obs_b[aid])
            if len(vals_a) == 1 and len(vals_b) == 1:
                if vals_a != vals_b:
                    mismatch[aid] = (sorted(vals_a), sorted(vals_b))
                else:
                    compared += 1
            elif not (vals_a & vals_b):
                # 两侧取值集合无交集：不可能是同一份代码的抖动，是真回归
                mismatch[aid] = (sorted(vals_a), sorted(vals_b))
            else:
                # 至少一侧自身抖动，且另一侧的稳定取值在抖动集合里出现过
                flaky[aid] = sorted(vals_a | vals_b)

        if mismatch:
            detail = "; ".join(f"{a} 基线={x} 0.9={y}" for a, (x, y) in sorted(mismatch.items()))
            return C.emit(1, "FAIL", f"稳定项判定不一致 :: {detail}")

        note = ""
        if flaky:
            detail = "，".join(
                f"{aid}(观测到 {'/'.join(flaky[aid])})" for aid in sorted(flaky))
            note = ("；另有 %d 项探针自身抖动（两侧取值有交集），已单独点名不计入等价结论 :: %s"
                    % (len(flaky), detail))
        return C.emit(1, "PASS",
                      "MANIFEST 逐字节相等 + %d 项稳定 RESULT 一致（FLEX_RULES 留空等价基线）%s"
                      % (compared, note))
    finally:
        C.cleanup(tmpA)
        C.cleanup(tmpB)


if __name__ == "__main__":
    sys.exit(main())
