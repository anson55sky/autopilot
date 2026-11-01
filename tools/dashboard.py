#!/usr/bin/env python3
"""H15 只读看板：把 .autopilot/ 里的状态导出成**单个静态 HTML**（无常驻后端、无外部依赖）。

用法:
  dashboard.py render --repo <path> [--out <相对路径>] [--rounds 8]
  dashboard.py check  --repo <path>            # 只报当前状态摘要，不出文件（给监督者快速看）

设计约束（不是可选项）：
  - 只读 `.autopilot/`，**绝不写项目源码、绝不改 checks/ 与轮次报告**。
  - 单文件、内联 CSS/JS，不引任何 CDN、不发任何网络请求（离线可看，也不泄漏）。
  - 本机绝对路径一律替换成 `{REPO_ROOT}`；看板是给人与外部看的，不能带上家目录。
  - 看板**不构成验收证据**：`r-XX.passed` 只认冻结 `run.sh` 的 RESULT 行（永久红线 3）。
"""

import argparse
import datetime
import html
import json
import os
import re
import sys

E_OK, E_USAGE = 0, 2
DEFAULT_OUT = os.path.join(".autopilot", "dashboard", "index.html")
COLOR = {"PASS": "#197d3a", "FAIL": "#b3261e", "SKIP": "#8a6d00", "pending": "#5b6470",
         "doing": "#1b5fa8", "done": "#197d3a", "failed": "#b3261e", "blocked": "#8a6d00",
         "superseded": "#6b7280"}


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def redact(text, repo):
    home = os.path.expanduser("~")
    out = str(text).replace(repo, "{REPO_ROOT}")
    if home and home != repo:
        out = out.replace(home, "{HOME}")
    return out


def esc(text, repo=""):
    return html.escape(redact(text, repo), quote=False)


