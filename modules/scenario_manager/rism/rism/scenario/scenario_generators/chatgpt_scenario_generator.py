from .abstract_scenario_generator import AbstractScenarioGenerator


class ChatGPTScenarioGenerator(AbstractScenarioGenerator):
    def __init__(self, config):
        self.config = config
        # TODO: ChatGPTのインスタンスを作る
        # TODO: プロンプトを取ってくる

    def generate(self, config, observations):
        # TODO: 何かを生成する．以下はダミー
        data = {}
        data["name"] = "Generated Event"
        data["events"] = [
            {
                "speaker": "robot1",
                "sentence": "LLMで生成したシナリオ",
                "type": "normal",
            },
            {"speaker": "robot2", "sentence": "こんにちは", "type": "normal"},
            {"speaker": "robot1", "sentence": "はいこんにちは", "type": "normal"},
            {"speaker": "robot1", "sentence": "あなたは誰ですか？", "type": "normal"},
            {"speaker": "robot2", "sentence": "あなたは誰ですか？", "type": "normal"},
            {"speaker": "robot1", "sentence": "私は{t[robot1]}です", "type": "blank"},
            {"speaker": "robot2", "sentence": "私は{t[robot2]}です", "type": "blank"},
            {"speaker": "robot2", "sentence": "ほんとだね", "type": "normal"},
            {"speaker": "robot1", "sentence": "おーい", "type": "generate"},
            {"speaker": "robot2", "sentence": "うわぁ", "type": "normal"},
        ]
        return data
