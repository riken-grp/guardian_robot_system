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

    @staticmethod
    def _crop_face(img, face):
        """Crop the (enlarged) head region of a face bbox (l, t, r, b)."""
        l, t, r, b = map(int, face)

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
        if r <= l or b <= t:
            return None
        return img[t:b, l:r]

    def estimate_batch(self, img, faces):
        """Estimate (yaw, pitch, roll) of all faces in one forward pass.

        img: BGR image (cv2).  faces: list of (l, t, r, b).
        Returns a list aligned with ``faces``; None for faces whose crop is
        empty.
        """
        results = [None] * len(faces)
        tensors = []
        indices = []
        for i, face in enumerate(faces):
            fimg = self._crop_face(img, face)
            if fimg is None:
                continue
            # Hopenet is trained on RGB images
            fimg = Image.fromarray(cv2.cvtColor(fimg, cv2.COLOR_BGR2RGB))
            tensors.append(self.transformations(fimg))
            indices.append(i)
        if not tensors:
            return results

        with torch.inference_mode():
            batch = torch.stack(tensors, dim=0).to(self.idx_tensor.device)
            yaw, pitch, roll = self.model(batch)
            # expected value of the bin distributions -> degrees, (B, 3)
            angles = torch.stack(
                [
                    torch.sum(F.softmax(x, dim=1) * self.idx_tensor, dim=1) * 3 - 99
                    for x in (yaw, pitch, roll)
                ],
                dim=1,
            )
            angles = angles.cpu().numpy()  # single GPU -> CPU sync

        for i, a in zip(indices, angles):
            results[i] = (float(a[0]), float(a[1]), float(a[2]))
        return results

    def estimate(self, img, face):
        return self.estimate_batch(img, [face])[0]

    def visualize(self, img, ltrb, ypr, with_bb=True):
        l, t, r, b = ltrb  # face bb
        yaw, pitch, roll = ypr  # face roll, pitch, yaw

        if with_bb:
            img = cv2.rectangle(img, (l, t), (r, b), (0, 255, 0), 3)

        utils.draw_axis(
            img, yaw, pitch, roll, tdx=(l + r) / 2, tdy=(t + b) / 2, size=(b - t) / 4
        )
        return img
