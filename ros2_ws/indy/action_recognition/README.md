# Action Recognition Package

This package provides ROS2 nodes for real-time human action recognition based on pose estimation results. It also includes a set of tools for preparing data and training custom recognition models.

## 1. Setup

This package requires ROS2 Humble and Python 3.10+.

1.  **Clone the repository:**
    ```bash
    # Assuming your workspace root is ~/ros2_ws/src
    cd ~/ros2_ws/src
    git clone <repository_url>
    ```
2.  **Install Python dependencies:**
    ```bash
    # From your workspace root
    rosdep install --from-paths src --ignore-src -r -y
    pip install -r src/indy/mdr/action_recognition/requirements.txt # (Assuming requirements.txt exists with joblib, lightgbm, numpy, pyyaml, scikit-learn, opencv-python, etc.)
    ```
    *(Note: A `requirements.txt` file does not currently exist. You might need to create one based on the `pip install` commands used during refactoring, e.g., `joblib`, `lightgbm`, `numpy`, `pyyaml`, `scikit-learn`, `opencv-python`.)*
3.  **Build the workspace:**
    ```bash
    # From your workspace root
    colcon build --packages-select action_recognition common_msgs recognition_msgs
    ```
4.  **Source the workspace:**
    ```bash
    # From your workspace root
    source install/setup.bash
    ```

### Pre-trained models (automatic download)

