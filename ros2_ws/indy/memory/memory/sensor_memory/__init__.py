from __future__ import annotations

from typing import List

from common_msgs.msg import StringStamped  # type:ignore
from recognition_msgs.msg import Objects, Persons  # type: ignore
from std_msgs.msg import String

from .sensor_memory_asr import SensorMemoryASR as SM_ASR
from .sensor_memory_base import PartialSensorMemory
from .sensor_memory_obj import SensorMemoryObject as SM_OBJ
from .sensor_memory_per import SensorMemoryPerson as SM_PER
from .sensor_memory_tts import SensorMemoryTTS_FromActCtrl as SM_TTS


def get_sm_expo_modules() -> List[PartialSensorMemory]:
    return [
        SM_ASR.gen_partial("dia", "asr/meta_data", StringStamped),
        SM_TTS.gen_partial("dia", "robot/action_ctl", String),
        SM_OBJ.gen_partial("obj", "recog/object/tracked", Objects),
        SM_PER.gen_partial("per", "recog/person/pose/associated", Persons),
        # SM_LOC.gen_partial("loc", "rover/pose", PoseStamped),
    ]
