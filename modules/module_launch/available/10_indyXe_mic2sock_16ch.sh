#!/bin/bash

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

MIC2SOCK_DIR=$GUARDIAN_ROBOT_PATH/modules/indy_modules/mic2sock/mic2sock_shim.rs

if echo "$tmux_sessions" | grep -q "^$filename$"; then
  echo "$filename" already exists
else
  echo "$filename" is launching...
  # target/release/mic2sock が無ければ先にビルドする（初回のみ）。
  # mic2sock はワークスペースの default-members 外なので -p 指定が必須。
  # rustup 環境では tmux 内の非ログインシェルに cargo の PATH が通らないため ~/.cargo/env を読む。
  tmux new -d -s $filename bash -c "tmux pipe-pane -o 'cat >> ~/tmux_${filename}.log';
                                    [ -f ~/.cargo/env ] && . ~/.cargo/env;
                                    cd $MIC2SOCK_DIR &&
                                    { [ -x target/release/mic2sock ] || cargo build -p mic2sock --release; } &&
                                    target/release/mic2sock"
  # sleep 5
  echo "$filename" started
fi
