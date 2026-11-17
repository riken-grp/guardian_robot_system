"""Event Generators for RISM2"""

from .abstract_event_generator import AbstractEventGenerator
from .llm_jp_event_generator_adapter import LlmJPEventGeneratorAdapter
from .echo_back_event_generator import EchoBackEventGenerator
from .multi_gen_and_select_event_generator import MultiGenAndSelectEventGenerator
from .template_event_generator import TemplateEventGenerator
from .keyword_response_event_generator import KeywordResponseEventGenerator
from .knowledge_event_generator import KnowledgeEventGenerator
from .memory_event_generator import MemoryEventGenerator

# speak.option.generator を省略したときに使う Generator
DEFAULT_GENERATOR = "LlmJPEventGenerator"

# シナリオに書く名前 → Generator クラス
GENERATORS = {
    "LlmJPEventGenerator": LlmJPEventGeneratorAdapter,
    "EchoBackEventGenerator": EchoBackEventGenerator,
    "MultiGenAndSelectEventGenerator": MultiGenAndSelectEventGenerator,
    "TemplateEventGenerator": TemplateEventGenerator,
    "KeywordResponseEventGenerator": KeywordResponseEventGenerator,
    "KnowledgeEventGenerator": KnowledgeEventGenerator,
    "MemoryEventGenerator": MemoryEventGenerator,
}

__all__ = [
    "AbstractEventGenerator",
    "DEFAULT_GENERATOR",
    "GENERATORS",
    "LlmJPEventGeneratorAdapter",
    "EchoBackEventGenerator",
    "MultiGenAndSelectEventGenerator",
    "TemplateEventGenerator",
    "KeywordResponseEventGenerator",
    "KnowledgeEventGenerator",
    "MemoryEventGenerator",
    "get_generator",
]


def get_generator(generator_name: str, config: dict) -> AbstractEventGenerator:
    """
    Generatorを名前から取得

    Args:
        generator_name: Generator名（GENERATORS のキー）
        config: 設定辞書

    Returns:
        AbstractEventGeneratorインスタンス
    """
    generator_class = GENERATORS.get(generator_name)
    if generator_class is None:
        raise ValueError(f"Unknown generator: {generator_name}")
    return generator_class(config)
