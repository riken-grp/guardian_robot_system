#!/bin/bash
# WAVファイルをaplayで繰り返し再生するスクリプト
#
# Usage: ./01_play_audio_msg.sh [WAVファイル名またはパス]
#
#   引数なし         : tools/help_request.wav を再生 (デフォルト)
#   ファイル名のみ    : tools/<ファイル名> を再生
#                       例) ./01_play_audio_msg.sh alert.wav
#   相対・絶対パス    : そのパスのファイルを再生
#                       例) ./01_play_audio_msg.sh ../tools/help_request.wav
#                       例) ./01_play_audio_msg.sh /tmp/custom.wav

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_DIR="${SCRIPT_DIR}/../tools"
DEFAULT_WAV="help_request.wav"

ARG="${1:-${DEFAULT_WAV}}"

# 絶対パスまたは相対パス（/や./や../で始まる）ならそのまま使用、
# それ以外（ファイル名のみ）なら tools/ ディレクトリを補完
if [[ "${ARG}" = /* ]] || [[ "${ARG}" = ./* ]] || [[ "${ARG}" = ../* ]]; then
    # パスとして解釈
    if [[ "${ARG}" = /* ]]; then
        WAV_PATH="${ARG}"
    else
        WAV_PATH="${SCRIPT_DIR}/${ARG}"
    fi
else
    # ファイル名のみ → tools/ ディレクトリから探す
    WAV_PATH="${TOOLS_DIR}/${ARG}"
fi

if [ ! -f "${WAV_PATH}" ]; then
    echo "Error: WAV file not found: ${WAV_PATH}"
    exit 1
fi

INTERVAL=${PLAY_INTERVAL:-5}  # 再生間隔 [秒]（環境変数 PLAY_INTERVAL で上書き可能）

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Playing: ${WAV_PATH} (interval: ${INTERVAL}s, Press Ctrl+C to stop)"

while true; do
    aplay "${WAV_PATH}"
    sleep "${INTERVAL}"
done
