// 単一ノードレプリカセットの初期化・メンバー名修正・状態確認を行う healthcheck スクリプト．
// 環境変数 RS_HOST（例：robot-server.local:9110）を唯一のメンバー名とする．
// docker-compose.yml の healthcheck から 10 秒ごとに実行される．例外で終われば unhealthy 扱い．
const host = process.env.RS_HOST;
if (!host) throw new Error('RS_HOST is not set');

let cur = null;
try {
  cur = db.adminCommand({ replSetGetConfig: 1 });
} catch (e) {
  // mongosh はコマンドが失敗すると ok:0 を返さず例外を投げる．
  // 未初期化（NotYetInitialized, code 94）のときだけ初期化し，それ以外はそのまま失敗とする．
  if (e.codeName !== 'NotYetInitialized' && e.code !== 94) throw e;
}

if (cur === null) {
  rs.initiate({ _id: 'rs0', members: [{ _id: 0, host: host }] });
} else if (cur.config.members[0].host !== host) {
  // 別サーバから持ってきたデータなど，旧設定のメンバー名が残っていれば強制的に書き換える
  const c = cur.config;
  c.members[0].host = host;
  c.version += 1;
  db.adminCommand({ replSetReconfig: c, force: true });
}

// 初期化・書き換え直後はまだ PRIMARY でないことがある．次回の healthcheck で healthy になる．
const st = rs.status();
if (st.myState !== 1) throw new Error('not PRIMARY yet: ' + st.myState);
