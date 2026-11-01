#!/usr/bin/env python3
"""H36 外部触发接续：让宿主的定时器能把长跑接力下去，但不越权。

问题：刻意"一轮一会话 + 人唤醒"的代价是无人值守过夜会停（机器休眠或会话结束就断）。
本模块提供**决策函数**，宿主定时器（cron / heartbeat / 计划任务）每次敲一下时问一句
"现在该不该开新会话"，脚本据实回答；**开不开会话由宿主做，本模块不建会话、不发消息**。

开关：GOAL.md 的可选段 `## TRIGGER`（缺省不存在 = 关闭态，所有子命令退 23，不写任何文件）：
```
## TRIGGER
enable            = true
interval_min      = 20        # 定时器节拍，只用于判断"上一跳是否漏拍"
max_auto_sessions = 12        # 本 run 内自动接续上限，触顶就停手等人
stop_phase        = report    # 到该阶段就不再自动接续
```

用法:
  python3 scripts/trigger.py decide --repo <工作区> [--json]
  python3 scripts/trigger.py claim  --repo <工作区> --session <宿主会话id>
  python3 scripts/trigger.py release --repo <工作区>
  python3 scripts/trigger.py status  --repo <工作区>

退出码：0 该接续（已给出派发要素）· 10 不该接续（没活/已到阶段/预算将满）·
20 已有会话在跑（锁被占，**不要重复开**）· 21 自动接续次数触顶 · 23 未启用 · 24 需要人工批准（有待批项）。
"""

import argparse
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
try:
    import status as status_mod
except ImportError:                    # pragma: no cover
    status_mod = None
import goalcfg                          # GOAL 段落解析器唯一实现（H28）

E_OK, E_USAGE = 0, 2
E_BUSY, E_CAP, E_DISABLED, E_ASK_HUMAN, E_NO_WORK = 20, 21, 23, 24, 10
DEFAULTS = {"enable": False, "interval_min": 20, "max_auto_sessions": 12, "stop_phase": "report"}
LOCK = "trigger.lock"


def ap_of(repo):
    return os.path.join(repo, ".autopilot")


def load_config(repo):
    cfg = goalcfg.parse_block(os.path.join(ap_of(repo), "GOAL.md"), "TRIGGER", DEFAULTS)
    state = status_mod.load_json(os.path.join(ap_of(repo), "state.json"), {}) if status_mod else {}
    if not isinstance(state, dict):
        state = {}
    cfg["state"] = state
    cfg["round"] = int(state.get("rounds_used") or 0) + 1
    return cfg


def guard(cfg):
    if not cfg["enable"]:
        print("TRIGGER 23 未启用（GOAL 没有 ## TRIGGER）：不决策、不加锁、不写文件")
        return False
    return True


def read_ledger_events(repo, kind):
    if not status_mod:
        return []
    try:
        events = status_mod.read_ledger(ap_of(repo))
    except OSError:
        return []
    return [e for e in events if isinstance(e, dict) and e.get("type") == kind]


def lock_info(repo):
    p = os.path.join(ap_of(repo), LOCK)
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def open_inbox_count(repo):
    """待批项数量。数据源与 inbox.py 一致：`.autopilot/inbox.jsonl` 里 state=open 的行。"""
    p = os.path.join(ap_of(repo), "inbox.jsonl")
    n = 0
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and str(e.get("state") or "open") == "open":
                    n += 1
    except OSError:
        return 0
    return n


