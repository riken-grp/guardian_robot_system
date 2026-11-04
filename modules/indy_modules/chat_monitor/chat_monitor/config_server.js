module.exports = {

    // mongoDBの接続設定（起動時引数 --mongo_uri, --mongo_port で上書き可能）
    mongo_uri: 'example.local',
    mongo_port: 9000,
    database_name: 'subtitle_indy',
    collection_name: 'Actions',

    // 表示用のポート番号（起動時引数 --display_port で上書き可能）
    display_port: 3000,

    // 自動翻訳（DeepL）のON/OFF
    // true: DeepLで翻訳した英文を表示 / false: 日本語文をそのまま表示
    enableTranslation: false,

    // 翻訳失敗時のエラー文
    translation_failed_text: 'Oops! Translation FAILED! Guess I should study more Engish...',

    // 左側の話者名
    leftSideSpeaker: 'asr',

    // データを保持する最大のバブル数
    maxBubbles: 100
};