def load_state(repo):
    ap = os.path.join(repo, ".autopilot")
    state = read_json(os.path.join(ap, "state.json"), {}) or {}
    tasks_doc = read_json(os.path.join(ap, "tasks.json"), {}) or {}
    result = read_json(os.path.join(ap, "checks", "last-result.json"), {}) or {}
    env = read_json(os.path.join(ap, "environment.json"), {}) or {}
    host = read_json(os.path.join(ap, "host.json"), {}) or {}
    tasks = tasks_doc.get("tasks") if isinstance(tasks_doc.get("tasks"), list) else []
    rounds = []
    try:
        for name in sorted(os.listdir(os.path.join(ap, "rounds"))):
            if re.match(r"^r-\d+\.json$", name):
                doc = read_json(os.path.join(ap, "rounds", name), {}) or {}
                doc["_file"] = name
                rounds.append(doc)
    except OSError:
        pass
    ledger = []
    try:
        with open(os.path.join(ap, "ledger.jsonl"), encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        ledger.append(json.loads(line))
                    except ValueError:
                        continue
    except FileNotFoundError:
        pass
    metrics = {}
    if rounds:
        cand = os.path.join(ap, "rounds", rounds[-1]["_file"].replace(".json", ".metrics.json"))
        metrics = read_json(cand, {}) or {}
    return {"ap": ap, "state": state, "tasks": tasks, "result": result, "env": env,
            "host": host, "rounds": rounds, "ledger": ledger, "metrics": metrics,
            "epoch": tasks_doc.get("epoch") if isinstance(tasks_doc, dict) else None}


def badge(kind, label=None):
    color = COLOR.get(kind, "#5b6470")
    return ('<span class="b" style="background:%s">%s</span>'
            % (color, html.escape(str(label if label is not None else kind))))


def render_html(repo, data, rounds_show=8):
    state, budget = data["state"], (data["state"].get("budget") or {})
    tasks, result = data["tasks"], data["result"]
    passed = result.get("passed") or []
    failed = result.get("failed") or []
    skipped = result.get("skipped") or []
    done = [t for t in tasks if t.get("status") == "done"]
    rounds = data["rounds"][-rounds_show:]
    ledger = data["ledger"][-200:]
    caps = (data["env"].get("capabilities") or {})
    gen = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    task_rows = "".join(
        "<tr data-s='%s'><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            html.escape(str(t.get("status", "pending")), quote=True),
            html.escape(str(t.get("id"))),
            badge(str(t.get("status", "pending"))),
            html.escape(str(t.get("title") or "")),
            html.escape(", ".join(t.get("write_set") or [])),
            html.escape(", ".join(t.get("acceptance") or [])),
        ) for t in tasks)
    round_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            html.escape(str(r.get("_file"))),
            badge(str(r.get("verdict", "unknown"))),
            str(len(r.get("passed") or [])),
            str(len(r.get("failed") or [])) + " / SKIP " + str(len(r.get("skipped") or [])),
            html.escape(str(r.get("notes") or "")[:120]),
        ) for r in reversed(rounds))
    ledger_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            html.escape(str(e.get("ts") or e.get("time") or "")),
            html.escape(str(e.get("type"))),
            html.escape(str(e.get("task") or e.get("round") or "")),
            html.escape(redact(str(e.get("note") or e.get("reason") or ""), repo)[:160]),
        ) for e in reversed(ledger))
    cap_items = "".join("<li>%s %s</li>" % (badge("PASS" if v else "SKIP", k),
                                            html.escape(str(v if v else "缺失")))
                        for k, v in sorted(caps.items()) if not k.startswith("_"))
    deps_note = "".join("<li>%s ← %s</li>" % (html.escape(str(t.get("id"))),
                                               html.escape(", ".join(t.get("deps") or []) or "无"))
                        for t in tasks if (t.get("deps") or []))
    caps_line = cap_items or "<li>未探测（跑 environ.py probe）</li>"
    deps_count = len([t for t in tasks if t.get("deps")])
    host_name = str(data["host"].get("host") or state.get("host") or "generic-cli")
    # 时间/调用来自最近一轮 metrics（没有就留空，不猜数）
    met = data.get("metrics") or {}
    wall = "%s / %s 分" % (met.get("elapsed_minutes", "-"), budget.get("max_minutes", "-"))
    calls_line = "%s / %s" % (met.get("calls_used", "-"), budget.get("max_calls", "-"))
    page = HTML_TMPL
    for token, value in (
            ("@@TITLE@@", esc(state.get("goal", ""), repo)[:60]),
            ("@@EPOCH@@", str(data.get("epoch"))),
            ("@@PHASE@@", str(state.get("phase"))),
            ("@@ROUNDS@@", "%s/%s" % (state.get("rounds_used"), budget.get("max_rounds", "-"))),
            ("@@GEN@@", gen),
            ("@@PASS@@", "%d / %d" % (len(passed), len(passed) + len(failed) + len(skipped))),
            ("@@FAIL@@", str(len(failed))),
            ("@@SKIP@@", str(len(skipped))),
            ("@@TASKS@@", "%d / %d" % (len(done), len(tasks))),
            ("@@WALL@@", wall),
            ("@@CALLS@@", calls_line),
            ("@@TASKROWS@@", task_rows or "<tr><td colspan=5>tasks.json 为空</td></tr>"),
            ("@@DEPCOUNT@@", str(deps_count)),
            ("@@DEPS@@", deps_note or "<li>无依赖边</li>"),
            ("@@ROUNDROWS@@", round_rows or "<tr><td colspan=5>还没有收轮记录</td></tr>"),
            ("@@CAPS@@", caps_line),
            ("@@HOST@@", host_name),
            ("@@LEDGER@@", ledger_rows or "<tr><td colspan=4>账本为空</td></tr>")):
        page = page.replace(token, value)
    return page


