"""
This module contains the functions to save, load, train and predict using RaulNet models.
"""

from pathlib import Path
from typing import Any

import lightning as L
import numpy as np
import torch
from lightning.pytorch.callbacks import StochasticWeightAveraging, ModelCheckpoint
from lightning.pytorch.loggers import CSVLogger
from myoverse.datasets.filters.generic import IndexDataFilter
from myoverse.datasets.loader import EMGDatasetLoader
from myoverse.datatypes import _Data

from myogestic.gui.widgets.logger import CustomLogger


def save(_: str, __: L.LightningModule) -> str:
    """
    Save a RaulNet model.

    .. note:: Saving the model is not necessary as the model is saved automatically by PyTorch Lightning. This function only returns the path of the last saved model.

    Parameters
    ----------
    _: str
        The path to save the model.
    __: L.LightningModule
    The RaulNet model to save.

    Returns
    -------
    str
        The path where the model was saved.

    """
    return sorted(
        list(Path("data/logs/RaulNet_models/").rglob("last.ckpt")),
        key=lambda x: int(x.parts[-3].split("_")[-1]),
    )[-1]


def save_per_finger(_: str, __: L.LightningModule) -> str:
    """
    Save a RaulNet model.

    .. note:: Saving the model is not necessary as the model is saved automatically by PyTorch Lightning. This function only returns the path of the last saved model.

    Parameters
    ----------
    _: str
        The path to save the model.
    __: L.LightningModule
    The RaulNet model to save.

    Returns
    -------
    str
        The path where the model was saved.

    """
    parts = list(
        sorted(
            list(Path("data/logs/RaulNet_models_per_finger/").glob("*_*")),
            key=lambda x: int(x.parts[-1].split("_")[0]),
        )[-1].parts
    )
    parts[-1] = parts[-1].split("_")[0]

    return str(Path(*parts))


def load(model_path: str, model: L.LightningModule) -> L.LightningModule:
    """
    load a RaulNet model.

    Parameters
    ----------
    model_path: str
        The path to load the model.
    model: _CatBoostBase
        A new instance of the CatBoost model. This instance is used to load the model.

    Returns
    -------
    _CatBoostBase
        The loaded RaulNet model.

    """
    return model.__class__.load_from_checkpoint(model_path).to(
        "cuda" if torch.cuda.is_available() else "cpu"
    ).eval().requires_grad_(False)


def load_per_finger(
    model_path: str, model: L.LightningModule
) -> list[L.LightningModule]:
    """
    load a RaulNet model.

    Parameters
    ----------
    model_path: str
        The path to load the model.
    model: L.LightningModule
        A new instance of the CatBoost model. This instance is used to load the model.

    Returns
    -------
    L.LightningModule
        The loaded RaulNet model.

    """

    return [
        model.__class__.load_from_checkpoint(
            list(Path(model_path + f"_{i}").rglob("last.ckpt"))[0]
        ).to("cuda" if torch.cuda.is_available() else "cpu")
        for i in range(3)
    ]


def train(
    model: L.LightningModule, dataset, _: bool, __: CustomLogger
) -> L.LightningModule:
    """
    Train a RaulNet model.

    Parameters
    ----------
    model: L.LightningModule
        The RaulNet model to train.
    dataset: dict
        The dataset to train the model with.
    _: bool
        If the model is a classifier.
    __: CustomLogger
        The logger to log the training process.

    Returns
    -------
    L.LightningModule
        The trained RaulNet model.

    """
    torch.set_float32_matmul_precision("medium")

    torch.backends.cudnn.benchmark = True

    hparams = model.hparams
    hparams["input_length__samples"] = dataset["emg"].shape[-1]
    hparams["nr_of_electrodes_per_grid"] = dataset["emg"].shape[-2]
    hparams["nr_of_outputs"] = dataset["kinematics"].shape[-1]

    model = model.__class__(**hparams)

    class CustomDataClass(_Data):
        def __init__(
            self,
            raw_data,
            sampling_frequency=dataset["device_information"]["sampling_frequency"],
        ):
            # Initialize parent class with raw data
            super().__init__(
                raw_data.reshape(1, -1),
                sampling_frequency,
                nr_of_dimensions_when_unchunked=2,
            )

    loader = EMGDatasetLoader(
        Path(r"data/datasets/" + dataset["zarr_file_path"]).resolve(),
        target_data_class=CustomDataClass,
        dataloader_params={
            "batch_size": 64,
            "drop_last": True,
            "num_workers": 10,
            "pin_memory": True,
            "persistent_workers": True,
        },
    )

    Path("data/logs/").mkdir(parents=True, exist_ok=True)

    trainer = L.Trainer(
        accelerator="auto",
        devices=1,
        check_val_every_n_epoch=5,
        callbacks=[
            StochasticWeightAveraging(
                swa_lrs=10 ** (-4), swa_epoch_start=0.5, annealing_epochs=5
            ),
            ModelCheckpoint(
                monitor="val_loss", mode="min", save_top_k=1, save_last=True
            ),
        ],
        precision="16-mixed",
        max_epochs=50,
        logger=CSVLogger(
            name="RaulNet_models", save_dir=str(Path(r"data/logs/").resolve())
        ),
        enable_checkpointing=True,
        enable_model_summary=True,
        deterministic=False,
    )

    trainer.fit(model, datamodule=loader)

    return model


