#!/bin/bash

set -eu

# schedule_scripts.py は試験スクリプトを "../sh/..." の相対パスで参照するため、
# test_program ディレクトリへ移動してから実行する
cd "$(dirname "$(readlink -f "$0")")/test_program"

python3 schedule_scripts.py "$@"
