import simpleaudio as sa
from pydub import AudioSegment
from io import BytesIO
import sys

# MP3 を WAV に変換

def playMP3(mp3_file):
    audio = AudioSegment.from_mp3(mp3_file)
    # print(audio.__class__)
    wav_data = BytesIO()
    audio.export(wav_data, format="wav")
    wav_data.seek(0)
    # simpleaudio で再生
    # wave_obj = sa.WaveObject.from_wave_file(wav_data.name)
    wave_obj = sa.WaveObject.from_wave_file(wav_data)
    play_obj = wave_obj.play()
    stats={}
    stats['duration']=audio.duration_seconds
    stats['channels']=audio.channels
    stats['filename']=mp3_file
    return play_obj, stats
    # play_obj.wait_done()= audio.export(format="wav")

if __name__ == '__main__':
    args=sys.argv
    print(args[1])
    p, stats=playMP3(args[1])
    print(p)
    print(stats)
    p.wait_done()
    
