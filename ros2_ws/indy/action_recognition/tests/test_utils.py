import pytest
import os
import joblib
import yaml
from argparse import ArgumentParser
import numpy as np

from tools.utils import load_data, load_config, build_parser, train_model


def test_load_data_success(tmp_path):
    dummy_data = (np.array([1, 2, 3]), np.array([0, 1, 0]))
    test_file = tmp_path / "test_data.joblib"
    joblib.dump(dummy_data, test_file)

    data, labels = load_data(str(test_file))
    assert np.array_equal(data, dummy_data[0])
    assert np.array_equal(labels, dummy_data[1])


def test_load_data_file_not_found():
    data, labels = load_data("non_existent_file.joblib")
    assert data is None
    assert labels is None


def test_load_config_success(tmp_path):
    config_content = """
key1: value1
key2: 123
"""
    test_file = tmp_path / "test_config.yaml"
    test_file.write_text(config_content)

    config = load_config(str(test_file))
    assert config == {'key1': 'value1', 'key2': 123}


def test_load_config_file_not_found():
    config = load_config("non_existent_config.yaml")
    assert config is None


def test_build_parser():
    parser = build_parser()
    assert isinstance(parser, ArgumentParser)

    # Test expected arguments
    args = parser.parse_args(['--config-file', 'test.yaml', 'input.joblib', 'output.joblib', '--model_type', 'lightgbm'])
    assert args.config_file == 'test.yaml'
    assert args.input_file == 'input.joblib'
    assert args.output_file == 'output.joblib'
    assert args.model_type == 'lightgbm'

    # Test default model_type
    args = parser.parse_args(['input.joblib', 'output.joblib'])
    assert args.model_type == 'lightgbm'

    # Test positional arguments without options
    args = parser.parse_args(['my_input.joblib', 'my_output.joblib'])
    assert args.input_file == 'my_input.joblib'
    assert args.output_file == 'my_output.joblib'


# For train_model, it's complex and already indirectly tested by test_train_script.py.
# A dedicated unit test would require extensive mocking of sklearn internals,
# which is beyond the scope of this general refactoring.
# The integration test `test_train_script_config_and_args` serves this purpose for now.