#!/usr/bin/env bash
# 可选：把长跑进展推到你自己的 webhook（飞书 / Slack）。默认不发，必须显式配置。
# 用法: AUTOPILOT_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxx" notify.sh "文本"
#      echo "文本" | notify.sh
set -uo pipefail

HOOK="${AUTOPILOT_WEBHOOK:-}"
if [ -z "$HOOK" ]; then
  echo "未配置 AUTOPILOT_WEBHOOK，跳过通知（这是默认行为）"
  exit 0
fi

TEXT="${1:-}"
if [ -z "$TEXT" ] && [ ! -t 0 ]; then
  TEXT="$(cat)"
fi
if [ -z "$TEXT" ]; then
  echo "用法: notify.sh \"文本\" 或管道输入"
  exit 2
fi

TMP_JSON="$(mktemp -t autopilot-notify)"
TMP_OUT="$(mktemp -t autopilot-notify-out)"
trap 'rm -f "$TMP_JSON" "$TMP_OUT"' EXIT

HOOK="$HOOK" TEXT="$TEXT" python3 - "$TMP_JSON" <<'PY'
import json, os, sys
hook, text = os.environ["HOOK"], os.environ["TEXT"]
payload = {"text": text} if "hooks.slack.com" in hook else {
    "msg_type": "text", "content": {"text": text}}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False)
PY

code="$(curl -sS -o "$TMP_OUT" -w '%{http_code}' \
  -H 'Content-Type: application/json' --max-time 15 \
  --data-binary "@$TMP_JSON" "$HOOK" 2>/dev/null)" || code="000"
echo "通知已发送（HTTP $code）"
[ "$code" = "200" ]
