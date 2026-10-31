#!/usr/bin/env python3
"""autopilot 账本工具（0.9）：轮次汇总、事件记录、阶段切换、收轮、轮次指标。

用法:
  status.py summary [root]
  status.py log <root> '<json事件>'
  status.py phase <root> <intake|plan|execute|verify|report>
  status.py close-round <root> <round.json>
  status.py metrics <root> [round]

0.9 相对 0.8 的变化:
  C3 时间戳健壮：naive / 坏戳 / 空戳一律不崩，显示 unknown。
  C4 收轮幂等：close-round 可重复执行，flex 轮次也不会重复计数。
  C5 轮次指标：每次收轮写 rounds/r-XX.metrics.json。

CLI 与 0.8 完全兼容（同样的子命令、同样的参数名），0.9 是它的超集。
"""

import argparse
import datetime
import json
import os
import re
import sys

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


# ---------------------------------------------------------------- 账本

def append_ledger(ap, event):
    event.setdefault("ts", now_iso())
    with open(os.path.join(ap, "ledger.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


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
    state["phase"] = phase
    dump_json(path, state)
    print("阶段: %s" % phase)
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
        "calls_used": calls,
        "elapsed_minutes": elapsed,
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
    if args.cmd == "phase":
        return cmd_phase(os.path.abspath(args.root), args.phase)
    if args.cmd == "close-round":
        return cmd_close_round(os.path.abspath(args.root), args.round_json)
    if args.cmd == "metrics":
        return cmd_metrics(os.path.abspath(args.root), args.round)
    print("用法: status.py <summary|log|phase|close-round|metrics> ...")
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
