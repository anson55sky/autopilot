#!/usr/bin/env python3
"""H19 度量：把"跑得好不好"从感觉变成能复算的数，并且**只报能报的**。

口径全部对齐公开定义，不自创指标：
  - `pass^k`（单元 k 次尝试全通过率，SWE-bench Verified 口径）与 `pass@1`；
  - 返工率 = 重开过的卡 / 已关闭的卡（本项目既有口径，见 `status.py metrics`）；
  - 判定漂移率 = **同一份冻结基线**下，同一 A# 的判定在轮间发生翻转的比例
    （基线变了不算漂移——那是契约变更，epoch 会解释它）；
  - 每卡成本 / 每断言成本：只用宿主上报的 USD（`{"type":"usage","source":"host"}`），
    宿主没上报就打 `NA`，**不自估成本冒充实测**（H23）。

诚实边界：本模块度量的是**工作区里已经发生的事实**。模型层的成功率、幻觉率需要真实 run 的
样本量，样本不足时这里只会打出 `INSUFFICIENT`，不会编一个数出来。

用法:
  python3 scripts/metrics.py verdicts --repo <工作区> [--json]
  python3 scripts/metrics.py cost     --repo <工作区> [--json]
  python3 scripts/metrics.py summary  --repo <工作区> [--json]
退出码：0 正常 · 2 用法 · 10 数据不足以给出该指标（INSUFFICIENT，不是 0）。
"""

import argparse
import glob
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
try:
    import status as status_mod
except ImportError:                    # pragma: no cover
    status_mod = None

E_OK, E_USAGE, E_INSUFFICIENT = 0, 2, 10
RESULT_RE = re.compile(r"^RESULT\s+(A\d+)\s+(PASS|FAIL|SKIP)\b(.*)$")


def ap_of(repo):
    return os.path.join(repo, ".autopilot")


def load_json(path, default=None):
    if status_mod:
        return status_mod.load_json(path, default)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def round_docs(repo):
    out = []
    for p in sorted(glob.glob(os.path.join(ap_of(repo), "rounds", "r-*.json"))):
        d = load_json(p)
        if isinstance(d, dict):
            m = re.match(r"r-(\d+)\.passed\.json|r-(\d+)\.json|.*", os.path.basename(p))
            num = re.search(r"r-(\d+)", os.path.basename(p))
            d["_round"] = int(num.group(1)) if num else 0
            d["_file"] = os.path.basename(p)
            out.append(d)
    return out


def verdict_series(repo):
    """{A#: [(round, verdict, manifest_sha8)]}，按轮升序。"""
    series = {}
    for d in round_docs(repo):
        ev = d.get("evidence")
        man_in_ev = str(ev.get("manifest") or "") if isinstance(ev, dict) else ""
        stamp = (str(d.get("manifest") or d.get("manifest_sha256") or "")
                 or man_in_ev[:64] or "")
        stamp = stamp[:8].strip()
        passed = d.get("passed") or []
        failed = d.get("failed") or []
        skipped = d.get("skipped") or []
        for kind, names in (("PASS", passed), ("FAIL", failed), ("SKIP", skipped)):
            if not isinstance(names, list):
                continue
            for a in names:
                series.setdefault(str(a), []).append((d["_round"], kind, stamp))
        res = d.get("results")
        if isinstance(res, dict):
            for a, v in res.items():
                series.setdefault(str(a), []).append((d["_round"], str(v).upper(), stamp))
    for k in series:
        series[k].sort(key=lambda x: x[0])
    return series


def drift_rate(repo):
    series = verdict_series(repo)
    compared = flipped = 0
    detail = []
    unbaselined = False
    for aid, pts in sorted(series.items()):
        seen = {}
        for rnd, verdict, man in pts:
            key = man or "无基线戳"
            unbaselined = unbaselined or not man
            seen.setdefault(key, []).append((rnd, verdict))
        for man, lst in seen.items():
            uniq = set(v for _, v in lst)
            for i in range(1, len(lst)):
                compared += 1
                if lst[i][1] != lst[i - 1][1]:
                    flipped += 1
            if len(uniq) > 1:
                detail.append("A#%s 在同一基线 %s 下出现过 %s" % (aid, man or "无戳", "/".join(sorted(uniq))))
    rate = (float(flipped) / compared) if compared else None
    out = {"comparisons": compared, "flips": flipped, "rate": rate, "notes": detail}
    if unbaselined:
        out["confidence"] = ("轮次文档里没有 MANIFEST 戳：同一基线内的翻转"
                             "无法排除『其实是契约变更』，只作低置信提示")
    return out


