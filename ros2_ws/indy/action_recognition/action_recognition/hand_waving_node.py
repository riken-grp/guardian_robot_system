#!/usr/bin/env python
# coding: utf-8 -*-

import numpy as np

from action_recognition.base_recognition_node import (BaseRecognitionNode,
                                                      normalize_keypoints,
                                                      recognition_node_main)
from action_recognition.model_loader import (declare_model_parameters,
                                             load_model_from_node)


class _RingBuffer:
    """Fixed-length sequence buffer without per-frame copies.

    Each sample is written twice (at ``pos`` and ``pos + seqlen``) so that the
    latest ``seqlen`` samples in chronological order are always available as
    a contiguous view ``buf[pos + 1 : pos + 1 + seqlen]``.
    """

    def __init__(self, seqlen, dim):
        self.seqlen = seqlen
        self.dim = dim
        self.buf = np.zeros((2 * seqlen, dim))
        self.pos = -1
        self.count = 0

    def append(self, x):
        self.pos = (self.pos + 1) % self.seqlen
        self.buf[self.pos] = x
        self.buf[self.pos + self.seqlen] = x
        self.count = min(self.count + 1, self.seqlen)

    def full(self):
        return self.count == self.seqlen

    def window(self):
        """Latest seqlen samples (oldest first), flattened. Valid when full."""
        return self.buf[self.pos + 1 : self.pos + 1 + self.seqlen].reshape(-1)


class WavingHandRecognizer:
    """Hand waving recognition from a sequence of normalized 3D keypoints.

    The feature of a person is the concatenation of the last ``seq_len``
    normalized keypoint vectors (see ``normalize_keypoints``), oldest first.

    - persons with instance_id < 0 (not associated) are not buffered and
      their result is always 0
    - buffers of instance_ids not present in the current frame are dropped
      (the sequence must be continuous)
    """

    def __init__(self, node_instance=None, model=None, seq_len=5):
        if node_instance is not None:
            # Get parameters from the node instance
            seq_len = (
                node_instance.get_parameter("seq_len")
                .get_parameter_value()
                .integer_value
            )

            node_instance.get_logger().info(f"Recognizer Sequence Length: {seq_len}")

            model = load_model_from_node(node_instance)

        self.handwaving_recognizer = model
        self.seqlen = int(seq_len)
        self.buffer = {}  # instance_id -> _RingBuffer

    def normalize(self, data):
        return normalize_keypoints(data)

    def __call__(self, persons):
        seen = set()
        data = []
        available = []
        for p in persons.persons:
            instance_id = int(p.instance_id)
            kps = np.asarray(p.pose_sensor.keypoints, dtype=float)
            if instance_id < 0 or kps.size == 0 or kps.size % 3 != 0:
                available.append(False)
                continue
            seen.add(instance_id)
            feat = self.normalize(kps)
            buf = self.buffer.get(instance_id)
            if buf is None or buf.dim != feat.size:
                buf = _RingBuffer(self.seqlen, feat.size)
                self.buffer[instance_id] = buf
            buf.append(feat)
            if buf.full():
                data.append(buf.window())
                available.append(True)
            else:
                available.append(False)

        # forget persons that are not observed in this frame
        for instance_id in [k for k in self.buffer if k not in seen]:
            del self.buffer[instance_id]

        if len(data) != 0:
            features = np.stack(data)
            rets = self.handwaving_recognizer.predict(features)
        else:
            rets = []

        idx = 0
        results = []
        for a in available:
            if a:
                results.append(rets[idx])
                idx += 1
            else:
                results.append(0)

        return results


class WavingHandNode(BaseRecognitionNode):
    def __init__(self, name="WavingHandNode"):
        super().__init__(
            node_name=name,
            image_topic="in_topic",
            persons_topic="in_person_topic",
            output_topic="out_topic",
            vis_topic="vis_topic",
        )

    def _create_recognizer(self):
        # Declare specific parameters for this node here, after super().__init__ has run
        declare_model_parameters(self, "models/hand_waving_model.joblib")
        self.declare_parameter("seq_len", 5)
        # Note: Common topics parameters are declared in BaseRecognitionNode

        self.state_recognizer = WavingHandRecognizer(
            node_instance=self  # Pass the node instance
        )


def main():
    recognition_node_main(WavingHandNode)
