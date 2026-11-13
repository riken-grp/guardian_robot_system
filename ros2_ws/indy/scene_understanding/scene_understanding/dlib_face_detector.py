import bz2
import os

import cv2
import dlib
import numpy as np
import requests


class FaceDetector:
    def __init__(self, upsample=0):
        """upsample: number of times dlib upsamples the image before detection.

        Each upsample doubles the image size (finds ~2x smaller faces) but
        roughly quadruples the CNN cost on the full frame.
        """
        model_file = "mmod_human_face_detector.dat"
        self.check_and_get_file(model_file)
        self.model = dlib.cnn_face_detection_model_v1(model_file)
        self.upsample = int(upsample)

    def __call__(self, img):
        pimg = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        dets = self.model(pimg, self.upsample)
        return dets

    def check_and_get_file(self, model_file):
        if not os.path.isfile(model_file):
            url = "https://github.com/justadudewhohacks/face-recognition.js-models/raw/master/models/mmod_human_face_detector.dat"
            data = requests.get(url).content
            with open(model_file, "wb") as fout:
                fout.write(data)
