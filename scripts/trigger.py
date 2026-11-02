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
  python3 scripts/trigger.py release --repo <工作区> [--if-stale]
  python3 scripts/trigger.py status  --repo <工作区>

看门狗：占位的会话如果没自己 release（进程被取消、上下文被压缩、91 秒就退出），
`decide / claim / release --if-stale` 三处共用同一个判据（stale_reason）机器判定能不能解锁：
**claim 之后账本零活动**（`auto_round` 自身不算活动）且超过一个节拍，或超 TTL 且仍零活动。
有活动就一律退 20 不抢——哪怕已经超 TTL：长轮次本来就可能跑很久，两个会话写同一轮的代价
（重复派发、账本互踩、假 PASS）比"链停下来等人"高。真要强行解锁，是人执行不带
--if-stale 的 `release`。

退出码：0 该接续（已给出派发要素）· 10 不该接续（没活/已到阶段/预算将满）·
20 已有会话在跑（锁被占，**不要重复开**；`release --if-stale` 也用这个码表示"还不该解"）·
21 自动接续次数触顶 · 23 未启用 · 24 需要人工批准（有待批项）。
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
try:
    import inbox as inbox_mod           # 待批项状态的唯一实现（H45：不再自己数事件行）
except ImportError:                    # pragma: no cover
    inbox_mod = None
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


def activity_since(repo, since_epoch):
    """claim 之后账本里有没有别的活动（任务开工、闸门核销、工人收执、收轮）。

    只数 `auto_round` 以外的事件——占位本身不是干活。用来把「会话还在跑」与
    「claim 完就跑路」分开：前者不许抢锁，后者让无人值守那一跳能自己解开，
    而不是干等到 TTL（实测 ContraRunner 就卡过一次：占位的会话 91 秒就结束，
    下一跳每 30 分钟敲一次都判 BUSY，白等一个半小时）。
    """
    if not status_mod:
        return None
    try:
        events = status_mod.read_ledger(ap_of(repo))
    except OSError:
        return None
    n = 0
    for e in events:
        if not isinstance(e, dict) or e.get("type") == "auto_round":
            continue
        ts = status_mod.parse_ts(e.get("ts"))
        if ts is None:
            continue
        if ts.timestamp() >= since_epoch - 1:      # 容 1 秒：claim 与首条事件常同秒
            n += 1
    return n


def ttl_minutes(cfg):
    """陈旧锁的最长持有时间：3 个节拍，最少 3 分钟（口径唯一，decide/claim/release 共用）。"""
    return max(3, int(cfg["interval_min"])) * 3


def stale_reason(cfg, repo, lk):
    """该不该解锁。返回 (判据种类, 说明)；种类为空串表示**不许自动解**。

    只承认两种可以自动解的情形，共同点是「账本能证明这个会话没在干活」：
      idle —— 超过一个节拍且 claim 之后除 auto_round 外零事件（实测就是这个把链卡死的）；
      ttl  —— 超过 TTL 且仍然零活动（读不到账本时也只在超 TTL 后才敢按此放行）。
    反过来，**有活动就没资格自动解**，哪怕已经超 TTL：长轮次本来就可能跑很久，
    抢锁的代价是两个会话同时写同一轮（重复派发、账本互踩），
    比"链停下来等人"更糟。这种情形由人工 `release`（不带 --if-stale）兜底。
    """
    interval = max(1, int(cfg["interval_min"]))
    ttl = ttl_minutes(cfg)
    claimed = float(lk.get("ts") or 0)
    age_min = (time.time() - claimed) / 60.0
    acts = activity_since(repo, claimed)
    if acts is None:
        return ("ttl", "超过 TTL %d 分钟且读不到账本，按陈旧处理" % ttl) if age_min >= ttl else ("", "")
    if acts:
        return ("", "")
    if age_min >= ttl:
        return ("ttl", "超过 TTL %d 分钟且账本零活动" % ttl)
    if age_min >= interval:
        return ("idle", "claim 后 %d 分钟账本零活动（会话多半已退出而没 release）" % int(age_min))
    return ("", "")


