import numpy as np

from action_recognition.base_recognition_node import (BaseRecognitionNode,
                                                      normalize_keypoints,
                                                      recognition_node_main)
from action_recognition.model_loader import (declare_model_parameters,
                                             load_model_from_node)


class WheelChairRecognizer:
    def __init__(self, node_instance=None, model=None):  # Accept node instance
        if node_instance is not None:
            model = load_model_from_node(node_instance)

        self.wheelchair_recognizer = model

    def normalize(self, data):
        # mean over the valid keypoints only; invalid (0, 0, 0) points -> 0
        return normalize_keypoints(data)

    def __call__(self, persons):
        if len(persons.persons) == 0:
            return []
        kps = [np.asarray(p.pose_sensor.keypoints, dtype=float) for p in persons.persons]
        sizes = [k.size for k in kps if k.size > 0]
        dim = max(set(sizes), key=sizes.count) if sizes else 0
        # persons without keypoints (or with an unexpected size) -> 0
        valid = [dim > 0 and k.size == dim and dim % 3 == 0 for k in kps]
        results = [0] * len(kps)
        if any(valid):
            features = np.array([self.normalize(k) for k, v in zip(kps, valid) if v])
            rets = self.wheelchair_recognizer.predict(features)
            idx = [i for i, v in enumerate(valid) if v]
            for i, r in zip(idx, rets):
                results[i] = r

        return results


class WheelChairNode(BaseRecognitionNode):
    def __init__(self, name="WheelChairNode"):
        super().__init__(
            node_name=name,
            image_topic="in_topic",
            persons_topic="in_person_topic",
            output_topic="out_topic",
            vis_topic="vis_topic",
        )

    def _create_recognizer(self):
        # Declare specific parameters for this node here, after super().__init__ has run
        declare_model_parameters(self, "models/wheelchair_model.joblib")
        # Note: Common topics parameters are declared in BaseRecognitionNode

        self.state_recognizer = WheelChairRecognizer(
            node_instance=self  # Pass the node instance
        )


def main():
    recognition_node_main(WheelChairNode)
