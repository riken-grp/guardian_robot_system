# when an adhocgenerator is created, add it here
from .chatgpt_event_generator import ChatGPTEventGenerator
from .default_event_generator import DefaultEventGenerator
from .echo_back_event_generator import EchoBackEventGenerator
from .fixed_event_generator import FixedEventGenerator
from .llm_jp_event_generator import LlmJPEventGenerator
from .llm_jp_event_generator_alt import LlmJPEventGeneratorAlt
from .observation_prompt_generator import ObservationPromptGenerator
from .repeat_event_generator import RepeatEventGenerator


def get_generator(gen_name, config):
    return globals()[gen_name](config)
