#!/usr/bin/env python3
"""autopilot 账本工具（0.9）：轮次汇总、事件记录、阶段切换、收轮、轮次指标。

用法:
  status.py summary [root]
  status.py log <root> '<json事件>'
  status.py phase <root> <intake|plan|execute|verify|report>
  status.py close-round <root> <round.json>
  status.py metrics <root> [round]
  status.py task <root> set <T-xx> <status> [--note S]   # P2：带锁单写者
  status.py task <root> list [--json]
  status.py pause [root] [--note 原因]                    # H9 时间账
  status.py resume [root] [--note 原因]                   # H9 时间账
  status.py budget <root> max_tool_calls=400 [max_usd=20]  # H8/H23，只准收紧或新设

0.9 相对 0.8 的变化:
  C3 时间戳健壮：naive / 坏戳 / 空戳一律不崩，显示 unknown。
  C4 收轮幂等：close-round 可重复执行，flex 轮次也不会重复计数。
  C5 轮次指标：每次收轮写 rounds/r-XX.metrics.json。
  H12 收轮对账：done 写 closed_round；`tasks_closed` 与记账对不上则退 24 且零写盘。
  H9 时间账：pause/resume 只用于报告与量化，停止判定仍按墙钟（放宽需人工改 GOAL）。

CLI 与 0.8 完全兼容（同样的子命令、同样的参数名），0.9 是它的超集。
"""

import argparse
import datetime
import glob
import json
import os
import re
import shutil
import sys
import time

UNKNOWN = "unknown"
PHASES = ("intake", "plan", "execute", "verify", "report")
REWORK_TYPES = ("rework", "redo", "retry", "revert", "revise", "fix")
GATE_DECISION_KEYS = ("decision", "kind", "level", "type", "action", "result", "mode", "gate")
PARALLEL_KEYS = ("max_parallel", "max_parallelism", "parallel_peak", "peak_parallel", "parallelism")


# ---------------------------------------------------------------- 小工具

def now_iso():
    """新写的戳一律 UTC（+00:00）。

    换机器 / 换时区后，"这个事件距今多久" 必须由绝对时刻决定，
    不能跟着墙上时钟漂。历史戳带本地偏移照样能读（parse_ts → astimezone）。
    """
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def to_float(value, default=None):
    """宽容的浮点读取：坏值返回 default，不抛异常（与 to_int 同口径）。"""
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value, default=None):
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def dump_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except (OSError, UnicodeDecodeError):
        pass
    return rows


def fmt_num(value):
    return UNKNOWN if value is None else str(value)


# ---------------------------------------------------------------- C3 时间戳

# 读到缺偏移的时间戳时记一条警告（不是错误，但必须让人看见）。
# 0.9 起新写的戳一律 UTC；缺偏移只可能来自手改或外部写入。
TS_WARNINGS = []


def parse_ts(stamp):
    """解析时间戳；无时区偏移按 UTC 解释并记警告；坏戳/空戳返回 None（永不抛异常）。

    缺偏移一律按 UTC 解释（而不是猜本地）：0.9 的落盘口径就是 UTC，
    猜本地会在换时区的机器上把"距今多久"整体偏移一整个时区差。
    """
    if not isinstance(stamp, str):
        return None
    txt = stamp.strip()
    if not txt:
        return None
    if txt.endswith(("Z", "z")):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(txt)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
        note = "时间戳缺时区偏移，已按 UTC 解释（若它其实是本地时间，预算会偏）: " + txt
        if note not in TS_WARNINGS:
            TS_WARNINGS.append(note)
    return dt


def fmt_started(stamp):
    """started_at → 本地时间串（形如 2026-01-01 08:00）；坏戳/空戳 → unknown。"""
    try:
        dt = parse_ts(stamp)
        if dt is None:
            return UNKNOWN
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError, OverflowError):
        return UNKNOWN


