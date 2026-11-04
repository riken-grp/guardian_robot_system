from typing import List

from .sterm_memory_base import PartialShortTermMemory
from .sterm_memory_dia import ShortTermDiaMemory as STM_DIA
from .sterm_memory_obj import ShortTermObjMemory as STM_OBJ
from .sterm_memory_per import ShortTermPerMemory as STM_PER


def get_stm_expo_modules() -> List[PartialShortTermMemory]:
    return [
        STM_DIA.gen_partial("dia", "dia"),
        STM_OBJ.gen_partial("obj", "obj"),
        STM_PER.gen_partial("per", "per"),
        # STM_LOC.gen_partial("loc", "loc"),
    ]