def train_per_finger(model: L.LightningModule, dataset, _: bool, __: CustomLogger):
    """
    Train a RaulNet model.

    Parameters
    ----------
    model: L.LightningModule
        The RaulNet model to train.
    dataset: dict
        The dataset to train the model with.
    _: bool
        If the model is a classifier.
    __: CustomLogger
        The logger to log the training process.

    Returns
    -------
    L.LightningModule
        The trained RaulNet model.

    """
    torch.set_float32_matmul_precision("medium")
    torch.backends.cudnn.benchmark = True

    Path("data/logs/").mkdir(parents=True, exist_ok=True)

    # find the latest version of the models
    try:
        version_nr = (
            int(
                sorted(
                    list(Path("data/logs/RaulNet_models_per_finger/").glob("*_*")),
                    key=lambda x: int(x.parts[-1].split("_")[0]),
                )[-1].name.split("_")[0]
            )
            + 1
        )
    except Exception:
        version_nr = 0

    for i in range(3):
        hparams = model.hparams
        hparams["input_length__samples"] = dataset["emg"].shape[-1]

        model = model.__class__(**hparams)

        class CustomDataClass(_Data):
            def __init__(
                self,
                raw_data,
                sampling_frequency=dataset["device_information"]["sampling_frequency"],
            ):
                # Initialize parent class with raw data
                super().__init__(
                    raw_data.reshape(1, -1),
                    sampling_frequency,
                    nr_of_dimensions_when_unchunked=2,
                )

        loader = EMGDatasetLoader(
            Path(r"data/datasets/" + dataset["zarr_file_path"]).resolve(),
            target_data_class=CustomDataClass,
            dataloader_params={
                "batch_size": 64,
                "drop_last": True,
                "num_workers": 10,
                "pin_memory": True,
                "persistent_workers": True,
            },
            target_augmentation_pipeline=[
                [
                    IndexDataFilter(
                        indices=(0, [i + 1]), is_output=True, input_is_chunked=False
                    )
                ]
            ],
        )

        trainer = L.Trainer(
            accelerator="auto",
            devices=1,
            check_val_every_n_epoch=5,
            callbacks=[
                StochasticWeightAveraging(
                    swa_lrs=10 ** (-4), swa_epoch_start=0.5, annealing_epochs=5
                ),
                ModelCheckpoint(
                    monitor="val_loss", mode="min", save_top_k=1, save_last=True
                ),
            ],
            precision="16-mixed",
            max_epochs=20,
            logger=CSVLogger(
                name="RaulNet_models_per_finger",
                save_dir=str(Path(r"data/logs/").resolve()),
                version=f"{version_nr}_{i}",
            ),
            enable_checkpointing=True,
            enable_model_summary=True,
            deterministic=False,
        )

        trainer.fit(model, datamodule=loader)

    return


def predict(
    model: L.LightningModule, input: np.ndarray, is_classifier: bool
) -> list[Any] | None:
    """
    Predict with a RaulNet model.

    Parameters
    ----------
    model: L.LightningModule
        The RaulNet model to predict with.
    input: np.ndarray
        The input data to predict. The shape of the input data will be (1, n_features, n_samples).
    is_classifier
        If the model is a classifier.

    Returns
    -------
    list[float]
        The predicted output.

    """
    if not is_classifier:
        with torch.inference_mode():
            return list(
                model(
                    torch.from_numpy(input)
                    .to(torch.float32)
                    .to(model.device)[None, ...]
                )
                .detach()
                .cpu()
                .numpy()[0]
            )
    return None


def predict_per_finger(
    model: list[L.LightningModule], input: np.ndarray, is_classifier: bool
) -> list[int] | None:
    """
    Predict with a RaulNet model.

    Parameters
    ----------
    model: list[L.LightningModule]
        The RaulNet model to predict with.
    input: np.ndarray
        The input data to predict. The shape of the input data will be (1, n_features, n_samples).
    is_classifier
        If the model is a classifier.

    Returns
    -------
    list[float]
        The predicted output.

    """
    if not is_classifier:
        with torch.inference_mode():
            return (
                [0]
                + list(
                    torch.concatenate(
                        [
                            model[i](
                                torch.from_numpy(input)
                                .to(torch.float32)
                                .to(model[i].device)[None, ...]
                            )
                            for i in range(3)
                        ]
                    )
                    .detach()
                    .cpu()
                    .numpy()[:, 0]
                )
                + [0]
            )
    return None