def cmd_decide(a):
    repo = os.path.abspath(a.repo)
    cfg = load_config(repo)
    if not guard(cfg):
        return E_DISABLED
    state = cfg["state"]
    budget = state.get("budget") or {}
    used = int(state.get("rounds_used") or 0)
    max_rounds = int(budget.get("max_rounds") or 0)
    auto = len(read_ledger_events(repo, "auto_round"))
    reasons, code = [], E_OK

    lk = lock_info(repo)
    if lk:
        age_min = (time.time() - float(lk.get("ts") or 0)) / 60.0
        stale_after = max(3, int(cfg["interval_min"])) * 3
        if age_min < stale_after:
            reasons.append("已有自动会话在跑（%s，%d 分钟前 claim）——不要重复开会话" % (
                lk.get("session") or "?", int(age_min)))
            code = E_BUSY
    if str(state.get("phase") or "") == str(cfg["stop_phase"]):
        reasons.append("已到阶段 %s，自动接续停止，交回人工" % cfg["stop_phase"])
        code = E_NO_WORK if code == E_OK else code
    if max_rounds and used >= max_rounds:
        reasons.append("轮次预算已用尽（%d/%d）" % (used, max_rounds))
        code = E_NO_WORK if code == E_OK else code
    if cfg["max_auto_sessions"] and auto >= int(cfg["max_auto_sessions"]):
        reasons.append("本 run 自动接续已到上限 %d 次——停手等人，不无限自续"
                       % int(cfg["max_auto_sessions"]))
        code = E_CAP if code in (E_OK, E_NO_WORK) else code
    pend = open_inbox_count(repo)
    if pend:
        reasons.append("有待批项 %d 条：自动接续**不得**处理不可逆动作，先等人" % pend)
        code = E_ASK_HUMAN
    ready = 0
    if status_mod:
        tasks = status_mod.load_json(os.path.join(ap_of(repo), "tasks.json"), {}) or {}
        for t in (tasks.get("tasks") or []) if isinstance(tasks, dict) else []:
            if isinstance(t, dict) and t.get("status") == "ready":
                ready += 1
    if code == E_OK and not ready:
        reasons.append("没有 ready 卡（可能都在跑或都关了）：先跑 dag_scheduler.py plan 再决定")
        code = E_NO_WORK
    verdict = {E_OK: "GO", E_NO_WORK: "HOLD", E_BUSY: "BUSY",
               E_CAP: "STOP", E_ASK_HUMAN: "ASK-HUMAN"}.get(code, "HOLD")
    doc = {"decision": verdict, "round": cfg["round"], "ready_tasks": ready,
           "ready_source": "tasks.json 里 status=ready 的静态计数（并发开着时以 dag_scheduler.py plan 的 READY 为准）",
           "auto_sessions_used": auto, "auto_sessions_cap": int(cfg["max_auto_sessions"]),
           "phase": state.get("phase"), "pending_inbox": pend,
           "reasons": reasons or ["条件齐备：可以开第 %d 轮" % cfg["round"]],
           "declare": "REPORT 必须写明本 run 启用了外部触发接续（H36）",
           "next": "sh {SKILL_ROOT}/scripts/round_prompt.sh {REPO_ROOT} %d 取提示词 → claim → 宿主开会话 → 结束 release"
                   % cfg["round"]}
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, sort_keys=True))
    else:
        print("TRIGGER %d %s 第 %d 轮：%s" % (code, verdict, cfg["round"], "；".join(doc["reasons"])))
    if code == E_OK and not a.json:
        print("TRIGGER 下一步（由宿主做，本脚本不建会话、不发消息）："
              "sh {SKILL_ROOT}/scripts/round_prompt.sh {REPO_ROOT} %d 取提示词 → claim → 宿主开会话 → 结束 release"
              % cfg["round"])
    return code


def cmd_claim(a):
    repo = os.path.abspath(a.repo)
    cfg = load_config(repo)
    if not guard(cfg):
        return E_DISABLED
    lk = lock_info(repo)
    if lk:
        age_min = (time.time() - float(lk.get("ts") or 0)) / 60.0
        if age_min < max(3, int(cfg["interval_min"])) * 3:
            print("TRIGGER 20 锁还在（%d 分钟前由 %s claim）：不重复占位"
                  % (int(age_min), lk.get("session") or "?"))
            return E_BUSY
    auto = len(read_ledger_events(repo, "auto_round"))
    if cfg["max_auto_sessions"] and auto >= int(cfg["max_auto_sessions"]):
        print("TRIGGER 21 自动接续已到上限 %s 次，停手等人" % cfg["max_auto_sessions"])
        return E_CAP
    with open(os.path.join(ap_of(repo), LOCK), "w", encoding="utf-8") as fh:
        json.dump({"session": a.session or "", "ts": time.time(), "round": cfg["round"]},
                  fh, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    if status_mod:
        status_mod.append_ledger(ap_of(repo), {"type": "auto_round", "session": a.session or "",
                                               "round": cfg["round"], "source": "trigger"})
    print("TRIGGER 0 已占位：第 %d 轮由宿主开会话（session=%s）。会话结束必须 release，否则下一跳判 BUSY"
          % (cfg["round"], a.session or "未填"))
    return E_OK


def cmd_release(a):
    repo = os.path.abspath(a.repo)
    cfg = load_config(repo)
    if not guard(cfg):
        return E_DISABLED
    p = os.path.join(ap_of(repo), LOCK)
    if os.path.exists(p):
        os.remove(p)
        print("TRIGGER 0 锁已释放，下一跳可以接续")
    else:
        print("TRIGGER 0 没有锁（幂等：重复 release 不报错）")
    return E_OK


def cmd_status(a):
    repo = os.path.abspath(a.repo)
    cfg = load_config(repo)
    if not guard(cfg):
        return E_DISABLED
    lk = lock_info(repo)
    auto = len(read_ledger_events(repo, "auto_round"))
    print("TRIGGER 0 enable=true 节拍=%smin 自动接续=%d/%d 锁=%s 阶段=%s"
          % (cfg["interval_min"], auto, int(cfg["max_auto_sessions"]),
             ("占位中（session %s，轮 %s）" % (lk.get("session") or "?", lk.get("round")))
             if lk else "空闲", cfg["state"].get("phase")))
    return E_OK


def main():
    ap = argparse.ArgumentParser(prog="trigger.py")
    sub = ap.add_subparsers(dest="cmd")
    for name, fn in (("decide", cmd_decide), ("claim", cmd_claim),
                     ("release", cmd_release), ("status", cmd_status)):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.add_argument("--session", default="")
        p.add_argument("--json", action="store_true")
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    if not getattr(a, "cmd", None):
        ap.print_help()
        return E_USAGE
    try:
        return a.fn(a)
    except OSError as exc:
        print("TRIGGER 3 内部错误：%s" % exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
