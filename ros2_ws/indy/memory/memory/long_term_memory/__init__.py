from typing import List

from .lterm_memory_base import PartialLongTermMemory
from .lterm_memory_narrative import LongTermNarrative as LTM_NARR


def get_ltm_expo_modules() -> List[PartialLongTermMemory]:
    return [LTM_NARR.gen_partial("dia", "narrative")]
