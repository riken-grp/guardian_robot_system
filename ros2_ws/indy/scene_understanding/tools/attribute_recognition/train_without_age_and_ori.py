from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from lightning.pytorch import LightningModule, Trainer
from lightning.pytorch.callbacks.early_stopping import EarlyStopping
from lightning.pytorch.loggers import WandbLogger
from scipy.io import loadmat
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader
from torchmetrics.classification import BinaryAccuracy
from torchvision.models import (EfficientNet_V2_S_Weights, Swin_V2_S_Weights,
                                VGG16_Weights, efficientnet_v2_s,
                                feature_extraction, swin_v2_s, vgg16)
from train import PA100KDataset


class MultilabelClassificationModel(LightningModule):
    def __init__(self, weights=None):
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

        self.indices = np.array([0] + list(range(7, 26)))
        if weights is not None:
            self.weights = self.get_binary_weights(weights[self.indices])
            self.weights = torch.Tensor(self.weights).cuda()
            self.loss = nn.BCELoss(reduction="none")
            self.weight_flag = True
        else:
            self.weight_flag = False
            self.loss = nn.BCELoss()
        self.metric = BinaryAccuracy()

    def get_binary_weights(self, weights):
        return 1 - weights / 80000

    def forward(self, x):
        with torch.no_grad():
            features = self.backbone(x)["flatten"]

        results = self.cls_head(features)
        return results

    def training_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self(x)

        y = y[:, self.indices].reshape(-1, 1)

        y_hat = y_hat.reshape(-1, 1)

        loss = self.loss(y_hat, y)
        if self.weight_flag:
            loss = loss.reshape(-1, len(self.indices))
            yr = y.reshape(-1, len(self.indices))
            weights = yr * self.weights + (1 - yr) * (1 - self.weights)
            loss = (loss * weights).mean()

        self.log("train_loss", loss, on_step=True, on_epoch=True, prog_bar=True)

        accuracy = self.metric(y_hat, y)
        self.log(
            "train_accuracy", accuracy, on_step=True, on_epoch=False, prog_bar=True
        )

        return loss

    def validation_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self(x)

        y = y[:, self.indices].reshape(-1, 1)
        y_hat = y_hat.reshape(-1, 1)

        loss = self.loss(y_hat, y)
        if self.weight_flag:
            loss = loss.reshape(-1, len(self.indices))
            yr = y.reshape(-1, len(self.indices))
            weights = yr * self.weights + (1 - yr) * (1 - self.weights)
            loss = (loss * weights).mean()

        self.log("val_loss", loss, on_step=False, on_epoch=True, prog_bar=True)

        accuracy = self.metric(y_hat, y)
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
