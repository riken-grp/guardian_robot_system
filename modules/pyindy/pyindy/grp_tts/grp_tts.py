import json
from io import BytesIO

import numpy as np
import requests
import simpleaudio as sa
from gtts import gTTS
from pydub import AudioSegment
from scipy import interpolate
import time

def change_pitch_fft(audio, shift=512):
    a = np.array(audio.get_array_of_samples())
    afft = np.fft.rfft(a)
    h = np.roll(afft, shift)
    h[0:shift] = 0
    hi_audio = AudioSegment(
        np.fft.irfft(h).real.astype("int16").tobytes(),
        sample_width=audio.sample_width,
        frame_rate=audio.frame_rate,
        channels=1,
    )
    return hi_audio


def change_pitch_resample(audio, rate=1.0):
    a = np.array(audio.get_array_of_samples())
    x = np.arange(len(a))
    print(len(x))
    f = interpolate.interp1d(x, a)
    x = np.arange(np.floor((len(a) * rate))) / rate
    print(len(x))
    h = f(x)
    print(len(h))
    hi_audio = AudioSegment(
        h.real.astype("int16").tobytes(),
        sample_width=audio.sample_width,
        frame_rate=audio.frame_rate,
        channels=1,
    )
    return hi_audio


def silent_frames(num_frames, frame_rate=44100, sample_width=2):
    """
    num_frames: サンプル数（チャネルごとのフレーム数）
    frame_rate: サンプリング周波数
    sample_width: 1サンプルのバイト数（2 = 16bit）
    """
    # 無音のNumPy配列（int16など）を作る
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}[sample_width]
    data = np.zeros(np.floor(num_frames/sample_width).astype(int), dtype=dtype)
    return AudioSegment(
        data.tobytes(),
        frame_rate=frame_rate,
        sample_width=sample_width,
        channels=1
    )
#####################################################################
class grp_tts(object):
    def __init__(self, name, pitch=1.0, rate=1.0, lang="ja", ch="both"):
        self.name = name
        self.pitch = pitch
        self.rate = rate
        self.lang = lang
        self.channel = ch

    def say(self, data):
        print(data)
        print("Usage")

    def play_wav(self, audio):
        if abs(1.0 - self.rate) > 0.01:
            audio = change_pitch_resample(audio, rate=self.rate)
            # resampled_audio = resampled_audio.speedup(playback_speed=self.rate)
        resampled_audio = audio.set_frame_rate(44100)
        resampled_audio = resampled_audio.set_channels(1)
        #
        silent=silent_frames(len(resampled_audio.raw_data), frame_rate=44100, sample_width=2)
        #
        if self.channel == "left":
            stereo_audio = AudioSegment.from_mono_audiosegments(resampled_audio, silent)
        elif self.channel == "right":
            stereo_audio = AudioSegment.from_mono_audiosegments(silent, resampled_audio)
        else:
            stereo_audio = AudioSegment.from_mono_audiosegments(resampled_audio, resampled_audio)
        #
        wav_data = stereo_audio.raw_data
        wav_obj = sa.WaveObject(wav_data)
        play_obj = wav_obj.play()
        stats = {}
        stats["channels"] = stereo_audio.channels
        stats["duration"] = resampled_audio.duration_seconds
        return play_obj, stats

    def print_properties(self):
        print(self.name)


#
class tts_from_gtts(grp_tts):
    def say(self, data):
        print(f"gtts: {data}")
        d = {}
        if "text" in data.keys():
            d["text"] = data["text"]
            if len(d["text"]) == 0:
                d["text"] = "うっ"
        else:
            d["text"] = "言葉に詰まりました"
        mp3_fp = BytesIO()
        try:
            tts = gTTS(d["text"], lang=self.lang)
        except (AssertionError, ValueError, RuntimeError):
            return False, "error"
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)  # move to the start
        data = mp3_fp.read()
        audio = AudioSegment.from_mp3(BytesIO(data))
        p, stats = super().play_wav(audio)
        stats["lang"] = self.lang
        return p, stats


#
class tts_from_http_mp3(grp_tts):
    def say(self, data):
        print("http: mp3: ")
        print(data["url"])
        response = requests.get(data["url"])
        data = response.content
        audio = AudioSegment.from_mp3(BytesIO(data))
        p, stats = super().play_wav(audio)
        return p, stats


#
class tts_from_http_wav(grp_tts):
    def say(self, data):
        print("http: wav: ")
        print(data["url"])
        response = requests.get(data["url"])
        data = response.content
        audio = AudioSegment.from_wav(BytesIO(data))
        p, stats = super().play_wav(audio)
        return p, stats


#
# class tts_from_minato(grp_tts):
class tts_from_hoya(grp_tts):
    def __init__(self, name, pitch=1.0, rate=1.0, tts_rate=1.0, url=False, ch="both"):
        if url:
            self.url = url
        else:
            self.url = "http://example.local:15000/synthesize"
        self.tts_rate = tts_rate
        super().__init__(name=name, pitch=pitch, rate=rate, ch=ch)

    def say(self, data):
        url = self.url
        print(data)
        d = {}
        d["tts_rate"] = self.tts_rate
        d["tts_pitch"] = self.pitch
        if "text_ssml" in data.keys():
            d["text_ssml"] = data["text_ssml"]
            if len(d["text_ssml"]) == 0:
                d["text_ssml"] = "えっ"
        if "text" in data.keys():
            d["text"] = data["text"]
            if len(d["text"]) == 0:
                d["text"] = "おっ"
        else:
            d["text"] = "言葉に詰まりました"
        response = requests.post(url, json=d)
        # if response.ok == False:
        if response.status_code == 502:
            return False, str(response.status_code) + response.text
        data = response.content
        audio = AudioSegment.from_wav(BytesIO(data))
        p, stats = super().play_wav(audio)
        stats["response_status_code"] = str(response.status_code)
        if response.ok == False:
            return False, stats
        return p, stats


#
import sys
if __name__ == '__main__':
    if len(sys.argv) < 1:
        print("grp_tts_stereo.py right or left or both")
        sys.exit(1)
    channel=sys.argv[1]
    actor=tts_from_gtts("test", rate=1.0, ch=channel)
    doc={}
    doc['text']="hello good bye, hello good bye, Magical mistery tour"
    p, s = actor.say(doc)
    print(s)
    time.sleep(s['duration']+0.1)