def count_ready(repo):
    """ready 卡数。口径单一来源：开着并发就用 dag_scheduler plan 的 READY 行，
    否则退回 tasks.json 静态判定（status=ready，或 status=pending 且依赖全部 done）。"""
    plan = os.path.join(SCRIPT_DIR, "dag_scheduler.py")
    if os.path.exists(plan):
        import subprocess
        try:
            out = subprocess.run([sys.executable, plan, "plan", "--repo", repo],
                                 capture_output=True, text=True, timeout=60)
            if out.returncode == 0:
                n = sum(1 for ln in (out.stdout or "").splitlines() if ln.strip().startswith("READY"))
                if n or "READY" in (out.stdout or ""):
                    return n, "dag_scheduler plan 的 READY 行"
        except (OSError, subprocess.SubprocessError):
            pass
    doc = (status_mod.load_json(os.path.join(ap_of(repo), "tasks.json"), {})
           if status_mod else {}) or {}
    tasks = doc.get("tasks") if isinstance(doc, dict) else None
    done = {t.get("id") for t in (tasks or []) if isinstance(t, dict) and str(t.get("status")) in ("done", "closed")}
    n = 0
    for t in (tasks or []):
        if not isinstance(t, dict):
            continue
        st = str(t.get("status"))
        deps = t.get("depends_on") or t.get("deps") or []
        if st == "ready" or (st == "pending" and all(dp in done for dp in deps)):
            n += 1
    return n, "tasks.json 静态判定（status=ready，或 pending 且依赖全 done）"


