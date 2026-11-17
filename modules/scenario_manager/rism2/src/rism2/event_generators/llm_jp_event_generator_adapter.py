"""Adapter for LlmJPEventGenerator to work with RISM2 architecture"""

from logging import getLogger
from typing import Any, Dict, List

from .abstract_event_generator import AbstractEventGenerator
from .llm_jp_event_generator import LlmJPEventGenerator


class ScenarioAdapter:
    """Adapter to provide scenario-like interface to LlmJPEventGenerator"""

    def __init__(self, config: Dict[str, Any], actor_mapping: Dict[str, str]):
        self.config = config.copy()
        # Override robots mapping: actor_id -> robot_id for reference implementation
        self.config["robots"] = actor_mapping
        self.prompt = ""  # Default empty prompt
        self.finished_events = []  # Track finished events
        self.scenario_id = None


class LlmJPEventGeneratorAdapter(AbstractEventGenerator):
    """
    Adapter that wraps the reference LlmJPEventGenerator to work with
    the RISM2 AbstractEventGenerator interface.
    """

    def __init__(self, config: Dict[str, Any]):
        self._logger = getLogger(__name__)

        # Convert config structure from RISM2 format to reference format
        adapted_config = self._adapt_config(config)

        # Create the reference implementation
        try:
            self.llm_jp_generator = LlmJPEventGenerator(adapted_config)
            self._logger.info("LlmJPEventGenerator loaded successfully")
        except Exception as e:
            self._logger.error(
                f"Failed to initialize LlmJPEventGenerator: {e}", exc_info=True
            )
            raise

        # Create actor mapping for scenario adapter
        # In RISM2, event["actor"] is the robot_id (e.g., "robot1", "indy3e")
        # Create identity mapping: actor_id -> robot_id
        actor_mapping = {
            robot_id: robot_id for robot_id in config.get("robots", {}).keys()
        }

        # Create scenario adapter
        self.scenario = ScenarioAdapter(adapted_config, actor_mapping)

    def _adapt_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert RISM2 config structure to reference implementation format.

        RISM2 format:
            config["robots"][actor] = {"llm": {...}, "prev_ncm": {...}, "action_db": {...}}
            config["demo"] = {"host": ..., "port": ...}

        Reference format:
            config["robot_list"][actor] = {"llm": {...}, "host": ..., "port": ..., "action_dbname": ...}
            config["db_config"]["scenario_db"] = {"host": ..., "port": ..., "dbname": ..., "col_name": ...}
        """
        adapted = config.copy()

        # Convert robots to robot_list and add required fields
        if "robots" in config:
            robot_list = {}
            for robot_id, robot_conf in config["robots"].items():
                robot_list[robot_id] = robot_conf.copy()

                # Add action_db info for DialogueHistoryManager
                if "action_db" in robot_conf:
                    robot_list[robot_id]["host"] = robot_conf["action_db"].get(
                        "host", "localhost"
                    )
                    robot_list[robot_id]["port"] = robot_conf["action_db"].get(
                        "port", 27017
                    )
                    robot_list[robot_id]["action_dbname"] = robot_conf["action_db"].get(
                        "dbname", "tBlackBoard"
                    )
                else:
                    # Fallback to defaults
                    robot_list[robot_id]["host"] = "localhost"
                    robot_list[robot_id]["port"] = 27017
                    robot_list[robot_id]["action_dbname"] = "tBlackBoard"

            adapted["robot_list"] = robot_list

        # Add db_config for scenario database and internal state logger
        # Get internal state db info from first robot (assume all robots share same db)
        first_robot = next(iter(config.get("robots", {}).values()), {})

        # Try to get internalstate_db info (check for typo version first, then correct version)
        internal_state_db = first_robot.get(
            "internalstate_db", {}
        )  # typo version in DB
        if not internal_state_db:
            internal_state_db = first_robot.get("internalstate_db", {})
        if not internal_state_db:
            # Fallback to action_db (usually same host/port)
            internal_state_db = first_robot.get("action_db", {})

        adapted["db_config"] = {
            "scenario_db": {
                "host": config.get("demo", {}).get("host", "localhost"),
                "port": config.get("demo", {}).get("port", 27017),
                "dbname": "demo_configs",
                "col_name": "scenarios",
            },
            "internal_state_db": {
                "host": internal_state_db.get(
                    "host", internal_state_db.get("hsot", "localhost")
                ),  # Check for typo
                "port": internal_state_db.get("port", 27017),
                "dbname": internal_state_db.get("dbname", "tBlackBoard"),
                "col_name": "internal_state",
            },
        }

        return adapted

    def generate(
        self,
        actor: str,
        event: Dict[str, Any],
        history: List[Dict[str, str]],
        observations: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Adapter method that converts from RISM2 interface to reference interface.

        Args:
            actor: Actor name (RISM2 format)
            event: Event dict with "speak" field (RISM2 format)
            history: Conversation history (RISM2 format)
            observations: Observations including wait_for results (RISM2 format)

        Returns:
            List of generated events in RISM2 format
        """
        # Convert event structure: speak -> utterance
        adapted_event = self._adapt_event_to_reference(actor, event)

        # Call reference implementation
        try:
            generated_events = self.llm_jp_generator.generate(
                scenario=self.scenario,
                speaker_name=actor,
                event=adapted_event,
                history=history,
                opts=observations,
            )
        except Exception as e:
            self._logger.error(
                f"LlmJPEventGenerator.generate failed: {e}", exc_info=True
            )
            # Return a fallback event
            return [
                {
                    "type": "action",
                    "actor": actor,
                    "speak": {"type": "normal", "option": {"text": "[生成失敗]"}},
                }
            ]

        # Convert generated events back: utterance -> speak
        rism_events = [self._adapt_event_from_reference(ev) for ev in generated_events]

        # シナリオの generate イベントに gesture / eye が書いてあれば、ハッシュタグから決めたものより優先する
        # （報告のときに腕を動かす speaking_a など。ほかの Generator の make_speak_event と同じ）
        for ev in rism_events:
            if "speak" not in ev:
                continue
            for key in ("gesture", "eye"):
                if isinstance(event.get(key), dict) and event[key].get("type") != "generate":
                    ev[key] = event[key]

        return rism_events

    def _adapt_event_to_reference(
        self, actor: str, event: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Convert RISM2 event format to reference format.

        RISM2: {"speak": {"type": "generate", "option": {...}}}
        Reference: {"utterance": {"type": "generate", ...}}
        """
        adapted = event.copy()
        adapted["actor"] = actor

        if "speak" in event:
            speak_data = event["speak"]
            option = speak_data.get("option", {})

            # Convert speak -> utterance
            adapted["utterance"] = {
                "type": speak_data.get("type", "generate"),
                **option,  # Merge all options into utterance
            }

            # Remove speak field
            del adapted["speak"]

        return adapted

    def _adapt_event_from_reference(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert reference event format back to RISM2 format.

        Reference: {"utterance": {"type": "normal", "sentence": "..."}}
        RISM2: {"speak": {"type": "normal", "option": {"text": "..."}}}
        """
        adapted = event.copy()

        if "utterance" in event:
            utterance = event["utterance"]

            # Convert utterance -> speak
            adapted["speak"] = {
                "type": utterance.get("type", "normal"),
                "option": {"text": utterance.get("sentence", "")},
            }

            # Remove utterance field
            del adapted["utterance"]

        # Copy other action primitives (gesture, eye) if present
        # These are compatible between both formats

        return adapted
