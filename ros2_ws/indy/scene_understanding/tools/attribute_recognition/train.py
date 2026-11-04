from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from lightning.pytorch import LightningModule, Trainer
from lightning.pytorch.callbacks.early_stopping import EarlyStopping
from lightning.pytorch.loggers import WandbLogger
from PIL import Image
from scipy.io import loadmat
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader, Dataset
from torchmetrics.classification import BinaryAccuracy, MulticlassAccuracy
from torchvision.models import (EfficientNet_V2_S_Weights, Swin_V2_S_Weights,
                                VGG16_Weights, efficientnet_v2_s,
                                feature_extraction, swin_v2_s, vgg16)
from torchvision.transforms import transforms


class Preprocess:
    def __init__(self, mode):
        image_size = 224

        t = [transforms.Resize(256)]

        if mode == "train":
            t.extend(
                [
                    transforms.RandomHorizontalFlip(),
                    transforms.RandomResizedCrop(
                        (image_size, image_size), scale=(0.88, 1.0)
                    ),
                    transforms.ColorJitter(
                        brightness=0.1, contrast=0.1, saturation=0.1
                    ),
                ]
            )
        else:
            t.append(transforms.CenterCrop((image_size, image_size)))
        t.extend(
            [
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
        self.tfms = transforms.Compose(t)

    def __call__(self, img):
        return self.tfms(img)


class PA100KDataset(Dataset):
    def __init__(self, basepath, annotations, mode="train"):
        self.basepath = basepath
        self.image_names = annotations[mode + "_images_name"]
        self.labels = annotations[mode + "_label"].astype(np.float32)
        self.attributes = annotations["attributes"]
        self.tfms = Preprocess(mode)

        self.num_ones = self.labels.sum(axis=0)

    def __len__(self):
        return len(self.image_names)

    def __getitem__(self, idx):
        img_name = (
            self.basepath
            / "release_data"
            / "release_data"
            / self.image_names[idx][0][0]
        )
        annos = self.labels[idx]

        i = Image.open(str(img_name))
        img = self.tfms(i)

        return img, annos


class MultilabelClassificationModel(LightningModule):

    def __init__(self, weights):
        super().__init__()
        # pretrained = efficientnet_v2_s(weights=EfficientNet_V2_S_Weights.IMAGENET1K_V1)  # 1280 dim
        pretrained = swin_v2_s(weights=Swin_V2_S_Weights.IMAGENET1K_V1)  # 768 dim
        # pretrained = vgg16(weights=VGG16_Weights.IMAGENET1K_V1)  # 25088 dim

        self.backbone = feature_extraction.create_feature_extractor(
            pretrained, ["flatten"]
        )

        # for param in self.backbone.parameters():
        #    param.requires_grad = False

        self.shared_head = nn.Sequential(
            nn.Linear(768, 256),
            nn.Dropout(0.5),
            nn.LeakyReLU(),
            nn.Linear(256, 256),
            nn.Dropout(0.5),
            nn.LeakyReLU(),
        )
        self.age_head = nn.Sequential(
            nn.Linear(256, 128),
            nn.Dropout(0.5),
            nn.LeakyReLU(),
            nn.Linear(128, 3),
            nn.Softmax(dim=1),
        )
        self.ori_head = nn.Sequential(
            nn.Linear(256, 128),
            nn.Dropout(0.5),
            nn.LeakyReLU(),
            nn.Linear(128, 3),
            nn.Softmax(dim=1),
        )
        self.cls_head = nn.Sequential(
            nn.Linear(256, 128),
            nn.Dropout(0.5),
            nn.LeakyReLU(),
            nn.Linear(128, 20),
            nn.Sigmoid(),
        )

        self.indices = np.array([0] + list(range(7, 26)))
        age_weights = self.get_multiclass_weights(weights[1:4])
        ori_weights = self.get_multiclass_weights(weights[4:7])
        self.weights = self.get_binary_weights(weights[self.indices])
        self.weights = torch.Tensor(self.weights).cuda()

        self.loss = nn.BCELoss(reduction="none")
        self.age_cross_entropy = nn.CrossEntropyLoss(weight=torch.Tensor(age_weights))
        self.ori_cross_entropy = nn.CrossEntropyLoss(weight=torch.Tensor(ori_weights))
        self.metric = BinaryAccuracy()
        self.age_metric = MulticlassAccuracy(3)
        self.ori_metric = MulticlassAccuracy(3)

    def get_multiclass_weights(self, weights):
        return 1 - (weights / weights.sum())

    def get_binary_weights(self, weights):
        return 1 - weights / 80000

    def forward(self, x):
        with torch.no_grad():
            features = self.backbone(x)["flatten"]

        features = self.shared_head(features)
        age_results = self.age_head(features)
        ori_results = self.ori_head(features)
        results = self.cls_head(features)
        return age_results, ori_results, results

    def training_step(self, batch, batch_idx):
        x, y = batch
        y_age_hat, y_ori_hat, y_hat = self(x)

        y_age = y[:, 1:4]
        y_ori = y[:, 4:7]
        y = y[:, self.indices].reshape(-1, 1)

        y_hat = y_hat.reshape(-1, 1)

        age_loss = self.age_cross_entropy(y_age_hat, y_age)
        ori_loss = self.ori_cross_entropy(y_ori_hat, y_ori)

        other_losses = self.loss(y_hat, y)
        other_losses = other_losses.reshape(-1, len(self.indices))
        yr = y.reshape(-1, len(self.indices))
        weights = yr * self.weights + (1 - yr) * (1 - self.weights)
        other_loss = (other_losses * weights).mean()

        loss = age_loss + ori_loss + other_loss
        self.log("train_age_loss", age_loss, on_step=True, on_epoch=True, prog_bar=True)
        self.log("train_ori_loss", ori_loss, on_step=True, on_epoch=True, prog_bar=True)
        self.log("train_loss", loss, on_step=True, on_epoch=True, prog_bar=True)

        accuracy = self.metric(y_hat, y)
        age_accuracy = self.age_metric(y_age_hat, y_age)
        ori_accuracy = self.ori_metric(y_ori_hat, y_ori)
        self.log(
            "train_age_accuracy",
            age_accuracy,
            on_step=True,
            on_epoch=False,
            prog_bar=True,
        )
        self.log(
            "train_ori_accuracy",
            ori_accuracy,
            on_step=True,
            on_epoch=False,
            prog_bar=True,
        )
        self.log(
            "train_accuracy", accuracy, on_step=True, on_epoch=False, prog_bar=True
        )

        return loss

    def validation_step(self, batch, batch_idx):
        x, y = batch
        y_age_hat, y_ori_hat, y_hat = self(x)

        y_age = y[:, 1:4]
        y_ori = y[:, 4:7]
        y = y[:, self.indices].reshape(-1, 1)
        y_hat = y_hat.reshape(-1, 1)

        age_loss = self.age_cross_entropy(y_age_hat, y_age)
        ori_loss = self.ori_cross_entropy(y_ori_hat, y_ori)

        other_losses = self.loss(y_hat, y)
        other_losses = other_losses.reshape(-1, len(self.indices))
        yr = y.reshape(-1, len(self.indices))
        weights = yr * self.weights + (1 - yr) * (1 - self.weights)
        other_loss = (other_losses * weights).mean()

        loss = age_loss + ori_loss + other_loss
        self.log("val_age_loss", age_loss, on_step=False, on_epoch=True, prog_bar=True)
        self.log("val_ori_loss", ori_loss, on_step=False, on_epoch=True, prog_bar=True)
        self.log("val_loss", loss, on_step=False, on_epoch=True, prog_bar=True)

        accuracy = self.metric(y_hat, y)
        age_accuracy = self.age_metric(y_age_hat, y_age)
        ori_accuracy = self.ori_metric(y_ori_hat, y_ori)
        self.log(
            "val_age_accuracy",
            age_accuracy,
            on_step=False,
            on_epoch=True,
            prog_bar=True,
        )
        self.log(
            "val_ori_accuracy",
            ori_accuracy,
            on_step=False,
            on_epoch=True,
            prog_bar=True,
        )
        self.log("val_accuracy", accuracy, on_step=False, on_epoch=True, prog_bar=True)

    def configure_optimizers(self):
        optimizer = optim.Adam(self.parameters(), lr=0.001)
        scheduler = ReduceLROnPlateau(optimizer, mode="min", patience=10)
        return {
            "optimizer": optimizer,
            "lr_scheduler": scheduler,
            "monitor": "val_loss",
        }


def main():
    dataset_basepath = Path("/mnt/share/PublicDataset/PA-100K")

    annotations = loadmat(str(dataset_basepath / "annotation.mat"))

    dataset = PA100KDataset(dataset_basepath, annotations, mode="train")
    val_dataset = PA100KDataset(dataset_basepath, annotations, mode="val")
    # test_dataset = PA100KDataset(dataset_basepath, annotations, mode="test")

    data_loader = DataLoader(dataset, batch_size=256, shuffle=True, num_workers=24)
    val_loader = DataLoader(val_dataset, batch_size=256, shuffle=False, num_workers=24)
    # test_loader = DataLoader(test_dataset, batch_size=1024, shuffle=False, num_workers=24)

    model = MultilabelClassificationModel(weights=dataset.num_ones)

    wandb_logger = WandbLogger()
    trainer = Trainer(
        max_epochs=1000,
        callbacks=[EarlyStopping(monitor="val_loss", mode="min", patience=20)],
        logger=wandb_logger,
    )
    trainer.fit(model, data_loader, val_loader)

    torch.save(model.state_dict(), "trained_model.pth")


if __name__ == "__main__":
    main()
