from enum import Enum


class EpisodeState(Enum):
    OFF = "Off"
    WAITING = "Waiting For Episode"
    IN_EPISODE = "In Episode"
    LOOPING = "Looping"

    def __repr__(self) -> str:
        return f"State: {self.value}"

    def can_start_episode(self) -> bool:
        return (
            self == EpisodeState.WAITING
            or self == EpisodeState.OFF
            or self == EpisodeState.LOOPING
        )

    def can_start_loop(self) -> bool:
        return self == EpisodeState.WAITING or self == EpisodeState.OFF


class EpisodeStateTracker:
    def __init__(self, estate: EpisodeState = EpisodeState.OFF) -> None:
        self.ep_state = estate
