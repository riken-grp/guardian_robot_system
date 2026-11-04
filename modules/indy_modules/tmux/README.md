# tmux
## 設定手順
1. .tmux.confファイルをホームディレクトリに配置する。
   ```
   cp ※.tmux.confのパス※ ~/
   ```

2. tpm（tmux plugin manager）をインストールする。
   ```
   git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
   ```

3. tmuxが起動している状態で以下のコマンドを実行して、設定を反映させる。
   ```
   tmux source ~/.tmux.conf
   ```