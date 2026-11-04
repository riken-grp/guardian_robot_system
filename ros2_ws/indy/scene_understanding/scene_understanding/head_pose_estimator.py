import os

import cv2
import numpy as np
import requests
import torch
import torch.nn.functional as F
import torchvision
from PIL import Image
from torchvision import transforms

from . import hopenet, utils


class HeadPoseEstimator:
    def __init__(self, model_file, device):
        self.model = hopenet.Hopenet(
            torchvision.models.resnet.Bottleneck, [3, 4, 6, 3], 66
        )
        if not os.path.isfile(model_file):
            url = "https://drive.usercontent.google.com/download?id=1EJPu2sOAwrfuamTitTkw2xJ2ipmMsmD3&export=download&authuser=0"
            data = requests.get(url).content
            with open(model_file, "wb") as fout:
                fout.write(data)
        saved_state_dict = torch.load(model_file)
        self.model.load_state_dict(saved_state_dict)
        self.model.cuda(device)
        self.model.eval()

        self.transformations = transforms.Compose(
            [
                transforms.Resize(224),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
                ),
            ]
        )

        idx_tensor = [idx for idx in range(66)]
        self.idx_tensor = torch.FloatTensor(idx_tensor).cuda()

    def estimate(self, img, face):
        l, t, r, b = face

        bbw = r - l
        bbh = b - t
        l -= 2 * bbw // 4
        r += 2 * bbw // 4
        t -= 3 * bbh // 4
        b += bbh // 4
        l = max(l, 0)
        t = max(t, 0)
        r = min(img.shape[1], r)
        b = min(img.shape[0], b)

        fimg = img[t:b, l:r]
        fimg = Image.fromarray(fimg)

        fimg = self.transformations(fimg)
        fimg = fimg.unsqueeze(0).cuda()
        yaw, pitch, roll = self.model(fimg)

        yaw_predicted = F.softmax(yaw)
        pitch_predicted = F.softmax(pitch)
        roll_predicted = F.softmax(roll)

        yaw_predicted = torch.sum(yaw_predicted.data[0] * self.idx_tensor) * 3 - 99
        pitch_predicted = torch.sum(pitch_predicted.data[0] * self.idx_tensor) * 3 - 99
        roll_predicted = torch.sum(roll_predicted.data[0] * self.idx_tensor) * 3 - 99

        return float(yaw_predicted), float(pitch_predicted), float(roll_predicted)

    def visualize(self, img, ltrb, ypr, with_bb=True):
        l, t, r, b = ltrb  # face bb
        yaw, pitch, roll = ypr  # face roll, pitch, yaw

        if with_bb:
            img = cv2.rectangle(img, (l, t), (r, b), (0, 255, 0), 3)

        utils.draw_axis(
            img, yaw, pitch, roll, tdx=(l + r) / 2, tdy=(t + b) / 2, size=(b - t) / 4
        )
        return img
