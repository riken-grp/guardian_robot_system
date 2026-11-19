#!/bin/bash
# robstride02_tool をビルドし、実行ファイルを tools/other_tools/ に置く
# （Ubuntu 22.04 / x86_64 で実行する。libstdc++ は静的リンクする）
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../../../.." && pwd)
OUT="$REPO/tools/other_tools/robstride02_tool"

g++ -std=c++17 -O2 -s -Wall -static-libstdc++ -static-libgcc \
    -o "$OUT" "$HERE/robstride02_tool.cpp"
echo "built: $OUT"
