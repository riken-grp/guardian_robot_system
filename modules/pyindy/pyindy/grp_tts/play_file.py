import json
import simpleaudio as sa
from pydub import AudioSegment
from io import BytesIO
from gtts import gTTS

class play_file(object):
    def __init__(self, dir):
        self.dir = dir
    def say(self, data):
        file=self.dir+data['filename']
        print("filename: ", file)
    def play_wav(self, audio):
        if abs(1.0-self.rate) > 0.01:
            audio=change_pitch_resample(audio, rate=self.rate)
            # resampled_audio = resampled_audio.speedup(playback_speed=self.rate)
        resampled_audio = audio.set_frame_rate(44100)
        resampled_audio = resampled_audio.set_channels(2)
        wav_data = resampled_audio.raw_data
        wav_obj=sa.WaveObject(wav_data)
        play_obj=wav_obj.play()
        stats={}
        stats['channels']=audio.channels
        stats['duration']=resampled_audio.duration_seconds
        return play_obj, stats
    def print_properties(self):
        print(self.dir)

if __name__ == '__main__':
    pf=play_file('hoge')
    pf.print_properties()
    data={}
