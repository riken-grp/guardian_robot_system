#!/bin/bash
# MongoDB（設定DB とロボットDB）を対話で用意する（setup_mongo.py を rism2 の uv 環境で動かす）
#   ./setup_mongo.sh                 対話で聞く
#   ./setup_mongo.sh --help          オプション
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
RISM2=$(cd "$HERE/../../modules/scenario_manager/rism2" && pwd)
if ! command -v uv >/dev/null; then
  echo "uv がありません。先に入れてください（docs/手順書/サーバマシン構築.md）: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi
exec uv run --project "$RISM2" python "$HERE/setup_mongo.py" "$@"
