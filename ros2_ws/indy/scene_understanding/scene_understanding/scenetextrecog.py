import cv2
import easyocr
import numpy as np


class SceneTextRecognizer:
    def __init__(self, threshold):
        self.threshold = threshold
        self.reader = easyocr.Reader(
            ["en", "ja"], verbose=False, model_storage_directory=".", gpu=True
        )

    def __call__(self, img, dimg):
        texts = self.reader.readtext(img)

        for d in texts:
            bb, text, conf = d
            if conf < self.threshold:
                continue
            bb = np.array(bb).astype(np.int32)
            for i in range(4):
                cv2.line(img, bb[i], bb[(i + 1) % 4], (0, 255, 0), 2)

        return texts, img
