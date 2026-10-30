#!/usr/bin/env python3
"""meta-checks 共享工具：定位脚本目录、搭临时 fixture、跑子命令、输出判定行。

铁律：源码里不出现任何绝对路径或 ~ 前缀（M6 会扫本文件）。
脚本目录靠 __file__ 相对推出，fixture 一律 mktemp。
"""

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir))
SCRIPTS = os.path.normpath(os.path.join(ROOT, "scripts"))


def new_tmp(prefix):
    import tempfile
    return tempfile.mkdtemp(prefix=prefix, dir=os.environ.get("TMPDIR") or None)


def cleanup(path):
    shutil.rmtree(path, ignore_errors=True)


def sh(argv, env=None, cwd=None, timeout=60):
    """跑一条命令，返回 (rc, stdout, stderr)。argv 是列表，第一个元素是脚本路径。"""
    e = dict(os.environ)
    if env:
        e.update({k: v for k, v in env.items() if v is not None})
        for k, v in list(env.items()):
            if v is None:
                e.pop(k, None)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, env=e,
                           cwd=cwd, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as ex:
        return 127, "", f"{type(ex).__name__}: {ex}"


def flex(*args, env=None):
    return sh(["sh", os.path.join(SCRIPTS, "flex-gate.sh"), *args], env=env)


def environ(*args, env=None):
    return sh(["sh", os.path.join(SCRIPTS, "environ.sh"), *args], env=env)


def merge(*args, env=None):
    return sh(["sh", os.path.join(SCRIPTS, "proposal-merge.sh"), *args], env=env)


def emit(mid, status, desc):
    status = status.upper()
    assert status in ("PASS", "FAIL", "SKIP"), status
    print(f"RESULT M{mid} {status} {desc}")
    return 0 if status in ("PASS", "SKIP") else 1


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def build_checks_repo(tmp, run_sh_body="#!/bin/sh\nRESULT A1 PASS ok\nexit 0\n",
                      extra=None):
    """搭一个最小可冻结验收仓库：.autopilot/checks/run.sh + tasks.json + GOAL.md。"""
    ap = os.path.join(tmp, ".autopilot")
    ch = os.path.join(ap, "checks")
    os.makedirs(ch, exist_ok=True)
    os.makedirs(os.path.join(ap, "rounds"), exist_ok=True)
    write(os.path.join(ch, "run.sh"), run_sh_body)
    os.chmod(os.path.join(ch, "run.sh"), 0o755)
    write(os.path.join(ap, "GOAL.md"), "# GOAL\n\n（无 FLEX_RULES：等价基线）\n")
    write_json(os.path.join(ap, "tasks.json"), {
        "epoch": 0,
        "tasks": [{"id": "T-01", "title": "t", "role": "Builder", "status": "pending",
                   "deps": [], "write_set": ["src/a.js"], "acceptance": ["A1"],
                   "card": ".autopilot/tasks/T-01.md"}],
    })
    if extra:
        for rel, body in extra.items():
            write(os.path.join(tmp, rel), body)
    return ap, ch


def result_lines(text):
    """从日志里抽 (id, status) 序列（忽略时长/备注类噪声，只比 id 与 PASS/FAIL/SKIP）。"""
    import re
    out = []
    for line in text.splitlines():
        m = re.match(r"^\s*RESULT\s+(\S+)\s+(PASS|FAIL|SKIP)\b", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out
