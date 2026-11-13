import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torchvision.models import Swin_V2_S_Weights, feature_extraction, swin_v2_s
from torchvision.transforms import transforms


class AttributeRecognitionModel_PK100K_Binary(nn.Module):
    def __init__(self):
        super().__init__()
        # pretrained = efficientnet_v2_s(weights=EfficientNet_V2_S_Weights.IMAGENET1K_V1)  # 1280 dim
        pretrained = swin_v2_s(weights=Swin_V2_S_Weights.IMAGENET1K_V1)  # 768 dim
        # pretrained = vgg16(weights=VGG16_Weights.IMAGENET1K_V1)  # 25088 dim

        self.backbone = feature_extraction.create_feature_extractor(
            pretrained, ["flatten"]
        )

        # for param in self.backbone.parameters():
        #    param.requires_grad = False

        self.cls_head = nn.Sequential(
            nn.Linear(768, 256),
            nn.Dropout(0.5),
            nn.LeakyReLU(),
            nn.Linear(256, 128),
            nn.Dropout(0.5),
            nn.LeakyReLU(),
            nn.Linear(128, 20),
            nn.Sigmoid(),
        )

    def get_binary_weights(self, weights):
        return 1 - weights / 80000

    def forward(self, x):
        with torch.no_grad():
            features = self.backbone(x)["flatten"]

        results = self.cls_head(features)
        return results


class AttributeRecognitionModel_fujishiro(nn.Module):
    age_class_names = {
        0: "under 15",
        1: "under 30",
        2: "under 45",
        3: "under 60",
        4: "over 60",
    }

    gender_class_names = {
        0: "Male",
        1: "Female",
    }

    color_class_names = {
        0: "Black",
        1: "Blue",
        2: "Brown",
        3: "Green",
        4: "Grey",
        5: "Orange",
        6: "Pink",
        7: "Purple",
        8: "Red",
        9: "White",
        10: "Yellow",
    }

    def __init__(self):
        super().__init__()
        weights = Swin_V2_S_Weights.IMAGENET1K_V1
        self.backbone = swin_v2_s(weights=weights)
        self.backbone._fc = nn.Identity()
        for param in self.backbone.parameters():
            param.requires_grad = False
        self.backbone2 = nn.MaxPool2d(64, stride=32)

        self.shared_branch = nn.Sequential(
            nn.BatchNorm1d(1000),
            nn.Linear(1000, 256),
            nn.Dropout(0.5),
            nn.LeakyReLU(),
        )
        self.age_branch = nn.Sequential(
            nn.Linear(256, 128),
            nn.Dropout(0.5),
            nn.LeakyReLU(),
            nn.Linear(128, 5),
        )
        self.gender_branch = nn.Sequential(
            nn.Linear(256 + 108, 32),
            nn.Dropout(0.5),
            nn.LeakyReLU(),
            nn.Linear(32, 2),
        )
        self.cloth_color_branch = nn.Sequential(
            nn.Linear(256 + 108, 128),
            nn.Dropout(0.5),
            nn.LeakyReLU(),
            nn.Linear(128, 11),
            nn.Sigmoid(),
        )

        self.age_loss = nn.CrossEntropyLoss()
        self.gender_loss = nn.CrossEntropyLoss()
        self.ccolor_loss = nn.BCELoss()

    def forward(self, x):
        features = self.backbone(x)
        features = self.shared_branch(features)
        cfeatures = self.backbone2(x).reshape(len(features), -1)

        age = self.age_branch(features)
        gender = self.gender_branch(torch.cat([features, cfeatures], 1))
        cloth_color = self.cloth_color_branch(torch.cat([features, cfeatures], 1))

        return age, gender, cloth_color


class AttributeRecognizer:
    def __init__(self, modelfile):
        # model = AttributeRecognitionModel_fujishiro()
        # model.load_state_dict(torch.load(modelfile))
        self.class_names = np.asarray(
            [
                "Hat",
                "Glasses",
                "HandBag",
                "ShoulderBag",
                "Backpack",
                "HoldObjectsInFront",
                "ShortSleeve",
                "LongSleeve",
                "UpperStride",
                "UpperLogo",
                "UpperPlaid",
                "UpperSplice",
                "LowerStripe",
                "LowerPattern",
                "LongCoat",
                "Trousers",
                "Shorts",
                "Skirt&Dress",
                "boots",
            ]
        )
        model = AttributeRecognitionModel_PK100K_Binary()
        model.load_state_dict(torch.load(modelfile))
        model.eval()
        self.model = model.cuda()

        image_size = 224
        self.tfms = transforms.Compose(
            [
                transforms.Resize(256),
                transforms.CenterCrop((image_size, image_size)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )

    def __call__(self, imgs):
        """
        imgs: list of cv2 (BGR) images
        """
        # the model (Swin, ImageNet normalization) expects RGB images
        imgs = torch.stack(
            [self.tfms(self._to_pil(img)) for img in imgs], dim=0
        ).cuda()
        with torch.inference_mode():
            results = self.model(imgs).cpu().numpy()

        presults = results[:, 1:] > 0.7
        attributes = []
        for p, r in zip(presults, results):
            att = {}
            if r[0] < 0.5:
                att["Male"] = 1 - r[0]
            else:
                att["Female"] = r[0]

            # pair the selected names with their own (selected) scores
            att.update({x: float(y) for x, y in zip(self.class_names[p], r[1:][p])})
            attributes.append(att)
        return attributes

    @staticmethod
    def _to_pil(img):
        """cv2 BGR image -> PIL RGB image."""
        return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

    def __call_fujishiro__(self, imgs):
        """
        imgs: list of cv2 (BGR) images
        """
        img = torch.stack(
            [self.tfms(self._to_pil(img)) for img in imgs], dim=0
        ).cuda()
        with torch.no_grad():
            age, gender, cloth_color = self.model(img)

            age_hist = F.softmax(age, dim=1)
            gender_hist = F.softmax(gender, dim=1)

            age_confs = age_hist.detach().cpu().numpy()
            age_idx = age_confs.argmax(axis=1)

            gender_confs = gender_hist.detach().cpu().numpy()
            gender_idx = gender_confs.argmax(axis=1)

            cloth_confs = cloth_color.detach().cpu().numpy()
            cloth_color_binary = cloth_confs > 0.5

        all_attributes = []
        for i, (a, g, c) in enumerate(zip(age_idx, gender_idx, cloth_color_binary)):
            attributes = {}
            attributes[self.model.age_class_names[a]] = age_confs[i][a]
            attributes[self.model.gender_class_names[g]] = gender_confs[i][g]

            for j, cc in enumerate(c):
                if cc:
                    attributes[self.model.color_class_names[j]] = cloth_confs[i][j]

            all_attributes.append(attributes)

        return all_attributes