def elapsed_minutes(stamp):
    """距今分钟数；时间戳坏掉时返回 None（= unknown），不抛异常。"""
    try:
        dt = parse_ts(stamp)
        if dt is None:
            return None
        now = datetime.datetime.now(dt.tzinfo)
        return int((now - dt).total_seconds() // 60)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def slept_minutes(events):
    """H9：`pause`/`resume` 记账出来的"墙钟在走但没干活"分钟数。

    没有这两类事件时返回 None —— 老工作区的口径与输出一个字都不变。
    **停止判定仍然按墙钟**：本数字只用于报告和量化，要把判定改成活跃时长必须人工改 GOAL，
    不允许控制器自己放宽（只准收紧或持平）。
    """
    total = 0.0
    open_from = None
    seen = False
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") not in ("pause", "resume"):
            continue
        ts = parse_ts(e.get("ts"))
        if ts is None:
            continue
        seen = True
        if e["type"] == "pause":
            if open_from is None:
                open_from = ts
        elif open_from is not None:
            total += (ts - open_from).total_seconds()
            open_from = None
    if not seen:
        return None
    if open_from is not None:
        total += (datetime.datetime.now(open_from.tzinfo) - open_from).total_seconds()
    return int(total // 60)


# ---------------------------------------------------------------- 账本

def append_ledger(ap, event):
    """单次 O_APPEND 写入：并发调度时多个工人在同一本账上追加也不会截断半行。"""
    event.setdefault("ts", now_iso())
    data = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(os.path.join(ap, "ledger.jsonl"),
                 os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def read_ledger(ap):
    return read_jsonl(os.path.join(ap, "ledger.jsonl"))


def acceptance_ids(ap):
    ids = []
    try:
        with open(os.path.join(ap, "GOAL.md"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\|\s*(A\d+)\s*\|", line)
                if m and m.group(1) not in ids:
                    ids.append(m.group(1))
    except (FileNotFoundError, OSError):
        pass
    return ids


def open_inbox_count(ap):
    items = {}
    for e in read_jsonl(os.path.join(ap, "inbox.jsonl")):
        iid = e.get("id")
        if not iid:
            continue
        if e.get("type") == "open":
            items[iid] = "open"
        elif e.get("type") == "answer":
            items[iid] = "answered"
    return sum(1 for v in items.values() if v == "open")


def load_tasks(ap):
    doc = load_json(os.path.join(ap, "tasks.json"), {"tasks": []})
    tasks = doc.get("tasks", []) if isinstance(doc, dict) else []
    return tasks if isinstance(tasks, list) else []


# ---------------------------------------------------------------- 任务状态单写者（P2）

TASK_STATUSES = ("pending", "doing", "blocked", "done", "failed", "superseded")


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


def acquire_state_lock(ap, timeout=None):
    """tasks.json 的读改写锁。mkdir 原子 + PID + 陈旧抢占，与 check.sh 同款。"""
    lock_dir = os.path.join(ap, "locks", "state.lock")
    wait = timeout if timeout is not None else to_int(
        os.environ.get("AUTOPILOT_STATE_LOCK_TIMEOUT"), 30) or 30
    deadline = time.time() + max(1, wait)
    while True:
        try:
            os.makedirs(os.path.dirname(lock_dir), exist_ok=True)
            os.mkdir(lock_dir)
            with open(os.path.join(lock_dir, "pid"), "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            return lambda: shutil.rmtree(lock_dir, ignore_errors=True)
        except FileExistsError:
            holder = None
            try:
                with open(os.path.join(lock_dir, "pid"), encoding="utf-8") as f:
                    holder = to_int(f.read().strip(), 0) or None
            except OSError:
                holder = None
            if holder and not _pid_alive(holder):
                shutil.rmtree(lock_dir, ignore_errors=True)
                continue
            if time.time() >= deadline:
                raise TimeoutError("状态锁等待超时（%ss，持有者 PID %s）" % (wait, holder or "?"))
            time.sleep(0.1)


def atomic_dump_json(path, data):
    """与 dump_json 同格式（indent=2、不排序、无尾换行），但 tmp+replace 不撕裂。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def task_update(root, tid, status, note=None):
    ap = os.path.join(root, ".autopilot")
    if status not in TASK_STATUSES:
        print("状态只能是: %s" % " / ".join(TASK_STATUSES))
        return 2
    release = acquire_state_lock(ap)
    try:
        path = os.path.join(ap, "tasks.json")
        doc = load_json(path, None)
        if not isinstance(doc, dict) or not isinstance(doc.get("tasks"), list):
            print("读不到合法的 tasks.json: %s" % path)
            return 2
        tasks = doc["tasks"]
        task = next((t for t in tasks if isinstance(t, dict) and t.get("id") == tid), None)
        if task is None:
            print("任务不存在: %s" % tid)
            return 2
        old = task.get("status", "pending")
        if old == status:
            print("TASK %s 已是 %s（跳过）" % (tid, status))
            return 0
        now = now_iso()
        round_no = to_int((load_json(os.path.join(ap, "state.json"), {}) or {}).get("rounds_used"), 0) + 1
        task["status"] = status
        if status == "doing":
            task.setdefault("started_at", now)
        elif status in ("done", "failed"):
            task["ended_at"] = now
            if status == "failed":
                task["attempts"] = to_int(task.get("attempts"), 0) + 1
                if note:
                    task["last_error"] = note
            else:
                task["closed_round"] = round_no
        atomic_dump_json(path, doc)
        event = {"type": "task", "actor": "status.py", "task": tid,
                 "from": old, "status": status, "ts": now}
        if note:
            event["note"] = note
        append_ledger(ap, event)
    finally:
        release()
    print("TASK %s %s -> %s" % (tid, old, status))
    return 0


def task_list(root, as_json):
    ap = os.path.join(root, ".autopilot")
    tasks = load_tasks(ap)
    rows = [{"id": t.get("id"), "status": t.get("status", "pending"),
             "started_at": t.get("started_at"), "ended_at": t.get("ended_at"),
             "dispatch_round": t.get("dispatch_round"),
             "write_set": t.get("write_set") or []}
            for t in tasks if isinstance(t, dict)]
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for r in rows:
        print("%s %s %s" % (r["id"], r["status"], ",".join(r["write_set"])))
    return 0


# ---------------------------------------------------------------- flex 闸门

def gate_dirs(root, ap):
    # 生产者（flexgate.py / resume.py）用 <repo>/sandbox/.gate/；
    # 另一种布局 <ap>/sandbox/.gate/ 也认，避免工作区迁移后读不到。
    return [os.path.join(ap, "sandbox", ".gate"), os.path.join(root, "sandbox", ".gate")]


def classify_decision(event):
    """把一条闸门决策归成 light/heavy/flex/deny/other；认不出就记 other。"""
    if not isinstance(event, dict):
        return "other"
    texts = []
    for key in GATE_DECISION_KEYS:
        val = event.get(key)
        if isinstance(val, str) and val.strip():
            texts.append(val.strip().lower())
    # 生产者的一次决策既有 decision（allow/spend/deny）又有 mode（flex-light），
    # 所以要把所有键扫完再定级，不能在第一个认不出的键上提前返回 other。
    for text in texts:
        if any(w in text for w in ("deny", "reject", "block", "refuse")):
            return "deny"
    for text in texts:
        if "flex" in text:
            # flex-light / flex_heavy 都算 flex 通道（先判 flex 再判 light）
            return "flex"
    for text in texts:
        if "heavy" in text:
            return "heavy"
    for text in texts:
        if "light" in text:
            return "light"
    return "other"


def read_gate(root, ap):
    """读 flex 闸门：state.json 计数器 + gate.jsonl 决策流。"""
    base = None
    for d in gate_dirs(root, ap):
        if os.path.isfile(os.path.join(d, "state.json")) or os.path.isfile(os.path.join(d, "gate.jsonl")):
            base = d
            break
    if base is None:
        for d in gate_dirs(root, ap):
            if os.path.isdir(d):
                base = d
                break
    if base is None:
        return {"present": False, "path": None, "light_used": None, "heavy_used": None,
                "flex_calls": None, "decisions": None,
                "reason": "sandbox/.gate 目录不存在，无法判定 flex 用量"}

    st = load_json(os.path.join(base, "state.json"), None)
    light = heavy = flex = None
    if isinstance(st, dict):
        light = to_int(st.get("light_used"))
        heavy = to_int(st.get("heavy_used"))
        flex = to_int(st.get("flex_calls"))
    rows = read_jsonl(os.path.join(base, "gate.jsonl"))
    kinds = {"light": 0, "heavy": 0, "flex": 0, "deny": 0, "other": 0}
    for row in rows:
        kinds[classify_decision(row)] += 1
    decisions = {"total": len(rows)}
    decisions.update(kinds)
    reason = None
    if st is None and not rows:
        reason = "sandbox/.gate 下没有 state.json 也没有 gate.jsonl，flex 用量未知"
    return {"present": True, "path": base, "light_used": light, "heavy_used": heavy,
            "flex_calls": flex, "decisions": decisions, "reason": reason}


def flex_snapshot(gate):
    """把闸门读数压成可比较的累计快照。"""
    dec = gate.get("decisions") or {}
    return {
        "light_used": gate.get("light_used"),
        "heavy_used": gate.get("heavy_used"),
        "flex_calls": gate.get("flex_calls"),
        "decisions_total": dec.get("total"),
        "decisions_light": dec.get("light"),
        "decisions_heavy": dec.get("heavy"),
        "decisions_flex": dec.get("flex"),
    }


def _delta(current, base):
    """累计差值；没有基准时当前值就是增量（第一轮）。"""
    if current is None:
        return None
    if base is None:
        return current
    try:
        return max(0, current - int(base))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 轮次文件

def rounds_dir(ap):
    return os.path.join(ap, "rounds")


def latest_round_doc(ap):
    """真·轮次判定文档：只认 `r-<n>.json`。

    `r-<n>.metrics.json` / `r-<n>.flex.json` 是派生产物，按文件名字典序排它们会压过判定文档
    （实测把 report 闸门判空放行），所以按轮号取最大值而不是按文件名排序。
    """
    best = None
    try:
        names = os.listdir(rounds_dir(ap))
    except OSError:
        return None
    for name in names:
        m = re.match(r"^r-(\d+)\.json$", name)
        if not m:
            continue
        no = int(m.group(1))
        if best is None or no > best[0]:
            best = (no, os.path.join(rounds_dir(ap), name))
    return best[1] if best else None


def round_record_path(ap, round_no):
    return os.path.join(rounds_dir(ap), "r-%02d.json" % round_no)


def metrics_record_path(ap, round_no):
    return os.path.join(rounds_dir(ap), "r-%02d.metrics.json" % round_no)


def list_round_records(ap):
    """列出已有轮次记录（只认 r-NN.json；同目录的 .flex.json / .metrics.json 不算）。"""
    out = []
    try:
        names = sorted(os.listdir(rounds_dir(ap)))
    except OSError:
        return out
    for name in names:
        if not re.fullmatch(r"r-\d+\.json", name):
            continue
        doc = load_json(os.path.join(rounds_dir(ap), name), None)
        if isinstance(doc, dict):
            out.append((name, doc))
    return out


def latest_record_before(ap, round_no):
    """取 round_no 之前编号最大的那一轮记录。"""
    best = None
    for _, doc in list_round_records(ap):
        no = to_int(doc.get("round"))
        if no is None or no >= round_no:
            continue
        if best is None or no > best[0]:
            best = (no, doc)
    return best


def contract_change(round_doc, prev_doc):
    """合同 epoch 提升算进展；只认与上一轮记录的对比，不认轮次自报标记。"""
    if not isinstance(prev_doc, dict):
        return None
    cur_epoch = to_int(round_doc.get("epoch"))
    prev_epoch = to_int(prev_doc.get("epoch"))
    if cur_epoch is None or prev_epoch is None or cur_epoch <= prev_epoch:
        return None
    return {"from": prev_epoch, "to": cur_epoch}


# ---------------------------------------------------------------- 指标推导

def round_start(ap, state, round_doc, round_no, events):
    """本轮起点：round.json.started_at → 上一轮 closed_at → 上一条 round 事件 → state.started_at（第 1 轮兜底）。"""
    dt = parse_ts(round_doc.get("started_at"))
    if dt is not None:
        return dt, "轮次结果里的 started_at"
    prev = latest_record_before(ap, round_no)
    if prev:
        dt = parse_ts(prev[1].get("closed_at"))
        if dt is not None:
            return dt, "上一轮（r-%02d）的 closed_at" % prev[0]
    rounds = [e for e in events if e.get("type") == "round"]
    if rounds:
        dt = parse_ts(rounds[-1].get("ts"))
        if dt is not None:
            return dt, "账本里上一条 round 事件"
    if round_no <= 1:
        dt = parse_ts(state.get("started_at"))
        if dt is not None:
            return dt, "state.started_at（第 1 轮兜底）"
    return None, "没有任何起点记录"


def count_calls(events, start):
    """本轮 worker/verifier 调用数；start 为 None 时无法按时间切分，全部计入。"""
    total = 0
    for e in events:
        if e.get("type") not in ("worker", "verifier"):
            continue
        ts = parse_ts(e.get("ts"))
        if start is None or ts is None or ts >= start:
            total += 1
    return total


def count_rework(events, start):
    total = 0
    for e in events:
        if e.get("type") in REWORK_TYPES:
            ts = parse_ts(e.get("ts"))
            if start is None or ts is None or ts >= start:
                total += 1
    return total


def peak_overlap(intervals):
    """区间最大重叠数（同一时刻结束的先出栈）。"""
    marks = []
    for s, e in intervals:
        marks.append((s, 1))
        marks.append((e, -1))
    marks.sort(key=lambda m: (m[0], m[1]))
    cur = peak = 0
    for _, d in marks:
        cur += d
        if cur > peak:
            peak = cur
    return peak


def max_parallelism(events, tasks, state, round_doc):
    """最大并发度；只认显式记录（字段或起止时间），推不出来就 null。"""
    for src, label in ((round_doc, "轮次结果"), (state, "state.json")):
        for key in PARALLEL_KEYS:
            value = to_int(src.get(key))
            if value is not None:
                return value, "%s 里的 %s" % (label, key)
    intervals = []
    for e in events:
        s = parse_ts(e.get("started_at") or e.get("start"))
        t = parse_ts(e.get("ended_at") or e.get("end"))
        if s is not None and t is not None and t >= s:
            intervals.append((s, t))
    for task in tasks:
        if not isinstance(task, dict):
            continue
        s = parse_ts(task.get("started_at") or task.get("started"))
        t = parse_ts(task.get("ended_at") or task.get("finished"))
        if s is not None and t is not None and t >= s:
            intervals.append((s, t))
    if intervals:
        return peak_overlap(intervals), "由账本/任务表里的显式起止时间推出"
    return None, "轮次结果、state.json、账本、任务表里都没有并发度记录"


def count_redispatch(events, start):
    """同一任务在本轮窗口内被重复派发 = 返工；返回 (多出的派发次数, 参与任务数)。"""
    by_task = {}
    for e in events:
        if e.get("type") != "worker":
            continue
        ts = parse_ts(e.get("ts"))
        if start is not None and ts is not None and ts < start:
            continue
        key = e.get("task") or e.get("card") or e.get("id")
        if not key:
            continue
        by_task[key] = by_task.get(key, 0) + 1
    extra = sum(n - 1 for n in by_task.values() if n > 1)
    return extra, len(by_task)


def rework_rate(events, tasks, start, calls):
    """返工率：优先用账本里的 rework/retry 事件，其次看同一任务重复派发，最后用 attempts。"""
    rework = count_rework(events, start)
    if rework:
        if calls:
            return rework / calls, "账本里 rework/retry 事件 %d 条 ÷ 本轮调用 %d 次" % (rework, calls)
        return None, "发现 %d 条 rework/retry 事件，但本轮调用数未知，比率算不出" % rework
    redispatch, workers = count_redispatch(events, start)
    if redispatch:
        if calls:
            return redispatch / calls, ("账本里 %d 个任务重复派发、多出 %d 次 ÷ 本轮调用 %d 次"
                                        % (workers, redispatch, calls))
        return None, "发现同一任务重复派发 %d 次，但本轮调用数未知，比率算不出" % redispatch
    attempts = 0
    with_attempts = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        value = to_int(task.get("attempts"))
        if value is not None:
            attempts += max(0, value - 1)
            with_attempts += 1
    if with_attempts and tasks:
        return attempts / len(tasks), "任务表里 %d 个任务共 %d 次重做 ÷ %d 个任务" % (with_attempts, attempts, len(tasks))
    return None, "账本里没有 rework/retry 事件，任务表里也没有 attempts 计数"


def flex_usage_rate(flex_delta, dec_flex_delta, dec_total_delta, calls, gate_total_delta):
    """flex 使用率：先按「flex 调用 ÷ 本轮总调用」算（A3 的预算占比口径）。

    决策流只覆盖闸门流量，不覆盖 strict 卡，单独用它算占比会得出 100% 的假象；
    只有在调用数未知时才退回决策流。
    """
    if flex_delta is not None and calls:
        return flex_delta / calls, "flex 调用 %d 次 ÷ 本轮调用 %d 次" % (flex_delta, calls)
    if dec_flex_delta is not None and dec_total_delta:
        return (dec_flex_delta / dec_total_delta,
                "闸门决策流里 flex 决策 %d 次 ÷ 总决策 %d 次" % (dec_flex_delta, dec_total_delta))
    if flex_delta is not None and gate_total_delta:
        return flex_delta / gate_total_delta, "flex 计数 %d ÷ 闸门总计数 %d（计数器可能互相重叠）" % (
            flex_delta, gate_total_delta)
    if flex_delta == 0 and dec_total_delta == 0:
        return None, "本轮 flex 调用与闸门决策均为 0（占比不适用）"
    return None, "没有可用分母（闸门决策流缺失且本轮调用数未知）"


# ---------------------------------------------------------------- 子命令

def cmd_summary(root):
    ap = os.path.join(root, ".autopilot")
    if not os.path.isdir(ap):
        print("没有 %s（先跑 init.sh）" % ap)
        return 2

    state = load_json(os.path.join(ap, "state.json"), {})
    if not isinstance(state, dict):
        state = {}
    budget = state.get("budget") or {}
    if not isinstance(budget, dict):
        budget = {}
    started_text = fmt_started(state.get("started_at"))
    elapsed = elapsed_minutes(state.get("started_at"))
    events = read_ledger(ap)
    calls = sum(1 for e in events if e.get("type") in ("worker", "verifier"))

    tasks = load_tasks(ap)
    by_status = {}
    for t in tasks:
        key = t.get("status", "pending") if isinstance(t, dict) else "pending"
        by_status[key] = by_status.get(key, 0) + 1

    done_ids = {t.get("id") for t in tasks if isinstance(t, dict) and t.get("status") == "done"}
    ready = [
        t.get("id") for t in tasks
        if isinstance(t, dict)
        and t.get("status", "pending") == "pending"
        and all(d in done_ids for d in t.get("deps", []))
    ]

    result = load_json(os.path.join(ap, "checks", "last-result.json"), {})
    if not isinstance(result, dict):
        result = {}
    passed = result.get("passed", []) or []
    failed = result.get("failed", []) or []
    ids = acceptance_ids(ap)
    uncovered = [i for i in ids if i not in passed and i not in failed]

    max_rounds = to_int(budget.get("max_rounds"), 0) or 0
    max_minutes = to_int(budget.get("max_minutes"), 0) or 0
    max_calls = to_int(budget.get("max_calls"), 0) or 0
    # H8/H23：工具调用数由本地账本可数；美元/token 只在**宿主上报**时参与判定
    max_tool_calls = to_int(budget.get("max_tool_calls"), 0) or 0
    max_usd = to_float(budget.get("max_usd"), 0.0) or 0.0
    tool_calls = sum(1 for e in events if e.get("type") == "tool")
    host_usd = 0.0
    self_usd = 0.0
    host_tokens = 0
    for e in events:
        if e.get("type") != "usage":
            continue
        v = to_float(e.get("usd"), None)
        if e.get("source") == "host":
            if v is not None:
                host_usd += v
            host_tokens += to_int(e.get("tokens"), 0) or 0
        elif v is not None:
            self_usd += v
    rounds = to_int(state.get("rounds_used"), 0) or 0
    streak = to_int(state.get("no_progress_streak"), 0) or 0

    script_green = bool(ids) and not failed and bool(result) and set(ids) <= set(passed)
    verified_green = (
        script_green
        and state.get("phase") == "report"
        and state.get("last_verdict") == "pass"
    )

    stops = []
    if verified_green:
        stops.append("验收全绿（已收轮）")
    if streak >= 2:
        stops.append("连续两轮零进展")
    if max_rounds and rounds >= max_rounds:
        stops.append("轮次预算耗尽")
    if max_minutes and elapsed is not None and elapsed >= max_minutes:
        stops.append("时长预算耗尽")
    if max_calls and calls >= max_calls:
        stops.append("调用预算耗尽")
    if max_tool_calls and tool_calls >= max_tool_calls:
        stops.append("工具调用预算耗尽")
    if max_usd and host_usd >= max_usd:
        stops.append("宿主上报成本预算耗尽（USD）")

    goal = state.get("goal")
    goal_text = goal if isinstance(goal, str) else ("" if goal is None else str(goal))
    goal_line = goal_text.strip().splitlines()
    goal_line = goal_line[0] if goal_line else "(未记录)"

    gate = read_gate(root, ap)
    if gate["present"]:
        gate_text = ("light %s · heavy %s · flex_calls %s"
                     % (fmt_num(gate["light_used"]), fmt_num(gate["heavy_used"]),
                        fmt_num(gate["flex_calls"])))
    else:
        gate_text = "无记录（sandbox/.gate 未探测）"

    print("== autopilot ==")
    print("目标:   %s" % goal_line)
    print("模式:   %s   阶段: %s" % (state.get("mode", "auto"), state.get("phase", "intake")))
    print("开始:   %s" % started_text)
    print("轮次:   %s/%s   用时: %s/%s 分钟   调用: %s/%s"
          % (rounds, max_rounds or "-", fmt_num(elapsed), max_minutes or "-",
             calls, max_calls or "-"))
    slept = slept_minutes(events)
    if slept is not None and elapsed is not None:
        print("时间账:  墙钟 %s 分钟 = 活跃 %s + 暂停/休眠 %s（H9；停止判定仍按墙钟，改口径需人工改 GOAL）"
              % (elapsed, elapsed - slept, slept))
    if max_tool_calls or max_usd:
        parts = []
        if max_tool_calls:
            parts.append("工具调用 %s/%s" % (tool_calls, max_tool_calls))
        if max_usd:
            seg = "宿主上报 %.2f/%.2f USD" % (host_usd, max_usd)
            if self_usd:
                seg += " · 自估 %.2f（不参与判定）" % self_usd
            parts.append(seg)
        print("成本账:  %s" % " · ".join(parts))
    if tasks:
        parts = " · ".join("%s %s" % (k, v) for k, v in sorted(by_status.items()))
        print("任务:   %d/%d 完成   (%s)" % (by_status.get("done", 0), len(tasks), parts))
    else:
        print("任务:   未拆解（tasks.json 缺失）")
    if ids:
        print("验收:   %d/%d 通过%s" % (len(passed), len(ids),
                                       ("   未过: %s" % " ".join(failed)) if failed else ""))
        if uncovered:
            print("未覆盖: %s（还没跑出结果）" % " ".join(uncovered))
    else:
        print("验收:   矩阵为空（GOAL.md 未填）")
    if script_green and not verified_green:
        print("待验收: 脚本全绿，尚未独立收轮（verifier → close-round）")
    print("零进展: %s/2" % streak)
    print("停止:   %s" % ("触发 → " + "、".join(stops) if stops else "未触发"))
    round_events = [e for e in events if e.get("type") == "round"]
    if round_events:
        last = round_events[-1]
        print("上轮:   r-%s %s · 关闭 %s · %s"
              % (last.get("round"), last.get("verdict", "?"),
                 last.get("tasks_closed", 0), "有进展" if last.get("progress") else "零进展"))
    pending = open_inbox_count(ap)
    print("待决:   %d 条%s" % (pending, "（解决后才好继续：inbox.py list）" if pending else ""))
    if ready:
        print("可派发: %s%s" % (" ".join(str(x) for x in ready[:12]), " …" if len(ready) > 12 else ""))
    elif tasks:
        print("可派发: 无（依赖未满足或已全部完成）")
    print("闸门:   %s" % gate_text)
    for w in TS_WARNINGS:
        print("警告:   %s" % w)
    print("台账:   %s" % os.path.join(ap, "ledger.jsonl"))
    return 0


def cmd_log(root, payload):
    ap = os.path.join(root, ".autopilot")
    if not os.path.isdir(ap):
        print("没有 %s（先跑 init.sh）" % ap)
        return 2
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        print("事件不是合法 JSON: %s" % exc)
        return 2
    if not isinstance(event, dict):
        print("事件必须是 JSON 对象")
        return 2
    append_ledger(ap, event)
    return 0


A_TOKEN_RE = re.compile(r"\bA\d{1,3}\b")
# "出现过的编号"太宽：注释里写一句 A29 就会被算成有判定源。只认**发射位点**三种形态：
# ① `RESULT A18 ...`；② 引号里的 'A18'/"A18"（accept.mjs 与探针页都用这两种）；
# ③ 引号里的 `A18:a18` 映射对——数据驱动的工装（run.sh 的探针组表）靠它自己迭代出 RESULT 行，
#    不带引号或后面不是「:探针键」的注释提到一律不算。
A_EMIT_RE = re.compile(
    r"""(?:RESULT\s+(?P<res>A\d{1,3})\b"""
    r"""|['"](?P<lit>A\d{1,3})['"]"""
    r"""|['"](?P<map>A\d{1,3}):[A-Za-z][\w-]*['"])""")
CHECK_EXTS = (".sh", ".mjs", ".js", ".py", ".html", ".txt", ".md", ".json")


def judging_sources(ap):
    """冻结面里出现过的验收编号集合 = 潜在判定源。

    只算会被 MANIFEST 保护的判定文件；`MANIFEST.sha256` / `last.log` / `last-result.json`
    是产物或索引，出现过的编号不能当判定源。
    """
    cdir = os.path.join(os.path.abspath(ap), "checks")
    found = set()
    try:
        names = sorted(os.listdir(cdir))
    except OSError:
        return found, cdir
    for name in names:
        if name in ("MANIFEST.sha256", "last.log", "last-result.json") or not name.endswith(CHECK_EXTS):
            continue
        try:
            with open(os.path.join(cdir, name), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for m in A_EMIT_RE.finditer(text):
            found.add(m.group("res") or m.group("lit") or m.group("map"))
    return found, cdir


IDS_ARRAY_RE = re.compile(r"^\s*[A-Za-z_]*IDS\w*=\(([^)]*)\)", re.M)


PAIR_MAP_RE = re.compile(r"""['"](A\d{1,3}):([A-Za-z][\w-]*)['"]""")


def unwired_pairs(ap):
    """H41：run.sh 的映射表里接了 `A#:探针键`，但没有任何探针页真会上报这个键。

    为什么单独列一档：这九条（ContraRunner 的 A26-A28/A34-A35/A37-A39/A42）跑出来是
    `FAIL 探针页未上报该条`，而 FAIL 里混着两种完全不同的原因——产品没做 vs 尺子没接。
    派工前就能机检出来的事，不该等工人跑 15 分钟回来才发现"这张卡结构上做不绿"。

    只报告，不改判定：这些条目仍由冻结 run.sh 的 RESULT 行说话（永久红线 3）。
    """
    cdir = os.path.join(os.path.abspath(ap), "checks")
    run_sh = os.path.join(cdir, "run.sh")
    try:
        with open(run_sh, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError:
        return []
    pages = []
    try:
        names = sorted(os.listdir(cdir))
    except OSError:
        names = []
    for fn in names:
        if not fn.endswith(".html"):
            continue
        try:
            with open(os.path.join(cdir, fn), encoding="utf-8", errors="replace") as fh:
                pages.append(fh.read())
        except OSError:
            continue
    out = []
    seen = set()
    for aid, key in PAIR_MAP_RE.findall(body):
        if (aid, key) in seen:
            continue
        seen.add((aid, key))
        quoted = ['"%s"' % key, "'%s'" % key, "%s:" % key, '"%s":' % key]
        if not any(q in text for text in pages for q in quoted):
            out.append((aid, key))
    return out


def declared_ids(ap):
    """run.sh 里 `*_IDS=(...)` 声明的编号——只有进了数组才享有三条兜底
    （缺 node / 缺浏览器 / 探针未就绪 → 组内每条打 FAIL，而不是静默缺席）。"""
    p = os.path.join(os.path.abspath(ap), "checks", "run.sh")
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return set()
    out = set()
    for body in IDS_ARRAY_RE.findall(text):
        out.update(A_TOKEN_RE.findall(body))
    return out


def coverage_numbers(ap):
    """判定覆盖率的唯一算式：契约条目 / 有判定源 / 受数组保护 / WEAK / 无源。

    H38 的 `coverage` 子命令、H19 的 `metrics` 与看板的覆盖率卡片都读它——
    三处各算一遍迟早会给出三个分母，而分母用错正是"17/17 全绿"那种事故的来源。
    """
    ids = acceptance_ids(ap)
    if not ids:
        return {"contract_items": 0, "with_source": 0, "ratio": None,
                "protected_by_arrays": 0, "weak_not_in_arrays": [], "no_source": [],
                "note": "GOAL 无矩阵行"}
    sources, _ = judging_sources(ap)
    declared = declared_ids(ap)
    covered = [i for i in ids if i in sources]
    missing = [i for i in ids if i not in sources]
    weak = sorted(set(covered) - declared, key=lambda x: int(x[1:]))
    return {"contract_items": len(ids), "with_source": len(covered),
            "ratio": round(float(len(covered)) / len(ids), 4),
            "protected_by_arrays": len(set(covered) & declared),
            "weak_not_in_arrays": weak, "no_source": missing}


def cmd_coverage(root, allow_partial=""):
    """H38 冻结前的覆盖闸门：GOAL 矩阵里的每条 A# 都得在 checks/ 里找得到判定源。

    立规理由：H37 装在收轮处，属于"已经晚了"的位置。ContraRunner 的根因是**冻结时 run.sh
    只声明了 17 条 id，而契约写了 47 条**——缺陷照样被冻进 MANIFEST。所以把它前移到 freeze。
    `--allow-partial` 只给"分批冻结"这种真实场景：理由 ≥20 字、落账本、REPORT 必须声明。
    """
    ap = os.path.join(os.path.abspath(root), ".autopilot")
    if not os.path.isdir(ap):
        print("COVERAGE 2 没有 %s（先跑 init.sh）" % ap)
        return 2
    ids = acceptance_ids(ap)
    if not ids:
        print("COVERAGE 0 GOAL 里没有 | A# | 矩阵行——无契约条目可核对（老工作区行为不变）")
        return 0
    sources, cdir = judging_sources(ap)
    if not sources:
        print("COVERAGE 2 找不到 %s，或其中没有任何判定文件" % cdir)
        return 2
    missing = [i for i in ids if i not in sources]
    weak = sorted((set(ids) & sources) - declared_ids(ap), key=lambda x: int(x[1:]))
    print("COVERAGE 判定源核对：契约 %d 条 · 冻结面命中 %d 条 · 缺 %d 条 · 未纳入兜底数组 %d 条"
          % (len(ids), len(set(ids) & sources), len(missing), len(weak)))
    if weak:
        print("  WEAK：%s%s —— 有判定语句但没进 run.sh 的 *_IDS 数组，"
              "缺少 node/浏览器/探针未就绪三条兜底，异常退出时会静默缺席而不是变红"
              % (" ".join(weak[:12]), " …" if len(weak) > 12 else ""))
    unwired = [(a, k) for (a, k) in unwired_pairs(ap) if a in set(ids)]
    if unwired:
        print("  UNWIRED（映射接了但判定面里查不到这个键，现在拿不到 PASS）：%s"
              % " ".join("%s:%s" % (a, k) for a, k in unwired[:16]))
        print("    —— 缺的是尺子那一格（产品没做是另一种红），补键的卡要走 --allow-checks-edit（H40）；"
              "本行只报告，不改判定，条目结果仍由冻结 run.sh 的 RESULT 行说话")
    if not missing:
        print("COVERAGE 0 全部验收项在冻结面里都有判定源（H38 通过%s）"
              % ("；WEAK 条目请自行判断是否纳入数组" if weak else ""))
        return 0
    print("  缺判定源：%s%s" % (" ".join(missing[:16]), " …" if len(missing) > 16 else ""))
    reason = (allow_partial or "").strip()
    if len(reason) >= 20:
        append_ledger(ap, {"type": "coverage_partial", "missing": missing,
                           "missing_count": len(missing), "reason": reason})
        print("COVERAGE 0 分批冻结放行（理由已落账本）：剩余 %d 条必须在后续提案 + 重冻里补齐，"
              "REPORT 必须声明本 epoch 覆盖不完整" % len(missing))
        return 0
    if reason:
        print("COVERAGE 24 --allow-partial 的理由只有 %d 字（要求 ≥20）：写清为什么这批可以先不判"
              % len(reason))
    else:
        print("COVERAGE 24 拒绝冻结：这些条目在 checks/ 里一条判定语句都没有。"
              "先补判定源（或把工装产物一并放进 checks/），或把它们从本 epoch 的契约里移出去；"
              "确需分批冻结用 --allow-partial \"<≥20 字理由>\"（落账本并要求 REPORT 声明）")
    return 24


def cmd_phase(root, phase):
    ap = os.path.join(root, ".autopilot")
    path = os.path.join(ap, "state.json")
    state = load_json(path)
    if not state:
        print("读不到 %s（先跑 init.sh）" % path)
        return 2
    if phase not in PHASES:
        print("阶段只能是: %s" % " / ".join(PHASES))
        return 2
    # H37：手工把阶段推到 report（= 声称这一轮次序列做完了）时，同样要过覆盖检查。
    # 没有轮次文档时不设闸——老工作区与刚 init 的工作区行为不变。
    if phase == "report":
        ids = acceptance_ids(ap)
        latest_path = latest_round_doc(ap)
        if ids and latest_path:
            latest = load_json(latest_path)
            if isinstance(latest, dict) and str(latest.get("verdict") or "").lower() == "pass":
                covered = set()
                for key in ("passed", "failed", "skipped"):
                    val = latest.get(key)
                    if isinstance(val, list):
                        covered.update(str(x).strip() for x in val)
                missing = [i for i in ids if i not in covered]
                if missing:
                    print("COVERAGE CHECK 拒绝进入 report: 最新一轮（%s）声称 pass，"
                          "但 GOAL 矩阵有 %d 条从未跑出判定：%s"
                          % (os.path.basename(latest_path), len(missing), " ".join(missing[:12])))
                    print("未覆盖 ≠ 已完成。先让冻结通道覆盖它们（改 checks/ 走提案 + 重冻），"
                          "或按事实把 verdict 改成 fail / 给它们 SKIP 理由")
                    return 24
    state["phase"] = phase
    dump_json(path, state)
    print("阶段: %s" % phase)
    return 0


def cmd_budget(root, assignments):
    """H8/H23：给长跑加/收紧预算维度。**只准设正数，不准设 0 或删档** ——
    放宽预算属契约动作，必须由人在 state.json 上动手，不交给控制器自己放水。
    """
    ap = os.path.join(root, ".autopilot")
    path = os.path.join(ap, "state.json")
    if not os.path.isdir(ap):
        print("没有 %s（先跑 init.sh）" % ap)
        return 2
    keys = {"max_tool_calls": to_int, "max_usd": to_float, "max_minutes": to_int,
            "max_calls": to_int, "max_rounds": to_int, "max_tasks_per_round": to_int}
    parsed = {}
    for item in assignments:
        if "=" not in item:
            print("用法: status.py budget <root> max_tool_calls=400 [max_usd=20]")
            return 2
        k, v = item.split("=", 1)
        k = k.strip()
        if k not in keys:
            print("BUDGET 未知维度 %s（可写：%s）" % (k, " / ".join(sorted(keys))))
            return 2
        val = keys[k](v.strip(), None)
        if val is None or val <= 0:
            print("BUDGET %s 必须是正数；**放宽或取消上限属契约变更，请人工改 state.json**" % k)
            return 24
        parsed[k] = val
    try:
        release = acquire_state_lock(ap)
    except TimeoutError as exc:
        print("LOCK TIMEOUT %s" % exc)
        return 20
    try:
        state = load_json(path, {})
        if not isinstance(state, dict):
            print("读不到 %s" % path)
            return 2
        budget = state.get("budget") if isinstance(state.get("budget"), dict) else {}
        for k, v in parsed.items():
            old = keys[k](budget.get(k), None)
            if old is not None and old > 0:
                kept = min(old, v)
                if kept != v:
                    print("BUDGET %s 已有上限 %s，请求 %s 更宽 → 保留更严的 %s"
                          % (k, old, v, kept))
                budget[k] = kept
            else:
                budget[k] = v
        state["budget"] = budget
        atomic_dump_json(path, state)
    finally:
        release()
    append_ledger(ap, {"type": "budget", "actor": "status.py", "requested": parsed,
                       "applied": {k: budget.get(k) for k in sorted(parsed)}})
    print("BUDGET 已更新: " + " ".join("%s=%s" % (k, budget.get(k)) for k in sorted(parsed)))
    return 0


def cmd_clock(root, kind, note):
    """H9：把"墙钟在走但没干活"的时段记下来（pause / resume 配对）。

    只用于报告与量化。停止条件仍然按墙钟算 —— 想按活跃时长判定，必须人工改 GOAL，
    控制器不能自己把预算放宽（只准收紧或持平）。
    """
    ap = os.path.join(root, ".autopilot")
    if not os.path.isdir(ap):
        print("没有 %s（先跑 init.sh）" % ap)
        return 2
    last = None
    for e in read_ledger(ap):
        if isinstance(e, dict) and e.get("type") in ("pause", "resume"):
            last = e.get("type")
    if last == kind:
        print("CLOCK 已经在 %s 状态，不重复记账" % kind)
        return 0
    if kind == "resume" and last != "pause":
        print("CLOCK resume 之前没有未闭合的 pause（先跑 status.py pause）")
        return 2
    if kind == "pause" and last is None and note == "":
        print("CLOCK pause 建议带 --note <原因>，便于事后量化")
    append_ledger(ap, {"type": kind, "actor": "status.py", "note": note or ""})
    print("CLOCK %s 已记账%s" % (kind, ("（%s）" % note) if note else ""))
    return 0


def cmd_close_round(root, round_path):
    ap = os.path.join(root, ".autopilot")
    if not os.path.isdir(ap):
        print("没有 %s（先跑 init.sh）" % ap)
        return 2
    round_doc = load_json(round_path)
    if not isinstance(round_doc, dict) or not round_doc:
        print("读不到轮次结果: %s" % round_path)
        return 2
    state = load_json(os.path.join(ap, "state.json"))
    if not isinstance(state, dict) or not state:
        print("读不到 %s（先跑 init.sh）" % os.path.join(ap, "state.json"))
        return 2

    round_no = to_int(round_doc.get("round"), 0) or 0
    closed = state.setdefault("closed_rounds", [])
    if not isinstance(closed, list):
        closed = []
        state["closed_rounds"] = closed
    if round_no and round_no in closed:
        print("第 %d 轮已经收过，跳过（防重复计数）" % round_no)
        return 0

    events = read_ledger(ap)
    tasks = load_tasks(ap)

    # ---- flex 用量：本轮增量 = 收轮时的累计 − 上一轮收轮时的累计，避免重复计数
    gate = read_gate(root, ap)
    cur = flex_snapshot(gate)
    prev_no, prev_cum = None, None
    prev = latest_record_before(ap, round_no)
    if prev:
        prev_no = prev[0]
        prev_flex = prev[1].get("flex")
        if isinstance(prev_flex, dict) and isinstance(prev_flex.get("cumulative"), dict):
            prev_cum = prev_flex["cumulative"]
    epoch_bump = contract_change(round_doc, prev[1] if prev else None)
    light_delta = _delta(cur["light_used"], (prev_cum or {}).get("light_used"))
    heavy_delta = _delta(cur["heavy_used"], (prev_cum or {}).get("heavy_used"))
    flex_delta = _delta(cur["flex_calls"], (prev_cum or {}).get("flex_calls"))
    dec_total_delta = _delta(cur["decisions_total"], (prev_cum or {}).get("decisions_total"))
    dec_flex_delta = _delta(cur["decisions_flex"], (prev_cum or {}).get("decisions_flex"))
    dec_light_delta = _delta(cur["decisions_light"], (prev_cum or {}).get("decisions_light"))
    dec_heavy_delta = _delta(cur["decisions_heavy"], (prev_cum or {}).get("decisions_heavy"))
    gate_total_delta = None
    if light_delta is not None and heavy_delta is not None and flex_delta is not None:
        gate_total_delta = light_delta + heavy_delta + flex_delta

    # ---- 本轮窗口
    start_dt, start_reason = round_start(ap, state, round_doc, round_no, events)
    calls = count_calls(events, start_dt)
    elapsed = None
    if start_dt is not None:
        try:
            elapsed = int((datetime.datetime.now(start_dt.tzinfo) - start_dt).total_seconds() // 60)
        except (TypeError, ValueError, OSError, OverflowError):
            elapsed = None

    rate, rate_basis = flex_usage_rate(
        flex_delta, dec_flex_delta, dec_total_delta, calls, gate_total_delta)
    if rate is None and gate["present"] is False:
        rate_basis = gate.get("reason") or rate_basis

    # ---- 指标
    par, par_reason = max_parallelism(events, tasks, state, round_doc)
    rework, rework_reason = rework_rate(events, tasks, start_dt, calls)

    metrics = {
        "round": round_no,
        # H19 × H38 同源：收轮就把判定覆盖率一起落盘，看板与指标读同一份数，不再各算一遍
        "coverage": coverage_numbers(ap),
        "calls_used": calls,
        # H8：工具调用数本地可数；成本只认宿主上报（source == "host"）
        "tool_calls_used": sum(1 for e in events if e.get("type") == "tool"),
        "host_reported_usd": sum(to_float(e.get("usd"), 0.0) or 0.0
                                 for e in events
                                 if e.get("type") == "usage" and e.get("source") == "host"),
        "elapsed_minutes": elapsed,
        # H9：pause/resume 有记账时补活跃时长；没有就保持 None（口径与旧版完全一致）
        "slept_minutes": slept_minutes(events),
        "active_minutes": (elapsed - slept_minutes(events)
                           if elapsed is not None and slept_minutes(events) is not None else None),
        "max_parallel": par,
        "rework_rate": rework,
        "flex_usage_rate": rate,
        "unknown_reasons": {},
        "detail": {
            "window_start": start_dt.astimezone(datetime.timezone.utc).isoformat(timespec="seconds") if start_dt else None,
            "window_start_source": start_reason,
            "contract_change": epoch_bump,
            "flex_usage_rate_basis": rate_basis,
            "flex": {
                "light": light_delta if light_delta is not None else dec_light_delta,
                "heavy": heavy_delta if heavy_delta is not None else dec_heavy_delta,
                "flex": flex_delta if flex_delta is not None else dec_flex_delta,
                "decisions": dec_total_delta,
                "flex_decisions": dec_flex_delta,
                "cumulative": cur,
                "base_round": prev_no,
                "source": gate.get("path"),
            },
        },
        "generated_at": now_iso(),
    }
    if metrics["calls_used"] is None:
        metrics["unknown_reasons"]["calls_used"] = "账本里没有 worker/verifier 事件"
    if metrics["elapsed_minutes"] is None:
        metrics["unknown_reasons"]["elapsed_minutes"] = "本轮起点未知（%s）" % start_reason
    if metrics["max_parallel"] is None:
        metrics["unknown_reasons"]["max_parallel"] = par_reason
    if metrics["rework_rate"] is None:
        metrics["unknown_reasons"]["rework_rate"] = rework_reason
    if metrics["flex_usage_rate"] is None:
        metrics["unknown_reasons"]["flex_usage_rate"] = rate_basis

    # ---- 轮次记录（保留旧字段，只加 flex 相关字段）
    flex_block = {
        "light": metrics["detail"]["flex"]["light"],
        "heavy": metrics["detail"]["flex"]["heavy"],
        "flex": metrics["detail"]["flex"]["flex"],
        "decisions": dec_total_delta,
        "flex_decisions": dec_flex_delta,
        "usage_rate": rate,
        "usage_rate_basis": rate_basis,
        "cumulative": cur,
        "base_round": prev_no,
        "source": gate.get("path"),
    }

    record = {}
    canonical = round_record_path(ap, round_no) if round_no else None
    existing = load_json(canonical, None) if canonical else None
    if isinstance(existing, dict):
        record.update(existing)
    for key, value in round_doc.items():
        if key not in ("flex", "closed", "closed_at", "metrics_file"):
            record[key] = value
    # 已经打过的收轮标记不覆盖（只补内容，不改标记含义）
    if isinstance(existing, dict) and existing.get("closed"):
        record["closed"] = True
        record["closed_at"] = existing.get("closed_at", now_iso())
    else:
        record["closed"] = True
        record["closed_at"] = now_iso()
    record["flex"] = flex_block
    metrics_rel = ""
    if round_no:
        metrics_rel = os.path.join("rounds", "r-%02d.metrics.json" % round_no)
        record["metrics_file"] = metrics_rel

    # ---- H12 收轮一致性校验：声明的 tasks_closed 必须与 tasks.json 的记账对得上
    #      只对"有记账字段"的工作区生效（closed_round 或 ended_at），老工作区一律跳过不误伤。
    declared_closed = to_int(round_doc.get("tasks_closed"), 0) or 0
    trackable = [t for t in tasks if isinstance(t, dict)
                 and (t.get("closed_round") not in (None, "") or t.get("ended_at"))]
    if trackable:
        actual_closed, undecidable = 0, 0
        for t in trackable:
            if t.get("closed_round") not in (None, ""):
                if to_int(t.get("closed_round"), 0) == round_no:
                    actual_closed += 1
                continue
            ended = parse_ts(t.get("ended_at"))
            if ended is None or start_dt is None:
                undecidable += 1
            elif ended >= start_dt:
                actual_closed += 1
        if undecidable:
            print("CLOSE CHECK 跳过（%d 张卡只有 ended_at，且本轮起点未知，不做判定）" % undecidable)
        elif actual_closed != declared_closed:
            print("CLOSE CHECK 拒绝收轮: r-%02d.json 声明 tasks_closed=%d，"
                  "但 tasks.json 本轮记账是 %d（依据 closed_round / ended_at 落在本轮窗口内）"
                  % (round_no, declared_closed, actual_closed))
            print("先对齐记账再收轮：确实关闭就走 status.py task set <T-xx> done，"
                  "没关闭就把卡改回原状态；不要手改 tasks.json，也不要改轮次报告凑数")
            return 24
        else:
            print("CLOSE CHECK 通过：本轮关闭 %d 个任务，与 tasks.json 记账一致" % actual_closed)

    # ---- 判定覆盖检查（H37）：声称 pass 却有验收项一条 RESULT 都没跑出来 → 拒绝收轮（零写盘）。
    # 立规理由：ContraRunner r-05 实测——`run.sh` 的 id 数组只列了 A1–A17，GOAL 矩阵有 47 条。
    # 数组外的条目即使永远没有 RESULT 行，也不会让任何检查变红，"未覆盖"就静默变成了"已完成"。
    if str(round_doc.get("verdict") or "").strip().lower() == "pass":
        ids = acceptance_ids(ap)
        if ids:
            covered = set()
            for key in ("passed", "failed", "skipped"):
                val = round_doc.get(key)
                if isinstance(val, list):
                    covered.update(str(x).strip() for x in val)
            missing = [i for i in ids if i not in covered]
            if missing:
                print("COVERAGE CHECK 拒绝收轮: verdict=pass 但 GOAL 矩阵里 %d 条验收项"
                      "本轮没有任何 RESULT 判定（PASS/FAIL/SKIP 都算判定）：%s"
                      % (len(missing), " ".join(missing[:12])))
                print("要么这些条目还没进冻结通道（先跑 check.sh freeze 并确认 run.sh 的 id 数组覆盖到它们，"
                      "改 checks/ 属契约动作，走提案 + 重冻），要么按事实把 verdict 改成 fail / 给它们 SKIP 理由")
                return 24
            print("COVERAGE CHECK 通过：GOAL 的 %d 条验收项本轮都有判定" % len(ids))

    # ---- 写轮次记录 + 指标
    if round_no:
        try:
            os.makedirs(rounds_dir(ap), exist_ok=True)
        except OSError as exc:
            print("建不出轮次目录 %s: %s" % (rounds_dir(ap), exc))
            return 2
        try:
            dump_json(canonical, record)
        except OSError as exc:
            print("写不了轮次记录 %s: %s" % (canonical, exc))
            return 2
        try:
            dump_json(metrics_record_path(ap, round_no), metrics)
        except OSError as exc:
            print("写不了轮次指标 %s: %s" % (metrics_record_path(ap, round_no), exc))
            return 2
    else:
        print("提醒: 轮次结果里没有 round 字段，跳过轮次记录与指标文件")

    # ---- 状态与台账
    passed = sorted(set(round_doc.get("passed", []) or []))
    prev_passed = set(state.get("last_passed", []) or [])
    tasks_closed = to_int(round_doc.get("tasks_closed"), 0) or 0
    progressed = bool(set(passed) - prev_passed) or tasks_closed > 0 or epoch_bump is not None

    state["rounds_used"] = to_int(state.get("rounds_used"), 0) + 1
    state["no_progress_streak"] = 0 if progressed else to_int(state.get("no_progress_streak"), 0) + 1
    state["last_passed"] = passed
    state["last_verdict"] = round_doc.get("verdict", "fail")
    state["last_round_at"] = now_iso()
    if round_no and round_no not in closed:
        closed.append(round_no)
    checks = load_json(os.path.join(ap, "checks", "last-result.json"), {})
    if not isinstance(checks, dict):
        checks = {}
    checks_ok = bool(checks) and checks.get("exit") == 0 and not checks.get("failed")
    state["phase"] = ("report" if round_doc.get("verdict") == "pass"
                      and not round_doc.get("failed") and checks_ok else "execute")
    try:
        dump_json(os.path.join(ap, "state.json"), state)
    except OSError as exc:
        print("写不了 %s: %s" % (os.path.join(ap, "state.json"), exc))
        return 2

    event = {
        "type": "round",
        "round": state["rounds_used"],
        "verdict": round_doc.get("verdict", "fail"),
        "passed": passed,
        "failed": sorted(set(round_doc.get("failed", []) or [])),
        "tasks_closed": tasks_closed,
        "progress": progressed,
        "contract_change": epoch_bump,
        "notes": round_doc.get("notes", ""),
        # 0.9 新增字段，不改旧字段含义
        "flex": flex_block,
        "closed_at": record["closed_at"],
    }
    if start_dt is not None:
        event["started_at"] = start_dt.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")
    append_ledger(ap, event)

    print("第 %d 轮已收：%s · 关闭 %d 个任务%s · 零进展连击 %s/2"
          % (state["rounds_used"], "通过" if event["verdict"] == "pass" else "未通过",
             tasks_closed,
             (" · 合同 epoch %d→%d" % (epoch_bump["from"], epoch_bump["to"])) if epoch_bump else "",
             state["no_progress_streak"]))
    print("闸门:   light %s · heavy %s · flex %s（调用 %s 次）"
          % (fmt_num(flex_block["light"]), fmt_num(flex_block["heavy"]),
             fmt_num(flex_block["flex"]), calls))
    if metrics_rel:
        print("指标:   %s" % os.path.join(rounds_dir(ap), os.path.basename(metrics_rel)))
    return 0


def cmd_metrics(root, round_arg):
    ap = os.path.join(root, ".autopilot")
    if not os.path.isdir(ap):
        print("没有 %s（先跑 init.sh）" % ap)
        return 2
    if round_arg is None:
        numbers = []
        try:
            for name in os.listdir(rounds_dir(ap)):
                m = re.match(r"^r-(\d+)\.metrics\.json$", name)
                if m:
                    numbers.append(int(m.group(1)))
        except OSError:
            pass
        if not numbers:
            print("还没有轮次指标（先跑 close-round）")
            return 2
        round_no = max(numbers)
    else:
        round_no = to_int(round_arg)
        if round_no is None:
            print("轮次号不合法: %s" % round_arg)
            return 2
    path = metrics_record_path(ap, round_no)
    doc = load_json(path, None)
    if not isinstance(doc, dict):
        print("读不到轮次指标: %s" % path)
        return 2
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- 入口

class ZhParser(argparse.ArgumentParser):
    """argparse 默认报英文错误，这里换成中文，且一定以非零码退出。"""

    def error(self, message):
        self.print_usage(sys.stderr)
        print("参数不对: %s" % message, file=sys.stderr)
        sys.exit(2)


def build_parser():
    parser = ZhParser(prog="status.py", description="autopilot 账本工具（0.9）")
    sub = parser.add_subparsers(dest="cmd", metavar="子命令")

    p_summary = sub.add_parser("summary", help="轮次汇总（0.8 同款）")
    p_summary.add_argument("root", nargs="?", default=os.getcwd(), help="仓库目录")

    p_log = sub.add_parser("log", help="往台账追加一条事件")
    p_log.add_argument("root", help="仓库目录")
    p_log.add_argument("payload", nargs=argparse.REMAINDER, help="JSON 事件")

    p_phase = sub.add_parser("phase", help="切换阶段")
    p_phase.add_argument("root", help="仓库目录")
    p_phase.add_argument("phase", help="intake / plan / execute / verify / report")

    p_close = sub.add_parser("close-round", help="收轮（可重复执行）")
    p_close.add_argument("root", help="仓库目录")
    p_close.add_argument("round_json", help="轮次结果 JSON")

    p_metrics = sub.add_parser("metrics", help="打印某轮指标（0.9 新增）")
    p_metrics.add_argument("root", help="仓库目录")
    p_metrics.add_argument("round", nargs="?", default=None, help="轮次号，缺省取最后一轮")

    p_task = sub.add_parser("task", help="任务状态单写者（P2 并发，带锁更新 tasks.json）")
    p_task.add_argument("root", help="仓库目录")
    p_task.add_argument("action", choices=["set", "list"])
    p_task.add_argument("id", nargs="?", default=None, help="任务 ID（set 必填）")
    p_task.add_argument("status", nargs="?", default=None, help="目标状态（set 必填）")
    p_task.add_argument("--note", default=None, help="写进 last_error 的说明（failed 时）")
    p_task.add_argument("--json", action="store_true", help="list 输出 JSON")

    for name, helptxt in (("pause", "开始一段不计工作的暂停（H9 时间账）"),
                          ("resume", "结束暂停，回到工作状态（H9 时间账）")):
        p = sub.add_parser(name, help=helptxt)
        p.add_argument("root", nargs="?", default=os.getcwd(), help="仓库目录")
        p.add_argument("--note", default="", help="原因，进账本")

    p_cov = sub.add_parser("coverage", help="冻结前覆盖闸门（H38）：GOAL 每条 A# 都要在 checks/ 里有判定源")
    p_cov.add_argument("root", nargs="?", default=os.getcwd(), help="仓库目录")
    p_cov.add_argument("--allow-partial", default="", help="分批冻结的理由（≥20 字，落账本）")

    p_budget = sub.add_parser("budget", help="加设/收紧多维预算（H8/H23，只准收紧）")
    p_budget.add_argument("root", help="仓库目录")
    p_budget.add_argument("assign", nargs=argparse.REMAINDER, help="max_tool_calls=400 [max_usd=20]")
    return parser


def dispatch(args):
    if args.cmd == "summary":
        return cmd_summary(os.path.abspath(args.root))
    if args.cmd == "log":
        payload = " ".join(args.payload or []).strip()
        if not payload:
            print("用法: status.py log <root> '<json事件>'")
            return 2
        return cmd_log(os.path.abspath(args.root), payload)
    if args.cmd == "coverage":
        return cmd_coverage(os.path.abspath(args.root), args.allow_partial)
    if args.cmd == "phase":
        return cmd_phase(os.path.abspath(args.root), args.phase)
    if args.cmd in ("pause", "resume"):
        return cmd_clock(os.path.abspath(args.root), args.cmd, args.note)
    if args.cmd == "budget":
        return cmd_budget(os.path.abspath(args.root), list(args.assign or []))
    if args.cmd == "close-round":
        return cmd_close_round(os.path.abspath(args.root), args.round_json)
    if args.cmd == "metrics":
        return cmd_metrics(os.path.abspath(args.root), args.round)
    if args.cmd == "task":
        root = os.path.abspath(args.root)
        if args.action == "list":
            return task_list(root, args.json)
        if not args.id or not args.status:
            print("用法: status.py task <root> set <T-xx> <status> [--note ...]")
            return 2
        try:
            return task_update(root, args.id, args.status, args.note)
        except TimeoutError as exc:
            print("锁超时: %s" % exc, file=sys.stderr)
            return 20
    print("用法: status.py <summary|log|phase|close-round|metrics|task> ...")
    return 2


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["summary"]  # 与 0.8 一致：不给参数就打印当前目录的汇总
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if not getattr(args, "cmd", None):
        parser.print_usage(sys.stderr)
        print("参数不对: 缺少子命令（summary / log / phase / close-round / metrics）", file=sys.stderr)
        return 2
    try:
        return dispatch(args)
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130
    except Exception as exc:  # 用户看到的永远是中文提示，不是裸 traceback
        print("出错: %s: %s" % (exc.__class__.__name__, exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
