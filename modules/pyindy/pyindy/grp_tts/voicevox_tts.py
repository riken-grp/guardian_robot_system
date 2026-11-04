# coding: utf-8
import requests
import json
from pydub import AudioSegment
from io import BytesIO
from .grp_tts import grp_tts


class tts_from_VOICEVOX(grp_tts):
    def __init__(self, name="Indy", pitch=1.0, rate=1.0, host="127.0.0.1", port=50021, character=3):
        super().__init__(name, pitch, rate)
        # エンジン起動時に表示されているIP、portを指定
        self.host = host
        self.port = port
        self.speaker = character
        
    def say(self, data):
        print("voicevox:")
        d = {}
        if 'text' in data.keys():
            d['text']=data['text']
            if len(d['text'])==0:
                d['text']='うっ'
        else:
            d['text']="言葉に詰まりました"

        params = (
            ('text', d["text"]),
            ('speaker', self.speaker),
        )

        # 音声合成用のクエリ作成
        query = requests.post(
            f'http://{self.host}:{self.port}/audio_query',
            params=params
        )
        
        # 音声合成を実施
        synthesis = requests.post(
            f'http://{self.host}:{self.port}/synthesis',
            headers = {"Content-Type": "application/json"},
            params = params,
            data = json.dumps(query.json())
        )
        
        voice = synthesis.content
        audio = AudioSegment.from_file(BytesIO(voice), format="wav")
        p, stats=super().play_wav(audio)
        return p, stats

