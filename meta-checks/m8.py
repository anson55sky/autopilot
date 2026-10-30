#!/usr/bin/env python3
"""M8 黑名单预检拦下不可逆命令（复用 flex-gate deny-list，不依赖宿主回调）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

BLOCKED = [
    "git push origin main",
    "git -c foo=bar push --force",
    "sudo rm -rf " + os.sep + "tmp" + os.sep + "whatever",  # 运行时拼出来的绝对目标，源码不含禁串
    "pip install requests",
    "npm install -g left-pad",
    "curl -X POST https://example.invalid/api",
    "cat " + chr(126) + os.sep + ".ssh/id_rsa",             # 波浪号家目录凭据（运行时拼出，源码不留禁串）
]
ALLOWED = [
    "ls -la",
    "node --version",
    "python3 -m http.server",
]


def main():
    tmp = C.new_tmp("m8-")
    try:
        blocked_fail = []
        for cmd in BLOCKED:
            rc, out, err = C.flex("deny-list", "--repo", tmp, "--check", cmd)
            if rc != 24:
                blocked_fail.append((cmd[:40], rc))
        allowed_fail = []
        for cmd in ALLOWED:
            rc, out, err = C.flex("deny-list", "--repo", tmp, "--check", cmd)
            if rc != 0:
                allowed_fail.append((cmd[:40], rc))
        if blocked_fail:
            return C.emit(8, "FAIL",
                          f"未拦下 {len(blocked_fail)} 条不可逆命令 :: {blocked_fail}")
        if allowed_fail:
            return C.emit(8, "FAIL",
                          f"误伤 {len(allowed_fail)} 条普通命令 :: {allowed_fail}")
        # git push 是首要红线，单独再点一遍它的审计落盘
        C.flex("deny-list", "--repo", tmp, "--check", "git push")
        return C.emit(8, "PASS",
                      f"{len(BLOCKED)} 条不可逆命令全部退出 24、{len(ALLOWED)} 条普通命令放行")
    finally:
        C.cleanup(tmp)


if __name__ == "__main__":
    sys.exit(main())
