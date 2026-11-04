#!/bin/bash
# Slack Webhook にメッセージを送信するスクリプト
#
# Usage: ./send_slack_msg.sh <メッセージ>
#   例) ./send_slack_msg.sh "レスキューモードが開始されました"
#
# 環境変数 SLACK_WEBHOOK_URL でWebhook URLを指定する
# 未設定（空）の場合は通知を行わず、正常終了する

SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"

if [ -z "$1" ]; then
    echo "Usage: $0 <message>"
    exit 1
fi

if [ -z "${SLACK_WEBHOOK_URL}" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] SLACK_WEBHOOK_URL is not set. Skipping Slack notification: $1"
    exit 0
fi

HOSTNAME="$(hostname)"
CURRENT_TIME="$(date '+%Y-%m-%d %H:%M:%S')"
MESSAGE="${CURRENT_TIME}: ${HOSTNAME}: $1"

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "${SLACK_WEBHOOK_URL}" \
    -H "Content-Type: application/json" \
    -d "{\"text\": \"${MESSAGE}\"}")

if [ "${HTTP_STATUS}" = "200" ]; then
    echo "[${CURRENT_TIME}] Slack message sent: $1"
else
    echo "[${CURRENT_TIME}] Error: Failed to send Slack message (HTTP ${HTTP_STATUS})"
    exit 1
fi
