import pytest
import os
import joblib
import numpy as np
from unittest.mock import patch
from tools.train import main # Import the actual main function


def _create_dummy_features(num_samples, num_features):
    return np.random.rand(num_samples, num_features)

def _create_dummy_labels(num_samples, num_classes):
    return np.random.randint(0, num_classes, num_samples)


@patch('tools.train.train_model')
@patch('tools.train.load_data')
@patch('tools.train.load_config')
def test_train_script_config_and_args(mock_load_config, mock_load_data, mock_train_model, tmp_path):
    mock_load_data.return_value = (np.random.rand(20, 3), np.random.randint(0, 3, 20)) # More robust dummy data
    mock_train_model.return_value = "dummy_trained_model"
    mock_load_config.return_value = {
        'model_type': 'lightgbm_from_config',
        'input_file': 'config_input.joblib',
        'output_file': 'config_output.joblib'
    }

    input_file_cli = tmp_path / "cli_input.joblib"
    output_file_cli = tmp_path / "cli_file.joblib" # changed from output_model.joblib for clarity
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text("model_type: lightgbm") # Only model_type, others will be CLI args



    import sys
    original_argv = sys.argv
    sys.argv = [
        'train.py',
        '--config-file', str(config_file),
        '--model_type', 'lightgbm', # CLI overrides config, must be valid choice
        str(input_file_cli),
        str(output_file_cli)
    ]

    try:
        main() # Call the actual main function
        mock_load_config.assert_called_with(str(config_file))
        mock_load_data.assert_called_with(str(input_file_cli)) # CLI input_file takes precedence
        mock_train_model.assert_called_with(
            mock_load_data.return_value[0],
            mock_load_data.return_value[1],
            model_type='lightgbm' # CLI model_type takes precedence
        )
        assert os.path.exists(output_file_cli)

    finally:
        sys.argv = original_argv
        if os.path.exists(output_file_cli):
            os.remove(output_file_cli)

