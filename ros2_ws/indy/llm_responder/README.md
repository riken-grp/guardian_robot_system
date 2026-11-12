# LLM-Based Response Generator for Indy

Version `1.0.0`

## Requirements

The LLM-Based Response Generator for Indy has the following direct external requirements:

```
numpy==1.24.4
pymongo==4.15.0
setuptools==65.5.0
```

It also requires the following packages, which may in turn have requirements of their own:
- [ROS 2 Humble](https://docs.ros.org/en/humble/index.html) library, required for its `rclpy` package.
- [PyIndy](https://github.com/riken-grp/pyindy/tree/develop/pyindy) (Latest version)
- Other Indy internal packages built with ROS: `std_msgs`, `recognition_msgs` and `common_params`. These contain message and parameter file definitions that are common among all of Indy's modules.

## Running the Responder

After building using `colcon build`, the responder is run using the following command:

`ros2 launch llm_responder llm_responder_launch.py`

The launcher supports the following ROS2 parameters:
- `mongodb`: The URI for the MongoDB in which the memory will be stored. The default is `localhost`.
- `mongoport`: The Port for the MongoDB. The default is `6000`.

# Features

The Responder has the following components:

- `LlmResponseNode`: Main Node. Maintains a loop that waits for a `llm-kd` trigger from Indy's Actions database. Once the trigger occurs, execution is given to `LlmObservationHandler`.
  - `LlmObservationHandler`: Maintains a loop that waits for user's utterance in the form of text transcribed by ASR. Then, it generates a response based on that utterance, dialogue history, and a memory if it makes sense (this is the default behavior).
    - `LlmObservationChecker`: Checks if there is a new ASR entry in the `dialogue_history` collection in Indy's MongoDB, and creates a new dialogue history with N turns.
  - `ScenarioChecker`: Used to check whenever a Scenario changes. In particular, it is used to check the start of an Episode, which is used to ignore wake keyword scenario start.
- `LlmMicWatchdogNode`: This Node has two purposes. First, it detects whether the ASR results come from the ports of a Microphone array, or from adintool (Right now, the mic array ports are hard-coded to `[5562, 5563, 5564]`). Input from adintool is then processed and inserted into the proper databases. The second objective is to use LLM calls to make a basic intent recognizer: it calls the LLM with a special prompt and the user's utterance transcription and asks if the user's intent is to talk. When it does, it inserts that intention into Physical DB.
- `AsrInputTracker`: Helper class that is used to access Dialog Memory, 

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

## Version 1.0.5

Improvements to Dialogue Intention triggerer, Episode-tracking, compatibility with some  Prompt substitutions.