window.clientConfig = {

    // 次の発言取得を試みるまでのインターバル（ミリ秒）
    fetchInterval: 50,    // 発言や翻訳がスキップされることがあるときは、この値を小さくする。
    
    // 最大表示発言数
    messageLimit: 30,

    // 発言が表示されてから翻訳表示までの待ち時間（ミリ秒）
    translationTimeout: 2000,

    // 翻訳表示の各文字切替えまでのインターバル(ミリ秒)
    letterAnimationInterval: 100

};
