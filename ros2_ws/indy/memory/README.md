# Memory System

This is version `2.0.5` the implementation files for Indy's Memory System. 

## Requirements

The Memory System has the following direct external requirements:

```
chromadb==1.2.1
numpy==2.0.0
openai==1.35.12
pymongo==4.7.3
PyYAML==6.0.1
scipy==1.14.0
setuptools==65.5.0
```

It also requires the following packages, which may in turn have requirements of their own:
- [ROS 2 Humble](https://docs.ros.org/en/humble/index.html) library, required for its `rclpy` package.
- [PyIndy](https://github.com/riken-grp/pyindy/tree/develop/pyindy) (Latest version)
- Other Indy internal packages built with ROS: `std_msgs`, `recognition_msgs`. These contain message and parameter file definitions that are common among all of Indy's modules.

## Running the Memory System

There is a Launch File to run the memory system. It supports the following topics:

- Object Recognition: `/recog/object/tracked`
- Person Recognition: `/recog/person/pose/associated`
- Environmental Sensor: `/out_topic` (Currently not implemented)
- Automatic Speech Recognition: `/asr/meta_data`
- Rover Location estimation: `/rover/pose` (Currently disabled)
- Text-To-Speech information: `/robot/action_ctl` (Only TTS messages are processed)
- Scene Graph data: `/recog/scenegraph`(Currently disabled)

If a topic is absent, the memory system does not subscribe to it.

To Launch the Memory System's Launch file, run the following command on an environment sourced on ROS2 Humble and after `colcon build`ing and sourcing the Indy project:

`ros2 launch memory all_memory_launch.py`

This will launch the Memory System with the default parameters.

The launcher supports the following ROS2 parameters:
- `mongodb`: The URI for the MongoDB in which the memory will be stored. The default is Indy's `localhost`.
- `mongoport`: The Port for the MongoDB. The default is `6000`.

# Memory System Structure

There are three planned levels for this system:

## Sensor Memory

Saves the information published by Indy's recognition systems into collections inside MongoDB database. These systemas are:

| System | Collection | Description |
|--------|------------|-------------|
| ASR | `asr` | Automatic Speech Recognition |
| Environment Sensor | `env` | Environmental Sensor (Temperature, Pressure, etc.) |
| Object Recognition | `obj` | Object Recognition |
| Person Recognition | `per` | Person Recognition |
| Location | `loc` | Self-localization Estimation |
| Text-To-Speech | `tts` | Text-to-Speech information |
| Scene Graph | `sce` | Scene Graph generation data. |

The data published by these systems is saved with minimal changes. At regular intervals, the records in Sensor Memory are compiled and saved into Short-Term Memory, at which point they are removed from Sensor Memory. As such, Sensor Memory is always compact.

**NOTE**: For the Expo version, not all of these nodes will be gathered.

## Short-Term Memory

Compiles the information in Sensor Memory into slightly more complex objects. For example, a series of object recognition results that identify the same object are grouped into the same Short-Term Memory record. Additionally, these records are given a Forgetting Curve, which limits the amount of time the record will remain in memory. All Forgetting Curves decay at regular intervals, as long as the record is not updated (i.e. when a new recognition occurs). An updated record is reinforced, with a new starting value. All records in Short-Term Memory that subsist for a given period of time can be transferred to Long-Term Memory.

In this release, the only Short-Term Memory modules are **Dialogue** (Which compiles multiple ASR and TTS into a single storage), **Object Recognition** and **Person Recognition**.

The Dialogue module does not store the full dialogue information, summarizing multiple conversation turns instead. This conversation gets further summarized over time as it is "forgotten".

(**NEW**) In order to "Memorize" a Dialogue Episode, the Episode's *start* and *end* must be signaled in the **Scenario Manager**, via a a pair of `ros_command`-type events as part of the scenario script:
```
"ros_command": {
  "type": "command",
  "_id": <Unique Object ID>,
  "topic": "memory/episode_ctl",
  "topic_type": "std_msgs/msg/String",
  "data": "memory start episode"
},
```
and
```
"ros_command": {
  "type": "command",
  "_id": <Unique Object ID>,
  "topic": "memory/episode_ctl",
  "topic_type": "std_msgs/msg/String",
  "data": "memory end episode"
},
```
This gives the Scenario writer control over whether or not Indy incorporates a given scenario into its long-term memory.

## Long-Term Memory

Creates more complex memories. Currently the only Long-Term Memory is the **Narrative** memory module, which compiles multiple Dialogue summaries from Short-Term Memory and summarizes them together. This happens once a day, after midnight.

## Recall

Recall takes place in the *LLM Responder* module, when Indy interacts with the users.

## Chroma DB

Dialogue Memorization and Recall make use of an *Embeddings Database*. We use [Chroma](https://www.trychroma.com/)'s web-based API, as a child subprocess to the main Node. It is only run when the Memory Settings include the `db_url` and `db_port` settings, which launches a server listening on that URL and Port.

# Memory Settings

All memory settings can be found in MongoDB, in the `memory_settings` database. It has three collections:

- `robot_settings`: General Memory settings, such as 
    - `robot_name`
    - `llm`: settings for the LLM used in summarization, including its system prompt.
    - `embed_api`: settings for the Embeddings database, including its location in the file system and the API used to generate the embeddings.
    - `memory_level`: Configuration that determines whether a given type of memory runs, and forgets.
        - `sm_lvl`: Sensor Memory Level. Default value is `2`. Possible values are:
            - `1` for working sensor memory without forgetting; or 
            - `2` for working sensor memory with forgetting every five minutes.
        - `stm_lvl`: Short-Term Memory Level. Default value is `2`. Possible values are:
            - `0` to disable short-term memory; 
            - `1` for working short-term memory without forgetting; or 
            - `2` for working short-term memory with forgetting based on each module's forgetting curve and heuristics.
        - `ltm_lvl`: Long-Term Memory Level. Default value is `2`. Possible values are:
            - `0` to disable long-term memory; 
            - `1` for working long-term memory without forgetting; or 
            - `2` for working long-term memory with forgetting based on each module's forgetting curve and heuristics.
    - `mem_eval`: enable evaluation logging, which records various execution data to a separate database (`memory_eval`). Default value is `False`.
    - `default_forgetting`: Default Forgetting parameters. Only used when first creating the database settings.
- `llm_prompts`: Collection of Prompts used in dialogue summarization. Each promp comes in English and Japanese.
- `module_settings`: Individual settings for each module. Mostly focused on forgetting parameters.

## Other Databases

The following Databases are necessary to run the memory. All are created automatically upon running the Memory for the first time:
- `sensor_memory`
- `short_term_memory`
- `long_term_memory`
- `memory_settings` -- Note: The system creates default values for most settings, except for the `llm_prompts` collection. You can find a backup of the prompts on the `prompts/memory_settings.llm_prompts.json` file in this repository.

# Development

## Version 2.0.5

- Dialogue Short-Term Memory has been reworked to be triggered by the Scenario Manager.
- Narrative Long-Term Memory has been reworked to compile Short-Term Memories at the end of the day. Similarly, default Dialogue STM parameters for memory decay have been adjusted to give memories longer tails, which makes them last much longer than a single day. This ensures they are caught by Long Term Memory.
