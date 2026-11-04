from .abstract_event_generator import AbstractEventGenerator


class ChatGPTEventGenerator(AbstractEventGenerator):
    """ChatGPTを使って応答する例"""

    def __init__(self, config):
        # TODO: chatgptのインスタンスを作る
        # TODO: プロンプトを取ってくる
        pass

    def generate(self, scenario, speaker_name, event, history, opts):
        # TODO: プロンプトを作る
        # TODO: chatGPTの応答を得る
        sentence = ""
        return [{"speaker": event["speaker"], "type": "normal", "sentence": sentence}]
