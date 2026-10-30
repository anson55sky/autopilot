#!/usr/bin/env python3
"""M6 全包扫描：draft 目录内不得出现绝对路径常量或具体 App 目录名。

被禁字面（源码里不许出现的路径常量前缀）：
  - 家目录绝对前缀 = "/U" 拼接 "sers/"（mac 用户目录）
  - 家目录波浪前缀 = "~" 拼接 "/"（shell 家展开）
  - Windows 盘符常量 = 形如 `<字母>:\\` 的路径字面
  - macOS App 目录名 = `.app` 拼接 `/`（把具体 App 目录写进源码）
本文件的判定串本身必须由拼接构造，不然 M6 扫到自己。

allowlist（视为"文档/夹具里的必要占位示例"）：
  - `.md` 文件（规格文档必须能展示"什么不许写"）
  - `*.selftest.sh`（黑名单命令的假想参数）
  - 行内含标记 = "M6" 拼接 "-allow"

反例检测（先证明探测器有效）：
  写一个临时 .py 文件，逐行含上述禁串 → 必须每行都命中。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

# 用拼接构造，避免本文件自身被扫到时命中
USERS_PREFIX = "/U" + "sers/"
HOME_TILDE = "~" + "/"
APP_BUNDLE = ".app" + "/"
ALLOW_MARKER = "M6" + "-allow"

BAD_RULES = [
    (USERS_PREFIX, "家目录绝对前缀"),
    (HOME_TILDE, "家目录波浪前缀"),
    (APP_BUNDLE, "macOS App 目录名"),
]
# Windows 盘符：字符串字面里出现 `X:\` 或 `X:/`
WIN_DRIVE_RE = re.compile(r"""(['"][A-Za-z]:[\\/])""")

SCAN_SUFFIXES = (".py", ".sh", ".json", ".yaml", ".yml", ".md")
# 排除扫描：VCS、临时
SKIP_DIRNAMES = {".git", "__pycache__", ".DS_Store", "node_modules"}
# 排除规则里的"必要占位示例"文件模式
DOC_SUFFIXES = (".md",)
SELFTEST_MARK = ".selftest.sh"


def is_allowlisted(path):
    base = os.path.basename(path)
    if base.endswith(DOC_SUFFIXES):
        return True
    if base.endswith(SELFTEST_MARK):
        return True
    return False


def scan_file(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                if ALLOW_MARKER in line:
                    continue
                for token, label in BAD_RULES:
                    if token in line:
                        yield (path, n, label, token, line.rstrip())
                m = WIN_DRIVE_RE.search(line)
                if m:
                    yield (path, n, "Windows 盘符常量", m.group(1), line.rstrip())
    except OSError:
        return


def iter_sources(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRNAMES]
        for fn in filenames:
            if not fn.endswith(SCAN_SUFFIXES):
                continue
            yield os.path.join(dirpath, fn)


CRLF_SUFFIXES = (".sh", ".py", ".json", ".md", ".txt")


def crlf_violations(root):
    """行尾审计（P10）：文本文件里出现 \\r 就判失败。

    分发包里带 CRLF 的脚本会让 check.sh 的 RESULT 正则与 shell 执行双双出错，
    所以这不是"风格问题"，是打包门禁。
    """
    bad = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRNAMES]
        for fn in sorted(fns):
            if not fn.endswith(CRLF_SUFFIXES):
                continue
            p = os.path.join(dp, fn)
            try:
                data = open(p, "rb").read()
            except OSError:
                continue
            if b"\r\n" in data:
                bad.append(os.path.relpath(p, root))
    return bad


def violations_in(path):
    """完整管道：allowlist 闸门 + 逐行扫描。allowlisted 文件一律不计违规。"""
    if is_allowlisted(path):
        return []
    return list(scan_file(path))


def detector_selfcheck():
    """构造含禁串的合成文件，验证探测器命中 + allowlist 生效；返回 (ok, msg)。"""
    tmp = C.new_tmp("m6-probe-")
    try:
        p = os.path.join(tmp, "bad_example.py")
        # 每行一个禁串
        C.write(p,
                "a = '" + USERS_PREFIX + "alice/x'\n"
                + "b = '" + HOME_TILDE + ".ssh/id'\n"
                + "c = '/Applications/Foo" + APP_BUNDLE + "Contents'\n"
                + "d = 'C:" + chr(92) + "proj'\n")
        hits = {label for (_p, _n, label, _t, _l) in violations_in(p)}
        want = {"家目录绝对前缀", "家目录波浪前缀", "macOS App 目录名", "Windows 盘符常量"}
        missing = want - hits
        if missing:
            return False, f"探测器漏检: {sorted(missing)}"
        # allowlist 生效性：同样禁串写进 .selftest.sh 与 .md，必须不计违规
        for suffix in (SELFTEST_MARK, ".md"):
            p2 = os.path.join(tmp, "ok" + suffix)
            C.write(p2, "echo '" + USERS_PREFIX + "x'\n")
            if violations_in(p2):
                return False, f"allowlist 未生效：{suffix} 文件仍被计违规"
        return True, "探测器命中禁串 + allowlist 生效"
    finally:
        C.cleanup(tmp)


def main():
    root = C.ROOT
    ok_probe, probe_msg = detector_selfcheck()
    if not ok_probe:
        return C.emit(6, "FAIL", f"探测器自证失败 :: {probe_msg}")

    violations = []
    scanned_files = 0
    for path in iter_sources(root):
        scanned_files += 1
        for hit in violations_in(path):
            # 相对化路径便于报告（禁绝对路径铁律：报告里也不能出现绝对路径）
            rel = os.path.relpath(hit[0], root)
            violations.append((rel, hit[1], hit[2], hit[3], hit[4]))

    crlf = crlf_violations(root)
    if crlf:
        return C.emit(6, "FAIL",
                      f"扫 {scanned_files} 文件，{len(crlf)} 个文本文件含 CRLF（打包门禁）:: "
                      + ", ".join(crlf[:6]))

    if violations:
        head = violations[0]
        return C.emit(6, "FAIL",
                      f"扫 {scanned_files} 文件，仍有 {len(violations)} 处禁串 :: "
                      f"{head[0]}:{head[1]} {head[2]} {head[4][:80]}")
    return C.emit(6, "PASS",
                  f"扫 {scanned_files} 文件，无 /U-sers / ~-slash / .app / 盘符 常量"
                  f"（allowlist：*.md 与 *.selftest.sh 承担必要占位示例）")


if __name__ == "__main__":
    sys.exit(main())
