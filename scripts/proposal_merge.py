#!/usr/bin/env python3
"""契约变更提案的合并器（B1/B2 + 升级清单第 5 项）。

设计意图见 00-DECISIONS.md §3 B1/B2 与 specs/host-adapter.md §4/§5。
把"已批准的契约变更提案"落到主轨道的动作序列：
  validate  校验提案结构与人工批准
  merge     归档旧基线 → 应用提案 → 重新冻结 MANIFEST → 追一条 changelog → epoch+1

零第三方依赖：POSIX sh 包装 + Python stdlib。所有路径必须项目相对，
禁止出现任何绝对路径与 ~ 前缀（M6 会扫这个文件本身）。

提案文件（Markdown，形如 `key: value` 的行会被解析）必填字段：
  proposal_id:   CP-01
  base_epoch:    0
  change_type:   add | tighten | relax | remove
  affected_a:    A7, A9
  evidence:      sandbox/proposals/CP-01-evidence.log     # 必须实际存在
  approved_by:   supervisor
  approved_at:   <UTC ISO8601>

方向不对称（关键安全规则）：
  add / tighten  → 有 approved_by/approved_at 即可自动合并
  relax / remove → affected_a 里每一条都必须带独立人工确认标记：
                     confirm-A7: yes
                     confirm-A9: yes
                   缺任一条 → 拒绝合并（防"一句话批准打包放宽"）

退出码：
  0  OK
  30 校验失败（结构 / 字段非法 / 证据文件缺失）
  31 缺人工批准记录，或 relax/remove 缺逐条 confirm-A#: yes
  32 epoch 不匹配（当前 epoch != 提案 base_epoch）
  33 归档写入失败（baseline/epoch-N/ 已存在 或 IO 出错）
  2  用法错误

只读约束：
  已归档的 baseline/epoch-*/ 与 rounds/r-*.json 视为历史，本脚本绝不覆写。
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sys

# 允许把同目录的 environ.py 作为模块引入（不写绝对路径，全靠 __file__）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import environ  # noqa: E402
except Exception as e:  # pragma: no cover
    print(f"MERGE INTERNAL 2 无法加载 environ.py: {e}", file=sys.stderr)
    raise SystemExit(2)

E_OK, E_VALIDATE, E_APPROVAL, E_EPOCH, E_ARCHIVE, E_USAGE = 0, 30, 31, 32, 33, 2

REQUIRED_KEYS = ("proposal_id", "base_epoch", "change_type",
                 "affected_a", "evidence")
APPROVAL_KEYS = ("approved_by", "approved_at")
ALL_KEYS = REQUIRED_KEYS + APPROVAL_KEYS
CHANGE_TYPES = ("add", "tighten", "relax", "remove")
ASYMMETRIC_TYPES = ("relax", "remove")  # 需逐条 confirm-A#: yes

KEY_RE = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*:\s*(.+?)\s*$")
A_RE = re.compile(r"^A\d+$")
ID_RE = re.compile(r"^CP-[A-Za-z0-9_-]{1,32}$")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def ap_paths(repo):
    ap = os.path.join(repo, ".autopilot")
    return {
        "ap": ap,
        "goal": os.path.join(ap, "GOAL.md"),
        "tasks": os.path.join(ap, "tasks.json"),
        "checks": os.path.join(ap, "checks"),
        "manifest": os.path.join(ap, "checks", "MANIFEST.sha256"),
        "baseline_root": os.path.join(ap, "baseline"),
        "rounds": os.path.join(ap, "rounds"),
        "changelog": os.path.join(ap, "contract-changelog.md"),
    }


def read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)


def parse_proposal(path):
    """把 Markdown 里所有 `key: value` 抽出。后到的同键覆盖前一次。"""
    fields = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            m = KEY_RE.match(raw.rstrip("\n"))
            if not m:
                continue
            k, v = m.group(1), m.group(2).strip()
            fields[k] = v
    return fields


def is_relpath(p):
    return bool(p) and not p.startswith("/") and not p.startswith("~") \
        and not re.match(r"^[A-Za-z]:[\\/]", p) and ".." not in p.split("/") \
        and "$" not in p and "{" not in p


def validate_fields(fields, repo, quiet=False):
    """返回 (code, message)。code=0 通过。"""
    def say(msg):
        if not quiet:
            print(f"MERGE VALIDATE {code_holder[0]} {msg}")

    missing = [k for k in REQUIRED_KEYS if k not in fields or not str(fields.get(k)).strip()]
    if missing:
        code_holder[0] = E_VALIDATE
        say("缺必填字段: " + ", ".join(missing))
        return E_VALIDATE, "缺必填字段: " + ", ".join(missing)

    pid = fields["proposal_id"].strip()
    if not ID_RE.match(pid):
        code_holder[0] = E_VALIDATE
        say(f"proposal_id 不合 ^CP-[\\w-]+$: {pid!r}")
        return E_VALIDATE, f"proposal_id 非法: {pid!r}"

    try:
        base_epoch = int(fields["base_epoch"])
    except ValueError:
        code_holder[0] = E_VALIDATE
        say(f"base_epoch 必须是整数: {fields['base_epoch']!r}")
        return E_VALIDATE, "base_epoch 非整数"
    if base_epoch < 0:
        code_holder[0] = E_VALIDATE
        say("base_epoch 不得为负")
        return E_VALIDATE, "base_epoch 为负"

    ct = fields["change_type"].strip().lower()
    if ct not in CHANGE_TYPES:
        code_holder[0] = E_VALIDATE
        say(f"change_type 必须是 {CHANGE_TYPES}，得到 {ct!r}")
        return E_VALIDATE, f"change_type 非法: {ct!r}"

    raw_a = fields["affected_a"].strip()
    affected = [x.strip() for x in raw_a.split(",") if x.strip()]
    if not affected:
        code_holder[0] = E_VALIDATE
        say("affected_a 至少一个 A#")
        return E_VALIDATE, "affected_a 为空"
    bad = [a for a in affected if not A_RE.match(a)]
    if bad:
        code_holder[0] = E_VALIDATE
        say(f"affected_a 含非法项: {bad}")
        return E_VALIDATE, f"affected_a 含非法项: {bad}"

    ev = fields["evidence"].strip()
    if not is_relpath(ev):
        code_holder[0] = E_VALIDATE
        say(f"evidence 必须是项目相对路径: {ev!r}")
        return E_VALIDATE, f"evidence 非相对路径: {ev!r}"
    ev_abs = os.path.join(repo, ev)
    if not os.path.isfile(ev_abs):
        code_holder[0] = E_VALIDATE
        say(f"evidence 指向的文件不存在: {ev}")
        return E_VALIDATE, f"evidence 文件不存在: {ev}"

    # 人工批准记录（任何类型都必须有；缺失 → 31，不是结构错 30）
    if not str(fields.get("approved_by", "")).strip() \
            or not str(fields.get("approved_at", "")).strip():
        code_holder[0] = E_APPROVAL
        say("缺人工批准记录 approved_by/approved_at")
        return E_APPROVAL, "缺人工批准记录"

    # 方向不对称：relax/remove 需逐条 confirm-A#: yes
    if ct in ASYMMETRIC_TYPES:
        missing_confirm = []
        for a in affected:
            key = f"confirm-{a}"
            v = str(fields.get(key, "")).strip().lower()
            if v not in ("yes", "true", "1"):
                missing_confirm.append(key)
        if missing_confirm:
            code_holder[0] = E_APPROVAL
            say(f"{ct} 缺逐条确认: {', '.join(missing_confirm)}")
            return E_APPROVAL, f"{ct} 缺逐条确认: {', '.join(missing_confirm)}"

    code_holder[0] = E_OK
    say(f"通过 id={pid} type={ct} epoch={base_epoch} affected={','.join(affected)}")
    return E_OK, {
        "proposal_id": pid, "base_epoch": base_epoch, "change_type": ct,
        "affected_a": affected, "evidence": ev,
        "approved_by": fields["approved_by"].strip(),
        "approved_at": fields["approved_at"].strip(),
    }


# 用一个可变列表给 say() 用；比 closure 简单，也避免把 code 到处塞参数
code_holder = [E_OK]


def load_proposal(path, repo, quiet=False):
    if not os.path.isfile(path):
        code_holder[0] = E_VALIDATE
        if not quiet:
            print(f"MERGE VALIDATE {E_VALIDATE} 提案文件不存在: {path}")
        return E_VALIDATE, None
    try:
        fields = parse_proposal(path)
    except OSError as e:
        code_holder[0] = E_VALIDATE
        if not quiet:
            print(f"MERGE VALIDATE {E_VALIDATE} 读取提案失败: {e}")
        return E_VALIDATE, None
    return validate_fields(fields, repo, quiet=quiet)


def current_epoch(repo):
    doc = read_json(ap_paths(repo)["tasks"], {}) or {}
    if "epoch" in doc and isinstance(doc["epoch"], int):
        return doc["epoch"]
    return 0


def cmd_validate(args):
    repo = args.repo
    if not os.path.isdir(repo):
        print(f"MERGE USAGE {E_USAGE} 仓库不存在: {repo}")
        return E_USAGE
    code, payload = load_proposal(args.proposal, repo)
    if code != E_OK:
        return code
    # 校验通过时也做一次 epoch 匹配检查，方便 CI 里先筛
    if args.check_epoch:
        cur = current_epoch(repo)
        if cur != payload["base_epoch"]:
            print(f"MERGE EPOCH {E_EPOCH} 当前 epoch={cur} 提案 base_epoch={payload['base_epoch']}")
            return E_EPOCH
    return E_OK


def archive_baseline(repo, old_epoch, proposal_src):
    P = ap_paths(repo)
    tgt = os.path.join(P["baseline_root"], f"epoch-{old_epoch}")
    if os.path.exists(tgt):
        # 历史不可覆写
        print(f"MERGE ARCHIVE {E_ARCHIVE} 归档目录已存在，拒绝覆写: "
              f"{os.path.relpath(tgt, repo)}")
        return E_ARCHIVE, None
    try:
        os.makedirs(tgt, exist_ok=False)
        # GOAL.md
        if os.path.isfile(P["goal"]):
            shutil.copy2(P["goal"], os.path.join(tgt, "GOAL.md"))
        # tasks.json（供还原 epoch-N 时的完整契约）
        if os.path.isfile(P["tasks"]):
            shutil.copy2(P["tasks"], os.path.join(tgt, "tasks.json"))
        # checks/ 整目录（只含判定脚本与 MANIFEST）
        if os.path.isdir(P["checks"]):
            shutil.copytree(P["checks"], os.path.join(tgt, "checks"), symlinks=False)
        else:
            print(f"MERGE ARCHIVE {E_ARCHIVE} 缺 checks/，无法归档")
            shutil.rmtree(tgt, ignore_errors=True)
            return E_ARCHIVE, None
        # 探测产物住在 .autopilot/ 顶层，归档时单独带一份快照
        env_src = os.path.join(repo, ".autopilot", "environment.json")
        if os.path.isfile(env_src):
            shutil.copy2(env_src, os.path.join(tgt, "environment.json"))
        # 单独再存一份 MANIFEST.sha256 到顶层，方便肉眼 diff（不删原 checks/ 里的）
        src_manifest = os.path.join(P["checks"], "MANIFEST.sha256")
        if os.path.isfile(src_manifest):
            shutil.copy2(src_manifest, os.path.join(tgt, "MANIFEST.sha256"))
        # 提案源文件也一并归档，作为该 epoch 的 provenance
        if os.path.isfile(proposal_src):
            shutil.copy2(proposal_src, os.path.join(tgt, "PROPOSAL.md"))
    except (OSError, shutil.Error) as e:
        shutil.rmtree(tgt, ignore_errors=True)
        print(f"MERGE ARCHIVE {E_ARCHIVE} 归档写入失败: {e}")
        return E_ARCHIVE, None
    return E_OK, tgt


def apply_proposal(repo, payload, old_epoch):
    P = ap_paths(repo)
    doc = read_json(P["tasks"], {}) or {}
    doc["epoch"] = old_epoch + 1
    contract = doc.setdefault("contract", {})
    if isinstance(contract, dict):
        contract["last_proposal"] = {
            "id": payload["proposal_id"],
            "type": payload["change_type"],
            "affected_a": payload["affected_a"],
            "approved_by": payload["approved_by"],
            "approved_at": payload["approved_at"],
            "merged_at": utc_now(),
        }
    try:
        write_json(P["tasks"], doc)
    except OSError as e:
        print(f"MERGE ARCHIVE {E_ARCHIVE} 写 tasks.json 失败: {e}")
        return E_ARCHIVE
    sync_goal_epoch_line(repo, old_epoch + 1)
    return E_OK


# GOAL.md 抬头那行「契约 epoch：N」是给人和验证者读的真源声明。
# ContraRunner 实测踩坑：merge 只加 tasks.json 的 epoch，声明行留在旧值，两处差 1，
# 于是"跨 epoch 的历史绿不并入当轮结论"这条规则失去可核对的锚点。合并动作必须把它一起推进。
def sync_goal_epoch_line(repo, new_epoch):
    goal = os.path.join(ap_paths(repo)["ap"], "GOAL.md")
    try:
        with open(goal, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return
    pat = re.compile(r"^(\s*-\s*契约 epoch[：:]\s*)(\d+)(.*)$", re.M)
    if not pat.search(text):
        print("MERGE WARN GOAL.md 没有「契约 epoch：N」声明行，未同步（下次 validate 也查不出漂移）")
        return
    new = pat.sub(lambda m: "%s%d%s" % (m.group(1), new_epoch, m.group(3)), text, count=1)
    if new != text:
        try:
            with open(goal, "w", encoding="utf-8") as fh:
                fh.write(new)
        except OSError as e:
            print(f"MERGE WARN 同步 GOAL epoch 声明行失败: {e}")


def refreeze_manifest(repo):
    P = ap_paths(repo)
    try:
        path, lines, impl = environ.do_freeze(repo, checks_rel=".autopilot/checks")
    except Exception as e:
        print(f"MERGE ARCHIVE {E_ARCHIVE} 重新冻结 MANIFEST 失败: {e}")
        return E_ARCHIVE
    print(f"MERGE FREEZE 0 {os.path.relpath(path, repo)} impl={impl} files={len(lines)}")
    return E_OK


def append_changelog(repo, payload, old_epoch):
    P = ap_paths(repo)
    header_needed = not os.path.isfile(P["changelog"])
    try:
        with open(P["changelog"], "a", encoding="utf-8") as f:
            if header_needed:
                f.write("# Contract changelog\n\n")
                f.write("| from | to | type | proposal | affected | approved_by | approved_at | ts |\n")
                f.write("| --- | --- | --- | --- | --- | --- | --- | --- |\n")
            row = (f"| {old_epoch} | {old_epoch + 1} | {payload['change_type']} | "
                   f"{payload['proposal_id']} | {','.join(payload['affected_a'])} | "
                   f"{payload['approved_by']} | {payload['approved_at']} | {utc_now()} |\n")
            f.write(row)
    except OSError as e:
        print(f"MERGE ARCHIVE {E_ARCHIVE} changelog 追加失败: {e}")
        return E_ARCHIVE
    return E_OK


def cmd_merge(args):
    repo = args.repo
    if not os.path.isdir(repo):
        print(f"MERGE USAGE {E_USAGE} 仓库不存在: {repo}")
        return E_USAGE
    code, payload = load_proposal(args.proposal, repo)
    if code != E_OK:
        return code
    cur = current_epoch(repo)
    if cur != payload["base_epoch"]:
        print(f"MERGE EPOCH {E_EPOCH} 当前 epoch={cur} != 提案 base_epoch={payload['base_epoch']}"
              "（拒绝跨 epoch 合并）")
        return E_EPOCH
    # 归档旧基线
    rc, tgt = archive_baseline(repo, payload["base_epoch"], args.proposal)
    if rc != E_OK:
        return rc
    # 应用提案（写 tasks.json 记录 + epoch+1）
    rc = apply_proposal(repo, payload, payload["base_epoch"])
    if rc != E_OK:
        return rc
    # 重新冻结 MANIFEST（判定文件本身没动 → 逐字节不变；这正是 M4 的锚点）
    rc = refreeze_manifest(repo)
    if rc != E_OK:
        return rc
    # changelog 追加一行
    rc = append_changelog(repo, payload, payload["base_epoch"])
    if rc != E_OK:
        return rc
    print(f"MERGE OK 0 已合并 {payload['proposal_id']} "
          f"type={payload['change_type']} epoch {payload['base_epoch']}→{payload['base_epoch']+1} "
          f"归档 baseline/epoch-{payload['base_epoch']}/")
    return E_OK


def main(argv=None):
    ap = argparse.ArgumentParser(prog="proposal-merge.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    v = sp.add_parser("validate")
    v.add_argument("--repo", required=True)
    v.add_argument("--proposal", required=True)
    v.add_argument("--check-epoch", action="store_true")
    v.set_defaults(fn=cmd_validate)

    m = sp.add_parser("merge")
    m.add_argument("--repo", required=True)
    m.add_argument("--proposal", required=True)
    m.set_defaults(fn=cmd_merge)

    args = ap.parse_args(argv)
    if args.cmd not in ("validate", "merge"):
        print(f"MERGE USAGE {E_USAGE} 未知子命令 {args.cmd}", file=sys.stderr)
        return E_USAGE
    if not os.path.isabs(args.repo) and not os.path.isdir(args.repo):
        # 相对 --repo 但目录不存在
        pass
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
