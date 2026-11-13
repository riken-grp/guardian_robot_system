#!/usr/bin/env python
# coding: utf-8

from argparse import ArgumentParser

import joblib
import numpy as np
import rclpy
from rclpy.serialization import deserialize_message
from rosbag2_py import ConverterOptions, SequentialReader, StorageOptions
from rosidl_runtime_py.utilities import get_message


def extract_looking_at(msg):
    """Extractor for 'looking_at' features."""
    if len(msg.persons) != 1:
        return None
    person = msg.persons[0]
    return np.concatenate((person.face_location, person.face_orientation))


def extract_wheelchair(msg):
    """Extractor for 'wheelchair' (full body pose) features."""
    if len(msg.persons) != 1:
        return None
    return np.asarray(msg.persons[0].pose_sensor.keypoints)


# Add new extractors here as needed.
# For example, for hand-waving, which might use the same features as wheelchair:
extract_hand_waving = extract_wheelchair


EXTRACTORS = {
    "looking_at": extract_looking_at,
    "wheelchair": extract_wheelchair,
    "hand_waving": extract_hand_waving,
}


def save_messages_from_bag(bag_files, topic_name, output_file, extractor_name):
    """
    Reads ROS2 bag files, extracts messages from a specific topic, processes them
    using a specified extractor, and saves the results to a joblib file.
    """
    if extractor_name not in EXTRACTORS:
        print(f"Error: Extractor '{extractor_name}' not found.")
        print("Available extractors:", list(EXTRACTORS.keys()))
        return

    extractor_func = EXTRACTORS[extractor_name]
    rclpy.init()

    features = []
    labels = []

    print(f"Processing {len(bag_files)} bag file(s)...")
    for class_id, bag_file in enumerate(bag_files):
        print(f"  - Reading '{bag_file}' for class {class_id}")
        reader = SequentialReader()
        storage_options = StorageOptions(uri=bag_file, storage_id="sqlite3")
        converter_options = ConverterOptions(
            input_serialization_format="cdr", output_serialization_format="cdr"
        )
        reader.open(storage_options, converter_options)

        topic_types = reader.get_all_topics_and_types()
        type_dict = {topic.name: topic.type for topic in topic_types}

        if topic_name not in type_dict:
            print(
                f"Warning: Topic '{topic_name}' not found in bag file '{bag_file}'. Skipping."
            )
            continue

        msg_type = get_message(type_dict[topic_name])

        while reader.has_next():
            (topic, data, t) = reader.read_next()
            if topic == topic_name:
                msg = deserialize_message(data, msg_type)
                feature_vector = extractor_func(msg)
                if feature_vector is not None:
                    features.append(feature_vector)
                    labels.append(class_id)

    if not features:
        print("No features were extracted. Output file will not be created.")
        rclpy.shutdown()
        return

    print(
        f"Successfully extracted {len(features)} feature vectors. Saving to '{output_file}'."
    )
    joblib.dump((np.asarray(features), np.asarray(labels)), output_file)
    rclpy.shutdown()
    print("Done.")


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Extract features from ROS2 bag files and save to a joblib file."
    )
    parser.add_argument(
        "--extractor",
        required=True,
        choices=EXTRACTORS.keys(),
        help="The name of the feature extractor to use.",
    )
    parser.add_argument(
        "--topic", required=True, help="Name of the topic to extract messages from."
    )
    parser.add_argument(
        "--output", help="Path to the output joblib file. Defaults to data/processed/{extractor_name}_data.joblib if not provided."
    )
    parser.add_argument(
        "bag_files", nargs="+", help="Paths to the ROS2 bag files."
    )

    args = parser.parse_args()

    output_file = args.output
    if output_file is None:
        output_file = f"data/processed/{args.extractor}_data.joblib"

    save_messages_from_bag(
        args.bag_files, args.topic, output_file, args.extractor
    )
