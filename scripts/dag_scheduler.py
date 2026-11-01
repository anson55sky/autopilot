#!/usr/bin/env python3
"""单目标 DAG 并发调度器（P2，默认关闭）。

只在 GOAL.md 的 `## CONCURRENT` 区块写 `enable = true` 时工作；关闭时
plan/status/start/finish/recover 一律退出码 23（config 只读，始终可用），
行为与串行基线一致。

职责边界：
  - 唯一写 tasks.json 运行时字段的组件（并发模式下工人与执行器都不手改；
    串行侧的状态变更走 status.py task，同一把思路的锁）；
  - 派发前做依赖 / 写集冲突 / 并发上限 / 槽位 / Triage 前提校验；
  - 超时只记账标 failed，本脚本从不杀工人（宿主无子代理 kill 原语，见 00-DECISIONS G3）；
    halt_policy=kill-running 时 recover 额外打印 KILL 清单，交给执行器调宿主 stop 原语（H6）。
  - 第一版只调度 strict 卡；flex 卡归类为 FLEX-SERIAL，照旧走串行流程（G4）。

子命令:
  config  --repo R [--enabled|--json]   读 GOAL.CONCURRENT 与 state.budget
  plan    --repo R                      只读：READY / DEFER / BLOCKED / STALE / TRIAGE-HALT
  start   --repo R --task T-xx [--session S]
  finish  --repo R --task T-xx --status done|failed [--note S]
  recover --repo R                      把超时的 running 标 failed（幂等）
  status  --repo R                      运行面（含 VERIFY-WINDOW / SLOTS）

退出码：0 ok / 2 用法 / 3 内部 / 20 锁超时 / 21 槽位或并发上限 /
        22 写集冲突 / 23 开关未启用 / 24 状态或依赖不合法。
"""

import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import status as status_mod  # noqa: E402

E_OK, E_USAGE, E_INTERNAL = 0, 2, 3
E_LOCK, E_BUDGET, E_CONFLICT, E_DISABLED, E_STATE = 20, 21, 22, 23, 24

DEFAULTS = {
    "enable": False,
    "max_concurrent_builder": 3,
    "halt_policy": "wait-running",
    "task_timeout_min": 30,
}
SUPPORTED_HALT = ("wait-running", "kill-running")
TASK_STATUSES = ("pending", "doing", "blocked", "done", "failed", "superseded")


def ap_of(repo):
    return os.path.join(repo, ".autopilot")


def as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def utc_now():
    return status_mod.now_iso()


# ---------------------------------------------------------------- 配置

