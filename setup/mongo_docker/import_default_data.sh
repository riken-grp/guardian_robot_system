#!/bin/bash
# 標準データセット（default_data/*.json）を、この compose で起動した MongoDB に投入する．
#
# 使い方:
#   ./import_default_data.sh [オプション] <ROBOT_NAME> [MONGO_HOST]
#
#   ROBOT_NAME   ロボット名（ロボット側 indy.env の ROBOT_NAME と同じ値）
#   MONGO_HOST   設定に書き込む MongoDB のホスト名．省略時は env ファイルの MONGO_PUBLIC_HOST
#
# オプション:
#   -p <名前>            docker compose のプロジェクト名（複数台分を起動している場合）
#   --env-file <ファイル>  env ファイル（既定: mongo.env）
#   --overwrite          同じ _id のドキュメントがあれば標準データで上書きする（既定は上書きしない）
#
# 置き換えるプレースホルダ: __ROBOT_NAME__ / __MONGO_HOST__ / __MONGO_PORT__
# それ以外（__LLM_HOST__ など）は投入後に一覧を表示するので，mongo-express などで書き換える．
set -euo pipefail

cd "$(dirname "$0")"

project_args=()
env_file=mongo.env
mode=insert
while [ $# -gt 0 ]; do
  case "$1" in
    -p) project_args=(-p "$2"); shift 2 ;;
    --env-file) env_file="$2"; shift 2 ;;
    --overwrite) mode=upsert; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    -*) echo "不明なオプション: $1" >&2; exit 1 ;;
    *) break ;;
  esac
done

if [ $# -lt 1 ]; then
  sed -n '2,17p' "$0" >&2
  exit 1
fi
[ -f "$env_file" ] || { echo "env ファイルがありません: $env_file" >&2; exit 1; }

env_value() { grep -E "^$1=" "$env_file" | tail -n 1 | cut -d= -f2- | sed -E 's/^"(.*)"$/\1/'; }

robot_name="$1"
mongo_host="${2:-$(env_value MONGO_PUBLIC_HOST)}"
mongo_port="$(env_value MONGO_PORT)"

if [ -z "$mongo_host" ] || [[ "$mongo_host" == *"<"* ]]; then
  echo "$env_file の MONGO_PUBLIC_HOST を設定してください" >&2
  exit 1
fi
[[ "$mongo_port" =~ ^[0-9]+$ ]] || { echo "MONGO_PORT が $env_file に数値で設定されていません" >&2; exit 1; }
for v in "$robot_name" "$mongo_host"; do
  [[ "$v" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "使えない文字が含まれています: $v" >&2; exit 1; }
done

compose=(docker compose "${project_args[@]}" --env-file "$env_file")

echo "投入先: ${project_args[*]:-（既定のプロジェクト）} / ROBOT_NAME=$robot_name / MONGO_HOST=$mongo_host / MONGO_PORT=$mongo_port / mode=$mode"

for f in default_data/*.json; do
  ns=$(basename "$f" .json)
  db=${ns%%.*}
  coll=${ns#*.}
  # mongoimport は _id の重複があっても終了コード 0 で終わるため，件数を出力から読み取る
  if ! out=$(sed -e "s|__ROBOT_NAME__|$robot_name|g" \
                 -e "s|__MONGO_HOST__|$mongo_host|g" \
                 -e "s|__MONGO_PORT__|$mongo_port|g" "$f" |
             "${compose[@]}" exec -T mongo \
               mongoimport --port "$mongo_port" -d "$db" -c "$coll" --jsonArray --mode="$mode" 2>&1); then
    echo "$out" >&2
    echo "$ns の投入に失敗しました" >&2
    exit 1
  fi
  ok=$(echo "$out" | grep -oE '[0-9]+ document\(s\) imported' | grep -oE '^[0-9]+' || echo 0)
  ng=$(echo "$out" | grep -oE '[0-9]+ document\(s\) failed' | grep -oE '^[0-9]+' || echo 0)
  if [ "$mode" = upsert ]; then
    printf '  %-42s 追加・更新 %s 件（内容が同じものは数えない）' "$ns" "$ok"
  else
    printf '  %-42s 投入 %s 件' "$ns" "$ok"
  fi
  [ "$ng" -gt 0 ] && printf ' / 既存のためスキップ %s 件' "$ng"
  echo
  skipped=$((${skipped:-0} + ng))
done

if [ "${skipped:-0}" -gt 0 ]; then
  echo "同じ _id のドキュメントが既にあるものは投入していません．標準データで上書きするときは --overwrite を付けてください．"
fi

remaining=$(grep -ohE '__[A-Z_]+__' default_data/*.json | sort -u | grep -vE '^__(ROBOT_NAME|MONGO_HOST|MONGO_PORT)__$' || true)
if [ -n "$remaining" ]; then
  echo
  echo "次のプレースホルダは置き換えていません．環境に合わせて mongo-express などで書き換えてください："
  for p in $remaining; do
    echo "  $p : $(grep -lF "$p" default_data/*.json | xargs -n1 basename | sed 's/\.json$//' | paste -sd' ')"
  done
fi
