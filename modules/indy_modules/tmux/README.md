# tmux
## 設定手順
1. 以下のコマンドを実行して、ホームディレクトリ配下にtmuxの設定ファイルへのシンボリックリンクを作成する。
   ```
   $ ln -s $GUARDIAN_ROBOT_PATH/modules/indy_modules/tmux/.tmux.conf ~/
   ```

2. tmuxが起動している状態で以下のコマンドを実行して、設定を反映させる。
   ```
   tmux source ~/.tmux.conf
   ```

※ `.tmux.conf`のプラグイン設定（`@plugin`、`run '~/.tmux/plugins/tpm/tpm'`の行）はコメントアウトされているため、通常はtpm（tmux plugin manager）のインストールは不要です。  
プラグインを有効にする場合のみ、該当行のコメントを外したうえで、以下のコマンドでtpmをインストールしてください。
```
git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
```