HTML_TMPL = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>autopilot 看板 · @@TITLE@@</title>
<style>
 body{font:14px/1.6 -apple-system,"Segoe UI",sans-serif;margin:0;background:#f6f7f9;color:#1c2024}
 header{background:#12283c;color:#fff;padding:14px 20px}
 header h1{margin:0;font-size:16px;font-weight:600}
 header .sub{opacity:.75;font-size:12px}
 main{max-width:1180px;margin:0 auto;padding:18px 20px 40px}
 .cards{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
 .card{background:#fff;border:1px solid #e3e6ea;border-radius:8px;padding:10px 14px;min-width:150px}
 .card b{display:block;font-size:20px;margin-top:2px}
 .b{display:inline-block;color:#fff;border-radius:4px;padding:1px 7px;font-size:11.5px}
 section{background:#fff;border:1px solid #e3e6ea;border-radius:8px;margin:0 0 14px;padding:12px 14px}
 h2{font-size:13px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.04em;color:#5b6470}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #eef0f3;vertical-align:top}
 th{color:#5b6470;font-weight:600;font-size:11.5px;text-transform:uppercase}
 ul{margin:0;padding-left:18px}
 input{padding:6px 8px;border:1px solid #cfd5db;border-radius:6px;font-size:13px;width:220px}
 .note{font-size:12px;color:#5b6470}
 .two{display:flex;gap:14px;flex-wrap:wrap}.two>div{flex:1 1 320px}
</style></head>
<body>
<header>
  <h1>autopilot 看板 · @@TITLE@@</h1>
  <div class="sub">epoch @@EPOCH@@ · 阶段 @@PHASE@@ · 轮次 @@ROUNDS@@ · 生成于 @@GEN@@ · 只读快照，不构成验收证据</div>
</header>
<main>
  <div class="cards">
    <div class="card">验收 PASS<b style="color:#197d3a">@@PASS@@</b></div>
    <div class="card">FAIL<b style="color:#b3261e">@@FAIL@@</b></div>
    <div class="card">SKIP（未判定）<b style="color:#8a6d00">@@SKIP@@</b></div>
    <div class="card">任务关闭<b>@@TASKS@@</b></div>
    <div class="card">墙钟 / 预算<b>@@WALL@@</b></div>
    <div class="card">调用 / 预算<b>@@CALLS@@</b></div>
  </div>

  <section><h2>任务与 DAG（依赖只在同 epoch 内成立）</h2>
    <input id="q" placeholder="过滤任务…" onkeyup="flt()">
    <table id="tasks"><thead><tr><th>ID</th><th>状态</th><th>标题</th><th>写集</th><th>覆盖验收</th></tr></thead>
    <tbody>@@TASKROWS@@</tbody></table>
    <details><summary class="note">依赖边（@@DEPCOUNT@@ 条）</summary><ul>@@DEPS@@</ul></details>
  </section>

  <section><h2>轮次</h2>
    <table><thead><tr><th>轮次文件</th><th>判定</th><th>PASS</th><th>FAIL/SKIP</th><th>说明（截断）</th></tr></thead>
    <tbody>@@ROUNDROWS@@</tbody></table></section>

  <div class="two">
    <section style="flex:1 1 340px"><h2>环境能力（缺即 SKIP，不算绿）</h2><ul>@@CAPS@@</ul>
      <p class="note">宿主：<b>@@HOST@@</b>，原语缺失时 REPORT 必须出降级声明。</p></section>
    <section style="flex:1 1 480px"><h2>账本（最近 200 条）</h2>
      <table><thead><tr><th>时间</th><th>类型</th><th>对象</th><th>说明</th></tr></thead>
      <tbody>@@LEDGER@@</tbody></table></section>
  </div>
  <p class="note">数据源：<code>.autopilot/</code> 下 state / tasks / checks/last-result / rounds / ledger / environment / host。
     本文件由 <code>tools/dashboard.py render</code> 生成，路径已脱敏为 {REPO_ROOT}。</p>
</main>
<script>
function flt(){var v=document.getElementById('q').value.toLowerCase();
 document.querySelectorAll('#tasks tbody tr').forEach(function(r){
   r.style.display = r.textContent.toLowerCase().indexOf(v)>-1?'':'none';});}
</script>
</body></html>
"""



def cmd_render(args):
    repo = os.path.abspath(args.repo)
    data = load_state(repo)
    out = args.out or DEFAULT_OUT
    target = out if os.path.isabs(out) else os.path.join(repo, out)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(render_html(repo, data, args.rounds))
    print("DASHBOARD 0 写出 %s（只读快照；tasks %d · rounds %d · ledger %d）"
          % (os.path.relpath(target, repo), len(data["tasks"]), len(data["rounds"]), len(data["ledger"])))
    return E_OK


def cmd_check(args):
    repo = os.path.abspath(args.repo)
    data = load_state(repo)
    result = data["result"]
    print("DASHBOARD 0 phase=%s epoch=%s 任务 %d（done %d） · 验收 PASS %d / FAIL %d / SKIP %d · 轮次 %d · 账本 %d"
          % (data["state"].get("phase"), data.get("epoch"), len(data["tasks"]),
             len([t for t in data["tasks"] if t.get("status") == "done"]),
             len(result.get("passed") or []), len(result.get("failed") or []),
             len(result.get("skipped") or []), len(data["rounds"]), len(data["ledger"])))
    return E_OK


def build_parser():
    p = argparse.ArgumentParser(prog="dashboard.py", description="H15 只读看板（静态单文件）")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("render")
    s.add_argument("--repo", required=True)
    s.add_argument("--out", default="")
    s.add_argument("--rounds", type=int, default=8)
    s.set_defaults(fn=cmd_render)
    s = sub.add_parser("check")
    s.add_argument("--repo", required=True)
    s.set_defaults(fn=cmd_check)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".autopilot")):
        print("没有 %s（先跑 init.sh）" % os.path.join(repo, ".autopilot"))
        return E_USAGE
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
