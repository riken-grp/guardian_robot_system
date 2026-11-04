const { MongoClient } = require('mongodb');
const express = require('express');
const path = require('path');
const app = express();
// 設定のインポート
const config = require('../config_server');

// 起動時引数の取得（--name value または --name=value 形式）
function getArg(name, defaultValue) {
    const argv = process.argv.slice(2);
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === `--${name}` && i + 1 < argv.length) {
            return argv[i + 1];
        }
        if (argv[i].startsWith(`--${name}=`)) {
            return argv[i].slice(name.length + 3);
        }
    }
    return defaultValue;
}

// ポート番号（指定がなければ config_server.js の値を使用）
const port = Number(getArg('display_port', config.display_port));

// MongoDBの接続設定（指定がなければ config_server.js の値を使用）
const mongo_uri = getArg('mongo_uri', config.mongo_uri);
const mongo_port = Number(getArg('mongo_port', config.mongo_port));
const database_uri = `mongodb://${mongo_uri}:${mongo_port}`;
console.log("MongoDB URI: ", database_uri);
const database_name = config.database_name;
const collection_name = config.collection_name;

// MongoClientを作成
const client = new MongoClient(database_uri);

// MongoDBの取得データの初期化
let latestId = null;
let speaker = null;
let message = null;
let chatContents = {};

// 自動翻訳のON/OFF
const enableTranslation = config.enableTranslation;

// DeepLクライアントの初期化（自動翻訳ONの場合のみ）
let translator = null;
if (enableTranslation) {
    const authKey = process.env.DEEPL_API_KEY;
    const deepl = require('deepl-node');
    translator = new deepl.Translator(authKey);
}
console.log("Translation: ", enableTranslation ? "ON" : "OFF");

// DeepL翻訳API呼出関数
async function translateText(text) {
    try {
        console.log("Calling DeepL Translation API...");
        const result = await translator.translateText(text, null, 'en-US');
        return result.text;
    } catch (error) {
        console.error("DeepL Translation API ERROR!:", error);
        const TranslationFailedText = config.translation_failed_text;
        return TranslationFailedText;
    }
}

// 必要なデータを抽出する関数
async function getChatData(latestDoc) {
    console.log("latestdoc: ", latestDoc);  // エラーで落ちるとき、messageには何が入っているのか見てあげられる
    speaker = latestDoc.actor;
    message = latestDoc.option.text;
    latestId = latestDoc._id;

    // 翻訳処理呼び出し（自動翻訳OFFの場合はnull）
    const translatedText = enableTranslation ? await translateText(message) : null;

    if (speaker === config.leftSideSpeaker) {
        speaker = 'A';
    } else {
        speaker = 'B';
    }

    chatContents = {latestId, speaker, message, translatedText};    // HACK: 単なる値のペアとしているが、柔軟性のあるオブジェクト形式が望ましい。
    console.log(chatContents);
    return chatContents;
}

// 非同期にチャットテキストを取得
async function getChatContent(callback) {
    try {

        // MongoDBに接続
        await client.connect();

        // データベースとコレクションの選択
        const database = client.db(database_name);
        const collection = database.collection(collection_name);

        let chatContentsArray = [];
        
        // データ取得条件
        const initialQuery = {
            command:    'speak',
            status:     'done'
        };
        const query = {
            _id:        { $gt: latestId },
            command:    'speak',
            status:     { $in: ['done', 'is_playing']}
        };

        // データ取得1回目
        if (latestId === null) {
            console.log("Try to Find First Talk Data...");

            // 条件に合う最新のドキュメント（最大の_id）を取得
            const firstDocs = await collection.find(initialQuery).sort({ _id: 1 }).toArray();
            if (firstDocs.length > 0 && latestId === null) {
                console.log("Getting First Talk Data...");
                chatContentsArray.push(await getChatData(firstDocs[firstDocs.length - 1]));
                console.log("Getting First Talk Data...Done");

                // 最大のidを保存
                latestId = firstDocs[firstDocs.length - 1]._id;
            }
        };

        // データ取得2回目以降
        const newDocs = await collection.find(query).sort({ _id: 1 }).toArray();
        if (newDocs.length > 0 && newDocs[newDocs.length - 1]._id !== latestId) {

            // 取得したドキュメントについて並列でデータ取得
            for (let doc of newDocs) {
                console.log("---------- Getting the Talk Data...");
                chatContentsArray.push(await getChatData(doc));
                console.log("---------- Getting the Talk Data...Done");

                // データが一定数以上になったら最古のデータを削除
                const maxBubbles = config.maxBubbles;
                if (chatContentsArray.length > maxBubbles) {
                    chatContentsArray.shift();
                }
            }

            // 最新のidを更新
            latestId = newDocs[newDocs.length - 1]._id;
        };

        return chatContents;

    } catch (error) {
        console.error("ERROR:", error);
    }
}

// 静的ファイルを配信(index.htmlを指定)
app.use(express.static(path.join(__dirname, '../')));

// メッセージを取得するAPIエンドポイント
app.get('/api/messages', async (request, respond) => {
    try {
    const chatContents = await getChatContent();
    respond.json(chatContents);
    } catch (error) {
        console.error('ERROR fetching messages:', error);
        respond.status(500).json({ error: "Internal Server Error" });
    }
});

// サーバー起動
app.listen(port, () => {
    console.log("Server is Running on Port: ", port);
});