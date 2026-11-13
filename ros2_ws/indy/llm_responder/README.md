# LLM-Based Response Generator for Indy

Package version (`setup.py`): `1.0.0`

## Requirements

The LLM-Based Response Generator for Indy has the following direct external requirements:

```
numpy==1.24.4
pymongo==4.15.0
setuptools==65.5.0
```

It also requires the following packages, which may in turn have requirements of their own:
- [ROS 2 Humble](https://docs.ros.org/en/humble/index.html) library, required for its `rclpy` package.
- PyIndy, included in this repository at `modules/pyindy`.
- Other Indy internal packages built with ROS: `recognition_msgs` and `common_msgs` (in addition to the standard `std_msgs` and `sensor_msgs`). These contain message definitions that are common among Indy's modules.

## Running the Responder

After building using `colcon build` (in `$GUARDIAN_ROBOT_PATH/ros2_ws`), the responder is run using the following command (the `ROBOT_NAME` environment variable must be set; the node runs in the `/$ROBOT_NAME` namespace):

`ros2 launch llm_responder llm_responder_launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT`

The launcher supports the following launch arguments:
- `mongo_uri`: The URI of the MongoDB server. The launch default is an empty string, so it should always be given.
- `mongo_port`: The Port of the MongoDB server. The launch default is `1`, so it should always be given.

The responder settings (LLM/embedding API, prompts collection, ASR timeouts, `adintool_ports`, etc.) are read from the MongoDB database `robot_config`, collection `system_parameters`, in the Document whose `name` is `llm_responder` (its `config` field). The default data is in `setup/mongo_docker/default_data/robot_config.system_parameters.json`.

# Features

The Responder has the following components:

- `LlmResponderNode` (node name `llm_responder_node`): Main Node. Maintains a loop that waits for a `llm-kd` trigger from Indy's Actions database. Once the trigger occurs, execution is given to `LlmResponseHandler`.
  - `LlmResponseHandler`: Waits for user's utterance in the form of text transcribed by ASR. Then, it generates a response based on that utterance, dialogue history, and a memory if it makes sense (this is the default behavior).
    - `AsrInputTracker`: Helper class that checks if there is a new ASR entry in the dialogue history (`sensor_memory` database, `dia` collection) and builds a dialogue history with N turns.
  - `EpisodeStateTracker`: Holds the current episode state (`OFF` / `WAITING` / `IN_EPISODE` / `LOOPING`), which is changed through the `memory/episode_ctl` topic. The initial state is given by `initial_mode` in the MongoDB parameters.
- `LlmMicWatchdogNode` (node name `llm_adintool_watchdog`, runs in the same process): This Node has two purposes. First, it checks whether the ASR results (`asr/meta_data`) come from adintool ports, which are listed in `adintool_ports` of the `llm_responder` MongoDB parameters (default `[5580]` when the parameters are not found). Input from adintool is then processed and inserted into the proper databases. The second objective is to use LLM calls to make a basic intent recognizer: it calls the LLM with the user's utterance transcription and asks if the user's intent is to talk. When it does, it inserts that intention into Physical DB.

## Triggering the Responder

Currently, the responder uses **LLM-based Keyword Activation**, which means we call an LLM with a prompt that evalutes a user utterance and if their intention is to *start* a conversation, trigger an Action that will be consumed by the Scenario Manager to start a given scenario.

## Calling the Responder

In the Scenario Script, simply add an event with the `llm-kd` trigger. Below you will find a working example with some optional parameters that will be explained afterwards:

```json
 {
    "_id": <Object ID>,
    "actor": "robot1",
    "interruptable": false,
    "trigger": [
      {
        "llm-kd": {
          "reply": <Name of Prompt>
        }
      }
    ],
    "timeout": 40,
    "hist_to_prompt": <boolean>, /*optional, default is false*/
    "success": [
      {
        "actor": "robot1",
        "interruptable": false,
        "utterance": {
          "type": "blank",
          "sentence": "{buffer[<Object ID>][contents][words]}"
        },
        "type": "action"
      }
    ],
    "failure": [
      {
        "actor": "robot1",
        "interruptable": true,
        "utterance": {
          "type": "normal",
          "sentence": "えーっと。。うん。。"
        },
        "type": "action"
      }
    ],
    "type": "observation"
  },
```

The `<Name of Prompt>` in the `"trigger"` is the name of one of the prompts in the `memory_settings/llm_prompts` collection in the Database. 

The `<Object ID>` in `"_id"` and the `"success"` parameter must be the same. This signals the Scenario Manager to retrieve the generated utterance from its Database.

The `hist_to_prompt` parameter is a special one that tells the LLM Responder that the history of the current conversation must be reformatted to be added as part of the instruction prompt, instead of included as part of the dialogue with the LLM. The prompts that we have developed for our common usage of Indy's memory use this kind of structure, but if someone wants the conversation between User and Indy to be internally formatted as a conversation between User and LLM-as-Indy, this parameter can be ommited or set to False.

# Development

## Recent changes

Improvements to Dialogue Intention triggerer, Episode-tracking, compatibility with some  Prompt substitutions.