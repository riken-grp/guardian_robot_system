#!/usr/bin/env python
# coding: utf-8
import joblib
from .utils import build_parser, load_data, train_model, load_config


def main():
    """Main function to train a model."""
    parser = build_parser()
    args = parser.parse_args()

    config = {}
    if args.config_file:
        config = load_config(args.config_file)
        if config is None:
            print("Exiting due to config loading failure.")
            return

    # Merge config into args, with command-line arguments taking precedence
    for key, value in config.items():
        if getattr(args, key, None) is None: # Only set if not already set by command line
            setattr(args, key, value)
    
    # Ensure positional arguments (input_file, output_file) are handled
    if args.input_file is None:
        if 'input_file' in config:
            args.input_file = config['input_file']
        else:
            args.input_file = "data/processed/default_data.joblib" # Default path

    if args.output_file is None:
        if 'output_file' in config:
            args.output_file = config['output_file']
        else:
            args.output_file = "models/default_model.joblib" # Default path

    print(f"Loading data from: {args.input_file}")
    data, labels = load_data(args.input_file)

    if data is None or labels is None:
        print("Exiting due to data loading failure.")
        return

    print(f"Training a {args.model_type} model...")
    model = train_model(data, labels, model_type=args.model_type)

    print(f"Saving model to: {args.output_file}")
    try:
        joblib.dump(model, args.output_file)
        print("Model saved successfully.")
    except Exception as e:
        print(f"Error saving model to {args.output_file}: {e}")


if __name__ == "__main__":
    main()