def open_inbox_count(repo):
    """未答复的待批**条目**数。

    原实现是「数 inbox.jsonl 里 state==open 的行」，而 inbox.jsonl 是追加式事件流：
    一条待批会产生 open / present / answer 多行，且 present、answer 行根本没有 state 字段，
    于是 `e.get("state") or "open"` 把它们也默认成 open 一起计入 —— 事件当条目数，答复过的也还在数。
    ContraRunner 实测：真待批 1 条，它报 13 条，decide 因此永久返回 24 ASK-HUMAN，
    自动接续被一个不存在的数字停摆。改为复用 inbox.py 的按 id 折叠语义（单一实现，H28）。
    """
    ap = ap_of(repo)
    if inbox_mod is not None:
        try:
            events = inbox_mod.load_events(ap)
            # 兼容 0.8 时代与自测里的写法：有的行只有 state、没有 type。
            # 按 type 折叠会把这类"未答复待批"整个漏掉 —— 那等于把待批闸门改松了，
            # 违反「判定只更严、不删护栏」。这里先把它们规范成 open 事件再折叠。
            fixed = []
            for e in events:
                if isinstance(e, dict) and not e.get("type") and str(e.get("state") or "open") == "open":
                    e = dict(e, type="open")
                fixed.append(e)
            items = inbox_mod.current_items(fixed)
            return sum(1 for it in items.values() if it.get("status") != "answered")
        except Exception:
            pass
    # 退路（inbox.py 不可用时）：仍按 id 折叠，绝不按行计数
    p = os.path.join(ap, "inbox.jsonl")
    latest = {}
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
                if not isinstance(e, dict):
                    continue
                iid = e.get("id")
                if not iid:
                    continue
                et = e.get("type") or ("open" if str(e.get("state") or "open") == "open" else None)
                if et == "open":
                    latest[iid] = "open"
                elif et == "present" and latest.get(iid) == "open":
                    latest[iid] = "presented"
                elif et == "answer" and iid in latest and latest[iid] != "answered":
                    latest[iid] = "answered"
    except OSError:
        return 0
    return sum(1 for v in latest.values() if v != "answered")


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
        kind, why = stale_reason(cfg, repo, lk)
        if kind:
            reasons.append("锁看门狗判为陈旧（%s，claim %d 分钟，%s）：可以解锁后开第 %d 轮，"
                           "release --if-stale 只做机器确认过的解锁" % (
                               lk.get("session") or "?", int(age_min), why, cfg["round"]))
        elif age_min < ttl_minutes(cfg):
            reasons.append("已有自动会话在跑（%s，%d 分钟前 claim）——不要重复开会话；"
                           "看门狗没发现它失联，所以不给你解锁命令" % (
                               lk.get("session") or "?", int(age_min)))
            code = E_BUSY
        else:
            reasons.append("锁已超 TTL（claim %d 分钟）但 claim 后账本有活动，"
                           "无法确认那个会话是否还活着：自动接续**宁停不抢**（退 20）。"
                           "两个会话写同一轮的代价比链停下来等人高——"
                           "确认它死了再由人执行不带 --if-stale 的 release" % int(age_min))
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
    ready, ready_source = count_ready(repo)
    if code == E_OK and not ready:
        reasons.append("没有 ready 卡（可能都在跑或都关了）：先跑 dag_scheduler.py plan 再决定")
        code = E_NO_WORK
    verdict = {E_OK: "GO", E_NO_WORK: "HOLD", E_BUSY: "BUSY",
               E_CAP: "STOP", E_ASK_HUMAN: "ASK-HUMAN"}.get(code, "HOLD")
    doc = {"decision": verdict, "round": cfg["round"], "ready_tasks": ready,
           "ready_source": ready_source,
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
        kind, _why = stale_reason(cfg, repo, lk)
        if not kind:
            age_min = int((time.time() - float(lk.get("ts") or 0)) / 60.0)
            print("TRIGGER 20 锁还在（%d 分钟前由 %s claim，看门狗没发现它失联）：不重复占位。"
                  "确实那一轮已经死了，就先跑 release --if-stale（它只做机器确认过的解锁）"
                  % (age_min, lk.get("session") or "?"))
            return E_BUSY
        print("TRIGGER 0 旧锁由看门狗判为陈旧（%s），直接改占" % _why)
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
    lk = lock_info(repo)
    if getattr(a, "if_stale", False):
        if not lk:
            print("TRIGGER 0 没有锁（幂等：重复 release 不报错）")
            return E_OK
        kind, why = stale_reason(cfg, repo, lk)
        if not kind:
            age = int((time.time() - float(lk.get("ts") or 0)) / 60.0)
            acts = activity_since(repo, float(lk.get("ts") or 0)) or 0
            if age >= ttl_minutes(cfg):
                print("TRIGGER 20 锁已超 TTL（claim %d 分钟）但账本有 %d 条活动："
                      "宁停不抢——两个会话写同一轮的代价比链停下来等人高。"
                      "确认那一轮真的死了，再由人（或控制器）执行不带 --if-stale 的 release"
                      % (age, acts))
            else:
                print("TRIGGER 20 锁不该释放（claim %d 分钟前，session=%s，claim 后账本有 %d 条活动）："
                      "别抢正在干活的会话" % (age, lk.get("session") or "?", acts))
            return E_BUSY
        os.remove(p)
        print("TRIGGER 0 陈旧锁已释放：%s（原 session=%s，轮 %s）。"
              "若那个会话其实还活着，请它自己 release；本脚本不碰宿主 API，也不建会话"
              % (why, lk.get("session") or "?", lk.get("round")))
        if status_mod:
            status_mod.append_ledger(ap_of(repo), {"type": "auto_round_released",
                                                  "session": lk.get("session") or "",
                                                  "round": lk.get("round"), "reason": why})
        return E_OK
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
    parsers = {}
    for name, fn in (("decide", cmd_decide), ("claim", cmd_claim),
                     ("release", cmd_release), ("status", cmd_status)):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.add_argument("--session", default="")
        p.add_argument("--json", action="store_true")
        p.set_defaults(fn=fn)
        parsers[name] = p
    parsers["release"].add_argument(
        "--if-stale", action="store_true",
        help="只解陈旧锁：超 TTL，或超过一个节拍且 claim 之后账本零活动；否则退 20 不抢锁")
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
