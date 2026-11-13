# coding: utf-8
import argparse
import joblib
import lightgbm as lgb
import numpy as np
from sklearn.metrics import accuracy_score
from sklearn.model_selection import StratifiedKFold, train_test_split
import yaml


def load_data(input_file):
    """Load data from a joblib file."""
    try:
        data, labels = joblib.load(input_file)
        return data, labels
    except Exception as e:
        print(f"Error loading data from {input_file}: {e}")
        return None, None


def load_config(config_file_path):
    """Load configuration from a YAML file."""
    try:
        with open(config_file_path, 'r') as f:
            config = yaml.safe_load(f)
        return config
    except Exception as e:
        print(f"Error loading config from {config_file_path}: {e}")
        return None


def build_parser():
    """Build a command-line parser for training."""
    parser = argparse.ArgumentParser(description="Train a classifier.")
    parser.add_argument("--config-file", type=str, help="Path to a YAML configuration file.")
    parser.add_argument("input_file", type=str, nargs='?', help="Path to the input joblib file.")
    parser.add_argument("output_file", type=str, nargs='?', help="Path to the output model file.")
    parser.add_argument(
        "--model_type",
        type=str,
        default="lightgbm",
        choices=["lightgbm"],
        help="Type of model to train.",
    )
    # Add other model-specific arguments here if needed in the future
    return parser


def train_model(data, labels, model_type="lightgbm"):
    """
    Train a model using cross-validation and return the final model.

    :param data: Training data features.
    :param labels: Training data labels.
    :param model_type: The type of model to train.
    :return: A trained model.
    """
    if model_type != "lightgbm":
        raise NotImplementedError(f"Model type '{model_type}' is not supported yet.")

    num_classes = len(set(labels))
    params = {
        "objective": "multiclass",
        "metric": "multi_logloss",
        "num_class": num_classes,
        "n_estimators": 10000,
        "verbosity": -1,
        "random_state": 0,
        "boosting_type": "gbdt",
    }

    print("Starting 5-fold cross-validation...")
    kf = StratifiedKFold(n_splits=2, shuffle=True, random_state=0)
    accuracies = []

    for i_train, i_test in kf.split(data, labels):
        train_data, test_data = data[i_train], data[i_test]
        train_labels, test_labels = labels[i_train], labels[i_test]

        # Create a validation set from the training data
        train_data, val_data, train_labels, val_labels = train_test_split(
            train_data, train_labels, test_size=0.2, random_state=0
        )

        model = lgb.LGBMClassifier(**params, feature_name=None)
        model.fit(
            train_data,
            train_labels,
            eval_set=[(val_data, val_labels)],
            eval_metric="multi_logloss",
            callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False)],
        )

        preds = model.predict(test_data)
        acc = accuracy_score(test_labels, preds)
        accuracies.append(acc)
        print(f"  Fold accuracy: {acc:.4f}")

    print(f"Average cross-validation accuracy: {np.mean(accuracies):.4f}\n")

    print("Training final model on all data...")
    final_model = lgb.LGBMClassifier(**params, feature_name=None)
    final_model.fit(data, labels)
    print("Final model training complete.")

    return final_model