def parse_concurrent(goal_path):
    cfg = dict(DEFAULTS)
    try:
        with open(goal_path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return cfg
    inside = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("## "):
            inside = line[3:].strip().upper().startswith("CONCURRENT")
            continue
        if not inside:
            continue
        line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, value = [x.strip() for x in line.split("=", 1)]
        if key == "enable":
            cfg[key] = value.lower() in ("1", "true", "yes", "on")
        elif key == "max_concurrent_builder":
            cfg[key] = max(1, as_int(value, cfg[key]))
        elif key == "task_timeout_min":
            cfg[key] = max(1, as_int(value, cfg[key]))
        elif key == "halt_policy":
            cfg[key] = value or cfg[key]
    return cfg


def load_config(repo):
    ap = ap_of(repo)
    cfg = parse_concurrent(os.path.join(ap, "GOAL.md"))
    state = status_mod.load_json(os.path.join(ap, "state.json"), {}) or {}
    budget = state.get("budget") if isinstance(state.get("budget"), dict) else {}
    doc = status_mod.load_json(os.path.join(ap, "tasks.json"), {}) or {}
    host = status_mod.load_json(os.path.join(ap, "host.json"), {}) or {}
    primitives = host.get("primitives") if isinstance(host.get("primitives"), dict) else {}
    host_workers = as_int(host.get("parallel_workers"), 0) if host.get("parallel_workers") is not None else 0
    kill_capable = bool(primitives.get("kill_session"))

    limit = cfg["max_concurrent_builder"]
    limit_from = "CONCURRENT.max_concurrent_builder"
    parallel = as_int(budget.get("parallel"), 0)
    if parallel and parallel < limit:
        limit, limit_from = parallel, "state.budget.parallel"
    if host_workers and host_workers < limit:
        limit, limit_from = host_workers, "host.parallel_workers"

    effective_halt = cfg["halt_policy"]
    halt_note = None
    if effective_halt not in SUPPORTED_HALT:
        halt_note = "halt_policy=%s 未支持，按 wait-running 执行" % effective_halt
        effective_halt = "wait-running"
    # H6：kill-running 只是「让执行器去杀」的指令清单，本脚本没有 kill 原语可用。
    # 宿主不上报 kill_session 能力时退化为 wait-running（照旧记账，不出 KILL 清单）。
    kill_directive = effective_halt == "kill-running" and kill_capable
    if effective_halt == "kill-running" and not kill_capable:
        halt_note = ("halt_policy=kill-running 需要宿主 kill_session 原语；"
                     "host.json 未上报该能力 → 退化为 wait-running（只记账）")
        effective_halt = "wait-running"
    return {
        "enable": bool(cfg["enable"]),
        "max_concurrent_builder": cfg["max_concurrent_builder"],
        "limit": limit,
        "limit_from": limit_from,
        "host_parallel_workers": host_workers,
        "kill_capable": kill_capable,
        "kill_directive": kill_directive,
        "halt_policy": effective_halt,
        "halt_note": halt_note,
        "task_timeout_min": cfg["task_timeout_min"],
        "max_tasks_per_round": as_int(budget.get("max_tasks_per_round"), 0),
        "max_calls": as_int(budget.get("max_calls"), 0),
        "round": as_int(state.get("rounds_used"), 0) + 1,
        "epoch": as_int(doc.get("epoch"), 0) if isinstance(doc, dict) else 0,
        "goal_missing": not os.path.isfile(os.path.join(ap, "GOAL.md")),
    }


# ---------------------------------------------------------------- 锁

class LockBusy(Exception):
    pass


def _read_pid(lock_dir):
    try:
        with open(os.path.join(lock_dir, "pid"), encoding="utf-8") as f:
            return as_int(f.read().strip(), 0) or None
    except OSError:
        return None


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


class SchedLock:
    def __init__(self, ap, timeout=None):
        self.path = os.path.join(ap, "locks", "sched.lock")
        self.timeout = timeout if timeout is not None else as_int(
            os.environ.get("AUTOPILOT_SCHED_LOCK_TIMEOUT"), 30)
        self.held = False

    def __enter__(self):
        deadline = time.time() + max(1, self.timeout)
        while True:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                os.mkdir(self.path)
                with open(os.path.join(self.path, "pid"), "w", encoding="utf-8") as f:
                    f.write(str(os.getpid()))
                self.held = True
                return self
            except FileExistsError:
                pid = _read_pid(self.path)
                if pid and not _pid_alive(pid):
                    shutil.rmtree(self.path, ignore_errors=True)
                    continue
                if time.time() >= deadline:
                    raise LockBusy("调度锁等待超时（%ss，持有者 PID %s）"
                                   % (self.timeout, pid or "?"))
                time.sleep(0.1)

    def __exit__(self, *exc):
        if self.held:
            shutil.rmtree(self.path, ignore_errors=True)
        return False


# ---------------------------------------------------------------- 任务表

def load_doc(ap):
    doc = status_mod.load_json(os.path.join(ap, "tasks.json"), None)
    if not isinstance(doc, dict) or not isinstance(doc.get("tasks"), list):
        raise ValueError(".autopilot/tasks.json 缺失或不是合法 DAG")
    return doc


def save_doc(ap, doc):
    path = os.path.join(ap, "tasks.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def norm_path(p):
    return str(p).replace("\\", "/").strip("/")


def paths_conflict(a, b):
    a, b = norm_path(a), norm_path(b)
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def write_set_conflict(ws1, ws2):
    return any(paths_conflict(x, y) for x in ws1 for y in ws2)


def find_task(tasks, tid):
    for t in tasks:
        if t.get("id") == tid:
            return t
    return None


def done_ids(tasks):
    return {t.get("id") for t in tasks if t.get("status") == "done"}


def running_tasks(tasks):
    return [t for t in tasks if t.get("status") == "doing"]


def slot_used(tasks, round_no):
    return sum(1 for t in tasks
               if as_int(t.get("dispatch_round"), 0) == round_no
               and t.get("status") in ("doing", "done", "failed"))


def triage_halted(tasks):
    tags = {}
    for t in tasks:
        if t.get("status") != "failed":
            continue
        tag = (t.get("premise_tag") or "").strip()
        if tag:
            tags.setdefault(tag, []).append(str(t.get("id")))
    return {tag: ids for tag, ids in tags.items() if len(ids) >= 2}


def stale_tasks(tasks, timeout_min):
    out = []
    now = status_mod.parse_ts(utc_now())
    for t in running_tasks(tasks):
        started = status_mod.parse_ts(t.get("started_at"))
        if started is None or now is None:
            continue
        minutes = int((now - started).total_seconds() // 60)
        if minutes >= timeout_min:
            out.append((t, minutes))
    return out


def classify(tasks, cfg, epoch):
    done = done_ids(tasks)
    running = running_tasks(tasks)
    halted = triage_halted(tasks)
    ready, defer, blocked, flex_serial = [], [], [], []
    selected = []
    for t in sorted(tasks, key=lambda x: str(x.get("id"))):
        if t.get("status") != "pending":
            continue
        tid = t.get("id")
        if str(t.get("mode") or "strict") != "strict":
            flex_serial.append(tid)  # G4：flex 卡不进调度器，照串行流程
            continue
        own_epoch = t.get("epoch")
        if own_epoch is not None and as_int(own_epoch, epoch) != epoch:
            blocked.append((tid, "epoch %s≠%s" % (own_epoch, epoch)))
            continue
        missing = [d for d in (t.get("deps") or []) if d not in done]
        if missing:
            blocked.append((tid, "deps=" + ",".join(missing)))
            continue
        tag = (t.get("premise_tag") or "").strip()
        if tag and tag in halted:
            blocked.append((tid, "TRIAGE-HALT " + tag))
            continue
        clash = [r.get("id") for r in running
                 if write_set_conflict(t.get("write_set") or [], r.get("write_set") or [])]
        if clash:
            defer.append((tid, "conflict-with=" + ",".join(clash)))
            continue
        clash = [s.get("id") for s in selected
                 if write_set_conflict(t.get("write_set") or [], s.get("write_set") or [])]
        if clash:
            defer.append((tid, "conflict-with=" + ",".join(clash)))
            continue
        ready.append(tid)
        selected.append(t)
    return {
        "running": running,
        "ready": ready,
        "defer": defer,
        "blocked": blocked,
        "halted": halted,
        "flex_serial": flex_serial,
        "stale": stale_tasks(tasks, cfg["task_timeout_min"]),
    }


# ---------------------------------------------------------------- 子命令

def cmd_config(args):
    cfg = load_config(args.repo)
    if args.enabled:
        print("1" if cfg["enable"] else "0")
        return E_OK
    if args.json:
        print(json.dumps(cfg, ensure_ascii=False, indent=2, sort_keys=True))
        return E_OK
    print("CONCURRENT enabled=%d limit=%d round=%d epoch=%d halt=%s timeout=%dm "
          "limit_from=%s kill=%s"
          % (1 if cfg["enable"] else 0, cfg["limit"], cfg["round"], cfg["epoch"],
             cfg["halt_policy"], cfg["task_timeout_min"], cfg["limit_from"],
             "directive" if cfg["kill_directive"] else "no（脚本不杀）"))
    if cfg["max_tasks_per_round"]:
        print("budget max_tasks_per_round=%d parallel=%d"
              % (cfg["max_tasks_per_round"], cfg["limit"]))
    if cfg["halt_note"]:
        print("NOTE " + cfg["halt_note"])
    return E_OK


def cmd_plan(args):
    cfg = load_config(args.repo)
    if not cfg["enable"]:
        print("CONCURRENT disabled（开关关时走串行流程，不调用调度器）")
        return E_DISABLED
    ap = ap_of(args.repo)
    try:
        doc = load_doc(ap)
    except ValueError as exc:
        print("STATE ERROR %s" % exc)
        return E_STATE
    tasks = doc["tasks"]
    view = classify(tasks, cfg, cfg["epoch"])
    print("CONCURRENT enabled=1 limit=%d round=%d epoch=%d timeout=%dm "
          "halt=%s limit_from=%s kill=%s"
          % (cfg["limit"], cfg["round"], cfg["epoch"], cfg["task_timeout_min"],
             cfg["halt_policy"], cfg["limit_from"],
             "directive" if cfg["kill_directive"] else "no（脚本不杀）"))
    for t in view["running"]:
        print("RUNNING %s %s" % (t.get("id"), norm_path((t.get("write_set") or ["-"])[0])))
    for t, minutes in view["stale"]:
        print("STALE %s %dm（recover 可标 failed）" % (t.get("id"), minutes))
    for tid, why in view["blocked"]:
        print("BLOCKED %s %s" % (tid, why))
    for tid, why in view["defer"]:
        print("DEFER %s %s" % (tid, why))
    for tid in view["ready"]:
        print("READY %s" % tid)
    for tid in view["flex_serial"]:
        print("FLEX-SERIAL %s（flex 卡照串行流程，不进调度器）" % tid)
    for tag, ids in sorted(view["halted"].items()):
        print("TRIAGE-HALT %s %s" % (tag, ",".join(ids)))
    print("VERIFY-WINDOW %s" % ("open" if not view["running"] else "closed"))
    used = slot_used(tasks, cfg["round"])
    cap = cfg["max_tasks_per_round"]
    print("SLOTS %d/%s" % (used, cap if cap else "-"))
    if cfg["halt_note"]:
        print("NOTE " + cfg["halt_note"])
    return E_OK


def _guard_enabled(cfg):
    if not cfg["enable"]:
        print("CONCURRENT disabled（开关关时走串行流程，不调用调度器）")
        return E_DISABLED
    return E_OK


def cmd_start(args):
    cfg = load_config(args.repo)
    rc = _guard_enabled(cfg)
    if rc:
        return rc
    ap = ap_of(args.repo)
    try:
        with SchedLock(ap):
            doc = load_doc(ap)
            tasks = doc["tasks"]
            task = find_task(tasks, args.task)
            if task is None:
                print("STATE ERROR 任务不存在: %s" % args.task)
                return E_STATE
            if str(task.get("mode") or "strict") != "strict":
                print("STATE ERROR %s 是 %s 卡，不进调度器（flex 走串行流程，G4）"
                      % (args.task, task.get("mode")))
                return E_STATE
            if task.get("status") != "pending":
                print("STATE ERROR %s 状态是 %s，不是 pending" % (args.task, task.get("status")))
                return E_STATE
            # H25：非幂等卡重派前要人工放行（重放可能重复迁移 / 重复写外部状态）
            non_idem = task.get("idempotent") is False
            prior_attempts = as_int(task.get("attempts"), 0)
            needs_release = non_idem and prior_attempts > 0
            if args.allow_non_idempotent and not needs_release:
                print("用法 %s 不需要人工放行（开关只对 idempotent=false 且 attempts>0 的卡有效）"
                      % args.task)
                return E_USAGE
            if args.allow_non_idempotent and not (args.note or "").strip():
                print("用法 --allow-non-idempotent 必须带 --note <人工放行理由>")
                return E_USAGE
            if needs_release and not args.allow_non_idempotent:
                print("STATE ERROR %s 声明 idempotent=false 且已派过 %d 次；"
                      "重派前需人工放行：start --allow-non-idempotent --note <理由>"
                      % (args.task, prior_attempts))
                return E_STATE
            own_epoch = task.get("epoch")
            if own_epoch is not None and as_int(own_epoch, cfg["epoch"]) != cfg["epoch"]:
                print("STATE ERROR %s epoch %s≠%s" % (args.task, own_epoch, cfg["epoch"]))
                return E_STATE
            missing = [d for d in (task.get("deps") or []) if d not in done_ids(tasks)]
            if missing:
                print("STATE ERROR %s 依赖未完成: %s" % (args.task, ",".join(missing)))
                return E_STATE
            tag = (task.get("premise_tag") or "").strip()
            if tag and tag in triage_halted(tasks):
                print("STATE ERROR %s 命中 TRIAGE-HALT %s（同前提已两次失败，第三次不得开工）"
                      % (args.task, tag))
                return E_STATE
            running = running_tasks(tasks)
            clash = [r.get("id") for r in running
                     if write_set_conflict(task.get("write_set") or [], r.get("write_set") or [])]
            if clash:
                print("CONFLICT %s 写集与运行中卡重叠: %s" % (args.task, ",".join(clash)))
                return E_CONFLICT
            if len(running) >= cfg["limit"]:
                print("BUDGET %s 并发已达上限 %d" % (args.task, cfg["limit"]))
                return E_BUDGET
            used = slot_used(tasks, cfg["round"])
            cap = cfg["max_tasks_per_round"]
            if cap and used >= cap:
                print("BUDGET %s 本轮槽位已用尽 %d/%d" % (args.task, used, cap))
                return E_BUDGET
            now = utc_now()
            task["status"] = "doing"
            task["started_at"] = now
            task["dispatch_round"] = cfg["round"]
            if args.session:
                task["session_id"] = args.session
            save_doc(ap, doc)
            worker_event = {
                "type": "worker", "task": args.task, "ts": now,
                "concurrent": True, "round": cfg["round"],
                "session": args.session or "",
                "idempotent": task.get("idempotent"),
            }
            if args.allow_non_idempotent:
                worker_event["human_release"] = args.note
            status_mod.append_ledger(ap, worker_event)
    except LockBusy as exc:
        print("LOCK TIMEOUT %s" % exc)
        return E_LOCK
    except ValueError as exc:
        print("STATE ERROR %s" % exc)
        return E_STATE
    print("START %s round=%d" % (args.task, cfg["round"]))
    return E_OK


def cmd_finish(args):
    cfg = load_config(args.repo)
    rc = _guard_enabled(cfg)
    if rc:
        return rc
    if args.status not in ("done", "failed"):
        print("用法: finish --status done|failed")
        return E_USAGE
    ap = ap_of(args.repo)
    try:
        with SchedLock(ap):
            doc = load_doc(ap)
            tasks = doc["tasks"]
            task = find_task(tasks, args.task)
            if task is None:
                print("STATE ERROR 任务不存在: %s" % args.task)
                return E_STATE
            if task.get("status") != "doing":
                print("STATE ERROR %s 状态是 %s，不是 doing" % (args.task, task.get("status")))
                return E_STATE
            now = utc_now()
            task["status"] = args.status
            task["ended_at"] = now
            if args.status == "failed":
                task["attempts"] = as_int(task.get("attempts"), 0) + 1
                task["last_error"] = args.note or "failed"
            else:
                # H12：done 必须留下"本轮关闭"的记账，close-round 才有可对账的依据
                task["closed_round"] = cfg["round"]
            save_doc(ap, doc)
            status_mod.append_ledger(ap, {
                "type": "task-finish", "task": args.task, "ts": now,
                "status": args.status, "concurrent": True,
                "round": cfg["round"], "note": args.note or "",
            })
            remaining = [t.get("id") for t in running_tasks(tasks) if t.get("id") != args.task]
    except LockBusy as exc:
        print("LOCK TIMEOUT %s" % exc)
        return E_LOCK
    except ValueError as exc:
        print("STATE ERROR %s" % exc)
        return E_STATE
    print("FINISH %s %s" % (args.task, args.status))
    if args.status == "failed":
        print("HALT %s（运行中剩余 %d 张：%s）"
              % (cfg["halt_policy"], len(remaining), ",".join(remaining) or "-"))
        if cfg["halt_note"]:
            print("NOTE " + cfg["halt_note"])
    return E_OK


def cmd_recover(args):
    cfg = load_config(args.repo)
    rc = _guard_enabled(cfg)
    if rc:
        return rc
    ap = ap_of(args.repo)
    try:
        with SchedLock(ap):
            doc = load_doc(ap)
            tasks = doc["tasks"]
            stale = stale_tasks(tasks, cfg["task_timeout_min"])
            now = utc_now()
            for task, minutes in stale:
                task["status"] = "failed"
                task["ended_at"] = now
                task["attempts"] = as_int(task.get("attempts"), 0) + 1
                task["last_error"] = "timeout %dm（只记账，不杀工人）" % minutes
                status_mod.append_ledger(ap, {
                    "type": "task-finish", "task": task.get("id"), "ts": now,
                    "status": "failed", "reason": "timeout", "minutes": minutes,
                    "concurrent": True, "round": cfg["round"],
                })
            if stale:
                save_doc(ap, doc)
    except LockBusy as exc:
        print("LOCK TIMEOUT %s" % exc)
        return E_LOCK
    except ValueError as exc:
        print("STATE ERROR %s" % exc)
        return E_STATE
    if not stale:
        print("RECOVER none")
        return E_OK
    print("RECOVER %s" % " ".join(t.get("id") for t, _ in stale))
    # H6：kill-running 的唯一诚实形态 —— 本脚本不杀，只交给执行器去调宿主 stop 原语。
    if cfg["kill_directive"]:
        for task, minutes in stale:
            sid = (task.get("session_id") or "").strip()
            if sid:
                print("KILL %s session=%s（执行器调宿主 stop_chat_session；超时 %dm）"
                      % (task.get("id"), sid, minutes))
            else:
                print("KILL-UNAVAILABLE %s 无 session_id，只能记账" % task.get("id"))
    elif cfg["halt_policy"] == "wait-running":
        print("NOTE halt=wait-running：已标 failed 的卡如仍在运行，等其自然结束，不重派写集相同的卡")
    return E_OK


def cmd_status(args):
    cfg = load_config(args.repo)
    ap = ap_of(args.repo)
    print("CONCURRENT enabled=%d limit=%d round=%d epoch=%d halt=%s timeout=%dm "
          "limit_from=%s kill=%s"
          % (1 if cfg["enable"] else 0, cfg["limit"], cfg["round"], cfg["epoch"],
             cfg["halt_policy"], cfg["task_timeout_min"], cfg["limit_from"],
             "directive" if cfg["kill_directive"] else "no（脚本不杀）"))
    if not cfg["enable"]:
        if cfg["halt_note"]:
            print("NOTE " + cfg["halt_note"])
        return E_DISABLED
    try:
        doc = load_doc(ap)
    except ValueError as exc:
        print("STATE ERROR %s" % exc)
        return E_STATE
    tasks = doc["tasks"]
    view = classify(tasks, cfg, cfg["epoch"])
    for t in view["running"]:
        started = status_mod.parse_ts(t.get("started_at"))
        now = status_mod.parse_ts(utc_now())
        age = "%dm" % int((now - started).total_seconds() // 60) if started and now else "?"
        print("RUNNING %s %s session=%s" % (t.get("id"), age, t.get("session_id") or "-"))
    for t, minutes in view["stale"]:
        print("STALE %s %dm" % (t.get("id"), minutes))
    for tid in view["ready"]:
        print("READY %s" % tid)
    for tid in view["flex_serial"]:
        print("FLEX-SERIAL %s（flex 卡照串行流程，不进调度器）" % tid)
    for tid, why in view["defer"]:
        print("DEFER %s %s" % (tid, why))
    for tid, why in view["blocked"]:
        print("BLOCKED %s %s" % (tid, why))
    for tag, ids in sorted(view["halted"].items()):
        print("TRIAGE-HALT %s %s" % (tag, ",".join(ids)))
    print("VERIFY-WINDOW %s" % ("open" if not view["running"] else "closed"))
    used = slot_used(tasks, cfg["round"])
    cap = cfg["max_tasks_per_round"]
    print("SLOTS %d/%s" % (used, cap if cap else "-"))
    if cfg["halt_note"]:
        print("NOTE " + cfg["halt_note"])
    return E_OK


# ---------------------------------------------------------------- 入口

def build_parser():
    p = argparse.ArgumentParser(prog="dag_scheduler.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("config"); c.add_argument("--repo", required=True)
    c.add_argument("--enabled", action="store_true"); c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_config)

    for name, fn in (("plan", cmd_plan), ("recover", cmd_recover), ("status", cmd_status)):
        s = sub.add_parser(name); s.add_argument("--repo", required=True); s.set_defaults(fn=fn)

    s = sub.add_parser("start"); s.add_argument("--repo", required=True)
    s.add_argument("--task", required=True); s.add_argument("--session", default="")
    s.add_argument("--note", default="")
    s.add_argument("--allow-non-idempotent", dest="allow_non_idempotent",
                   action="store_true",
                   help="人工放行 idempotent=false 且已派过的卡（必须配 --note 理由）")
    s.set_defaults(fn=cmd_start)

    s = sub.add_parser("finish"); s.add_argument("--repo", required=True)
    s.add_argument("--task", required=True); s.add_argument("--status", required=True)
    s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_finish)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # 用户看到中文提示，不是裸 traceback
        print("INTERNAL %s: %s" % (exc.__class__.__name__, exc), file=sys.stderr)
        return E_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