def first_try_rate(repo):
    """首次尝试即通过的已关闭卡占比（本地可算的口径）。

    公开定义里的 `pass^k` 需要**同一任务 k 次独立采样**；一个 run 里每张卡只走一遍流程，
    没有独立重复采样，所以这里**不给 pass^k 数字**，只给可复算的 first_try_rate，
    并把"要测 pass^k 需要怎么采"写进输出，避免拿一个看起来一样的名字糊过去。
    """
    doc = load_json(os.path.join(ap_of(repo), "tasks.json"), {}) or {}
    tasks = doc.get("tasks") if isinstance(doc, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return None
    tot = one_try = 0
    for t in tasks:
        if not isinstance(t, dict) or str(t.get("status")) not in ("done", "closed"):
            continue
        tot += 1
        att = t.get("attempts")
        try:
            att = int(att) if att is not None else 1
        except (TypeError, ValueError):
            att = 1
        if att <= 1:
            one_try += 1
    if not tot:
        return None
    return {"closed_tasks": tot, "first_try": one_try,
            "first_try_rate": round(float(one_try) / tot, 4),
            "pass_pow_k": "INSUFFICIENT（需要同一任务 k 次独立采样；一个 run 内每卡只走一遍）",
            "how_to_measure_passk": "同一目标契约 + 同一冻结基线，独立开 k 个 run，统计 k 次全绿的卡占比"}


def cost_metrics(repo):
    events = []
    if status_mod:
        try:
            events = status_mod.read_ledger(ap_of(repo))
        except OSError:
            events = []
    usd = 0.0
    host_seen = False
    tool_calls = 0
    for e in events:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "usage" and e.get("source") == "host":
            try:
                usd += float(e.get("usd") or 0.0)
                host_seen = True
            except (TypeError, ValueError):
                pass
        if e.get("type") == "tool":
            tool_calls += 1
    doc = load_json(os.path.join(ap_of(repo), "tasks.json"), {}) or {}
    tasks = doc.get("tasks") if isinstance(doc, dict) else []
    closed = sum(1 for t in (tasks or []) if isinstance(t, dict) and str(t.get("status")) in ("done", "closed"))
    out = {"host_reported_usd": round(usd, 4) if host_seen else "NA（宿主未上报，不自估）",
           "tool_calls": tool_calls, "closed_tasks": closed}
    if host_seen and closed:
        out["usd_per_closed_task"] = round(usd / closed, 4)
    else:
        out["usd_per_closed_task"] = "NA"
    passed_ids = set()
    for aid, pts in verdict_series(repo).items():
        if pts and pts[-1][1] == "PASS":
            passed_ids.add(aid)
    out["passing_acceptance_items"] = len(passed_ids)
    if host_seen and passed_ids:
        out["usd_per_passing_item"] = round(usd / len(passed_ids), 4)
    else:
        out["usd_per_passing_item"] = "NA"
    return out


def recall_dup_rate(repo):
    """重复踩坑率代理：同一个 pitfall 主题在 N 轮里被再次记录的次数 / 总记录数。
    命中率的真值需要宿主召回日志，这里只给**代理口径**并明确标注。"""
    path = os.path.join(ap_of(repo), "playbook.md")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.startswith("- [")]
    except OSError:
        return {"entries": 0, "note": "没有 playbook.md，无数据"}
    seen, dup = {}, 0
    for ln in lines:
        key = re.sub(r"^-\s*\[\w+\]\s*", "", ln)[:24]
        seen[key] = seen.get(key, 0) + 1
    for v in seen.values():
        dup += max(0, v - 1)
    return {"entries": len(lines), "near_duplicates": dup,
            "proxy_rate": round(float(dup) / len(lines), 4) if lines else None,
            "口径": "前缀近重复查（代理）；真命中率需宿主召回日志，缺则不给数"}


