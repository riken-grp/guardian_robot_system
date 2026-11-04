from abc import ABC, abstractmethod


class AbstractEventGenerator(ABC):

    @abstractmethod
    def generate(self, scenario, speaker_name, event, history, opts):
        pass
        # この関数が返すべき値の形式
        # return [{"speaker": "robot1", "type": "normal", "sentence": sentence}]
        # speaker: "robot1" or "robot2"
        # type: "normal" or "generate" or "blank"
        # sentence: 発話する文字列． type: generateの場合は空文字，type=blankの場合は "これは{t[object]}です．"のような形式
