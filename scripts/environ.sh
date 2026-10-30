#!/bin/sh
# environ 跨平台包装脚本：定位 python3 后原样转发参数，退出码透传。
# 用法见 environ.py 顶部文档。POSIX sh，不依赖 bash；不写死任何绝对路径。
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info[0]>=3 else 1)' >/dev/null 2>&1; then
      PY=$c
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo "ENV BAD-ENV 2 - 需要 python3（本 skill 零第三方依赖，仅需标准库）"
  exit 2
fi

exec "$PY" "$HERE/environ.py" "$@"