def cmd_verdicts(a):
    d = drift_rate(os.path.abspath(a.repo))
    if not d["comparisons"]:
        print("METRICS 10 INSUFFICIENT 轮次样本不足（没有可对比的同基线判定序列）——不给漂移率，不编数")
        if a.json:
            print(json.dumps({"drift": d}, ensure_ascii=False))
        return E_INSUFFICIENT
    rate = d["rate"]
    print("METRICS 0 判定漂移率 = %.1f%%（同基线对比 %d 次，翻转 %d 次）"
          % (rate * 100.0, d["comparisons"], d["flips"]))
    for n in d["notes"][:6]:
        print("  DRIFT " + n)
    if a.json:
        print(json.dumps({"drift": d}, ensure_ascii=False, sort_keys=True))
    return E_OK


def cmd_cost(a):
    c = cost_metrics(os.path.abspath(a.repo))
    p = first_try_rate(os.path.abspath(a.repo))
    print("METRICS 0 成本：宿主 USD=%s · 工具调用=%s · 每关闭卡=%s · 每通过项=%s"
          % (c["host_reported_usd"], c["tool_calls"], c["usd_per_closed_task"],
             c["usd_per_passing_item"]))
    if p:
        print("METRICS 0 通过口径：一次通过 %.4f（已关闭卡 %d 张，其中首试即过 %d 张）；%s"
              % (p["first_try_rate"], p["closed_tasks"], p["first_try"], p["pass_pow_k"]))
    else:
        print("METRICS 10 INSUFFICIENT 没有已关闭的卡，一次通过率不给数")
    if a.json:
        print(json.dumps({"cost": c, "first_try": p}, ensure_ascii=False, sort_keys=True))
    return E_OK if p else E_INSUFFICIENT


def cmd_summary(a):
    repo = os.path.abspath(a.repo)
    d = drift_rate(repo)
    c = cost_metrics(repo)
    p = first_try_rate(repo)
    r = recall_dup_rate(repo)
    lines = [
        "判定漂移：%s" % ("INSUFFICIENT（同基线无可比序列）" if d["rate"] is None
                          else "%.1f%%（%d/%d 次对比翻转）" % (d["rate"] * 100.0, d["flips"], d["comparisons"])),
        "通过口径：%s" % ("INSUFFICIENT（没有已关闭的卡）" if not p else
                          "一次通过率 %.4f / 关闭 %d 卡（pass^k：%s）"
                          % (p["first_try_rate"], p["closed_tasks"], p["pass_pow_k"])),
        "成本：宿主 USD=%s 每关闭卡=%s 工具调用=%d" % (
            c["host_reported_usd"], c["usd_per_closed_task"], c["tool_calls"]),
        "重复踩坑代理：%s" % ("无 playbook" if not r.get("entries") else
                              "%d 条记录里近重 %d 条（代理口径，非真命中率）"
                              % (r["entries"], r.get("near_duplicates") or 0)),
        "声明：本模块只统计已发生的事实；模型层指标需真实 run 样本，样本不足一律 INSUFFICIENT。",
    ]
    print("METRICS 0 度量小结（%s）" % os.path.basename(repo))
    for ln in lines:
        print("  " + ln)
    if a.json:
        print(json.dumps({"drift": d, "cost": c, "first_try": p, "recall_proxy": r},
                         ensure_ascii=False, sort_keys=True))
    return E_OK


def main():
    ap = argparse.ArgumentParser(prog="metrics.py")
    sub = ap.add_subparsers(dest="cmd")
    for name, fn in (("verdicts", cmd_verdicts), ("cost", cmd_cost), ("summary", cmd_summary)):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.add_argument("--json", action="store_true")
        p.add_argument("--k", type=int, default=2)
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    if not getattr(a, "cmd", None):
        ap.print_help()
        return E_USAGE
    try:
        return a.fn(a)
    except OSError as exc:
        print("METRICS 2 内部错误：%s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
