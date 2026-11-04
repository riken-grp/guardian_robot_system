from .action_event import ActionEvent
from .command_event import CommandEvent
from .idling_event import IdlingEvent
from .insert_event import InsertEvent
from .observation_event import ObservationEvent


def build_event(event_data: dict, scenario):
    if event_data["type"] == "idling":
        return IdlingEvent(event_data, scenario)
    elif event_data["type"] == "command":
        return CommandEvent(event_data, scenario)
    elif event_data["type"] == "action":
        return ActionEvent(event_data, scenario)
    elif event_data["type"] == "observation":
        return ObservationEvent(event_data, scenario)
    elif event_data["type"] == "insert":
        return InsertEvent(event_data, scenario)