The pre-trained models of `hand_waving_node`, `looking_at_node` and `wheelchair_node` are published on the Hugging Face Hub
as [`yasutomo57jp/models-for-IndyXe`](https://huggingface.co/yasutomo57jp/models-for-IndyXe).
If the file given by `model_path` does not exist, the node downloads it automatically (requires `pip install huggingface_hub`).
Downloaded files are cached under `~/.cache/huggingface` (or `$HF_HOME`), so the download happens only once;
set `HF_HUB_OFFLINE=1` to run from the cache without network access.

| Parameter | Default | Description |
|---|---|---|
| `model_path` | `models/<name>_model.joblib` | Local model file, used if it exists |
| `model_repo_id` | `yasutomo57jp/models-for-IndyXe` | Hugging Face repository (empty: disable download) |
| `model_filename` | `""` | File name in the repository (empty: basename of `model_path`) |
| `model_revision` | `main` | Branch, tag or commit hash to download (pin it for reproducibility) |

In Docker, mount the cache to avoid re-downloading: `-v ~/.cache/huggingface:/root/.cache/huggingface`.

## 2. Node Usage

The action recognition nodes can be launched using ROS2 launch files, and their behavior can be customized via YAML configuration files.

Each recognition node (`hand_waving_node`, `looking_at_node`, `looking_at_simple_node`, `wheelchair_node`) inherits from a `BaseRecognitionNode` which handles common ROS2 functionalities like subscriber/publisher setup and parameter declaration.

To run a node with a custom configuration, you would typically use a launch file that loads your YAML file.

**Example: Running `hand_waving_node` with a custom configuration**

1.  **Create a configuration file** (e.g., `config/hand_waving_node.yaml`):
    ```yaml
    hand_waving_node:
      ros__parameters:
        model_path: "models/my_custom_hand_waving_model.joblib"
        seq_len: 10
        topics:
          output: "my_hand_waving/results"
          visualization: "my_hand_waving/vis"
          input_image: "/camera/image_raw/compressed"
          input_persons: "/person_tracking/persons"
    ```
    *(Note: This example assumes you have a model at `models/my_custom_hand_waving_model.joblib`)*
2.  **Create a launch file** (e.g., `launch/hand_waving_launch.py`):
    ```python
    import os
    from ament_index_python.packages import get_package_share_directory
    from launch import LaunchDescription
    from launch_ros.actions import Node

    def generate_launch_description():
        package_name = 'action_recognition'
        share_dir = get_package_share_directory(package_name)
        config_file = os.path.join(share_dir, 'config', 'hand_waving_node.yaml')

        return LaunchDescription([
            Node(
                package=package_name,
                executable='hand_waving_node',
                name='hand_waving_node',
                output='screen',
                parameters=[config_file]
            )
        ])
    ```
3.  **Launch the node:**
    ```bash
    ros2 launch action_recognition hand_waving_launch.py
    ```

## 3. Tools Workflow: Data Acquisition to Model Building

The `tools/` directory provides scripts to prepare data from ROS2 bags and train recognition models.

### 3.1. Data Preparation (`tools/prepare_data.py`)

This script extracts features from ROS2 bag files and saves them into a `.joblib` file suitable for model training.

**Usage:**
```bash
python3 -m tools.prepare_data --extractor <extractor_name> --topic <input_topic> [--output <output_file>] <bag_file1> [<bag_file2> ...]
```

*   `<extractor_name>`: Name of the feature extractor to use (e.g., `looking_at`, `wheelchair`, `hand_waving`). This determines which features (e.g., face orientation, keypoints) are extracted.
*   `<input_topic>`: The ROS2 topic from which to extract `recognition_msgs/Persons` messages (e.g., `/person_tracking/persons`).
*   `--output <output_file>`: (Optional) Path to the output `.joblib` file. If not provided, it defaults to `data/processed/{extractor_name}_data.joblib`.
*   `<bag_file1> [<bag_file2> ...]`: One or more paths to ROS2 bag files. Each bag file is treated as a different class for labeling (0, 1, 2, ...).

**Example:**
To extract `hand_waving` features from two bag files (representing class 0 and class 1) and save them to `data/processed/hand_waving_data.joblib`:

```bash
python3 -m tools.prepare_data --extractor hand_waving --topic /person_tracking/persons bag1.db3 bag2.db3
```
The output will be saved to `data/processed/hand_waving_data.joblib`.

### 3.2. Model Training (`tools/train.py`)

This script trains a LightGBM classification model using data prepared by `tools/prepare_data.py`.

**Usage:**
```bash
python3 -m tools.train [--config-file <config_path>] [<input_file>] [<output_file>] [--model_type <type>]
```

*   `--config-file <config_path>`: (Optional) Path to a YAML configuration file (e.g., `config/train.yaml`).
*   `<input_file>`: (Optional) Path to the input `.joblib` file containing features and labels. Defaults to `data/processed/default_data.joblib` if not provided via CLI or config.
*   `<output_file>`: (Optional) Path to save the trained model. Defaults to `models/default_model.joblib` if not provided via CLI or config.
*   `--model_type <type>`: (Optional) Type of model to train (currently only `lightgbm` is supported). Defaults to `lightgbm`.

**Example:**
To train a `lightgbm` model using `data/processed/hand_waving_data.joblib` and save it to `models/hand_waving_model.joblib`:

1.  **Create a configuration file** (e.g., `config/train.yaml`):
    ```yaml
    model_type: lightgbm
    input_file: data/processed/hand_waving_data.joblib
    output_file: models/hand_waving_model.joblib
    ```
2.  **Run the training script:**
    ```bash
    python3 -m tools.train --config-file config/train.yaml
    ```
    Alternatively, using command-line arguments:
    ```bash
    python3 -m tools.train data/processed/hand_waving_data.joblib models/hand_waving_model.joblib --model_type lightgbm
    ```

### 3.3. Standard Directory Structure

The recommended directory structure for data and models is:
*   `data/raw/`: For original ROS2 bag files.
*   `data/processed/`: For `.joblib` files generated by `tools/prepare_data.py`.
*   `models/`: For trained model files generated by `tools/train.py`.

## 4. Adding New Action Recognition Models

To add a new action recognition model:

1.  **Define an Extractor:** If your new model requires different features, add a new extractor function to `tools/prepare_data.py` and register it in the `EXTRACTORS` dictionary.
2.  **Prepare Data:** Use `tools/prepare_data.py` to extract features from your ROS2 bag files and save them to `data/processed/`.
3.  **Train Model:** Use `tools/train.py` to train your model and save it to `models/`.
4.  **Create a Recognizer:** Create a new Python class (e.g., `MyNewRecognizer`) similar to `WavingHandRecognizer`. Its `__init__` should accept a `node_instance` and retrieve model-specific parameters (e.g., model path, sequence length) from the node.
5.  **Create a Node:** Create a new ROS2 node (e.g., `my_new_node.py`) that inherits from `BaseRecognitionNode`. Implement the `_create_recognizer` method to instantiate your `MyNewRecognizer`.
6.  **Create a Configuration File:** Create a YAML configuration file (`config/my_new_node.yaml`) for your new node, specifying model paths, topics, and any other node-specific parameters.
7.  **Update `setup.py`:** Add your new node to the `entry_points` in `setup.py` if you want to run it directly, and ensure your new files are included in the package.
8.  **Create a Launch File:** Create a launch file to easily run your new node with its configuration.

## 5. Testing

To run the tests for this package, you will need a Docker environment with ROS2 Humble. The following command performs a clean build of the workspace, handles Python dependencies, generates dummy models for initialization tests, and then runs `pytest`.

```bash
docker run --rm -v $(pwd):/workspace ros2_humble bash -c "source /opt/ros/humble/setup.bash && 
cd /workspace && 
pip uninstall -y numpy && 
pip install numpy==1.23.5 && 
pip install lightgbm pyyaml && 
rm -rf build install log && 
colcon build --packages-select common_msgs recognition_msgs action_recognition && 
source install/setup.bash && 
pip install -e /workspace/indy/mdr/action_recognition && 
cd /workspace/indy/mdr/action_recognition && 
mkdir -p models data/processed && 
python3 -c "import joblib; joblib.dump({}, 'models/hand_waving_model.joblib'); joblib.dump({}, 'models/looking_at_model.joblib'); joblib.dump({}, 'models/wheelchair_model.joblib')" && 
python3 -m pytest"
```
*(Note: Replace `$(pwd)` with the absolute path to your ROS2 workspace root if you are not running from the workspace root.)*
