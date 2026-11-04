from enum import Enum


class EpisodeState(Enum):
    OFF = "Off"
    WAITING = "Waiting For Episode"
    IN_EPISODE = "In Episode"
    LOOPING = "Looping"

    def __repr__(self) -> str:
        return f"State: {self.value}"
