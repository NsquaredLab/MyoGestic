"""Functions to save, load, train and predict using RaulNet models."""
import multiprocessing
import platform
from pathlib import Path
from typing import Any

import lightning as L
import numpy as np
import torch
from lightning.pytorch.callbacks import ModelCheckpoint, StochasticWeightAveraging
from lightning.pytorch.loggers import CSVLogger
from myoverse.datasets import DataModule
from myoverse.transforms import Index

from myogestic.gui.widgets.logger import CustomLogger


def save(_: str, __: L.LightningModule) -> Path:
    """
    Return the path of the last saved RaulNet model checkpoint.

    Note: Saving is handled automatically by PyTorch Lightning.
    """
    checkpoints = sorted(
        Path("data/logs/RaulNet_models/").rglob("last.ckpt"),
        key=lambda x: int(x.parts[-3].split("_")[-1]),
    )
    return checkpoints[-1]


def save_per_finger(_: str, __: L.LightningModule) -> str:
    """
    Return the base path of the last saved per-finger RaulNet model checkpoints.

    Note: Saving is handled automatically by PyTorch Lightning.
    """
    model_dirs = sorted(
        Path("data/logs/RaulNet_models_per_finger/").glob("*_*"),
        key=lambda x: int(x.parts[-1].split("_")[0]),
    )
    parts = list(model_dirs[-1].parts)
    parts[-1] = parts[-1].split("_")[0]
    return str(Path(*parts))


def load(model_path: str, model: L.LightningModule) -> L.LightningModule:
    """
    Load a RaulNet model from checkpoint.

    Parameters
    ----------
    model_path : str
        The path to the checkpoint file.
    model : L.LightningModule
        A model instance used to determine the class for loading.

    Returns
    -------
    L.LightningModule
        The loaded RaulNet model in evaluation mode.
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    loaded_model = model.__class__.load_from_checkpoint(model_path)
    return loaded_model.to(device).eval().requires_grad_(False)


def load_per_finger(
    model_path: str, model: L.LightningModule
) -> list[L.LightningModule]:
    """
    Load per-finger RaulNet models from checkpoints.

    Parameters
    ----------
    model_path : str
        The base path for the per-finger model checkpoints.
    model : L.LightningModule
        A model instance used to determine the class for loading.

    Returns
    -------
    list[L.LightningModule]
        List of 3 loaded RaulNet models (one per finger).
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    models = []
    for i in range(3):
        checkpoint_path = list(Path(f"{model_path}_{i}").rglob("last.ckpt"))[0]
        loaded_model = model.__class__.load_from_checkpoint(checkpoint_path)
        models.append(loaded_model.to(device))
    return models


def _get_num_workers() -> int:
    """Get the number of workers for data loading based on platform."""
    if platform.system() == "Windows":
        return 0
    return multiprocessing.cpu_count() - 1


def _create_datamodule(
    zarr_path: Path, window_size: int, window_stride: int, target_transform=None
) -> DataModule:
    """Create a DataModule for training."""
    num_workers = _get_num_workers()
    return DataModule(
        data_path=zarr_path,
        inputs=["emg"],
        targets=["kinematics"],
        batch_size=64,
        window_size=window_size,
        window_stride=window_stride,
        num_workers=num_workers,
        pin_memory=True,
        persistent_workers=platform.system() != "Windows" and num_workers > 0,
        device="cuda" if torch.cuda.is_available() else None,
        target_transform=target_transform,
        cache_in_ram=True,
    )


def _create_trainer(logger_name: str, max_epochs: int, version: str | None = None) -> L.Trainer:
    """Create a Lightning Trainer with standard configuration."""
    return L.Trainer(
        accelerator="auto",
        devices=1,
        check_val_every_n_epoch=5,
        callbacks=[
            StochasticWeightAveraging(swa_lrs=1e-4, swa_epoch_start=0.5, annealing_epochs=5),
            ModelCheckpoint(monitor="val_loss", mode="min", save_top_k=1, save_last=True),
        ],
        precision="16-mixed",
        max_epochs=max_epochs,
        logger=CSVLogger(
            name=logger_name,
            save_dir=str(Path("data/logs/").resolve()),
            version=version,
        ),
        enable_checkpointing=True,
        enable_model_summary=True,
        deterministic=False,
    )


def train(
    model: L.LightningModule, dataset: dict, _: bool, __: CustomLogger
) -> L.LightningModule:
    """
    Train a RaulNet model.

    Parameters
    ----------
    model : L.LightningModule
        The RaulNet model to train.
    dataset : dict
        The dataset to train the model with.

    Returns
    -------
    L.LightningModule
        The trained RaulNet model.
    """
    torch.set_float32_matmul_precision("medium")
    torch.backends.cudnn.benchmark = True

    hparams = dict(model.hparams)
    hparams["input_length__samples"] = dataset["emg"].shape[-1]
    hparams["nr_of_electrodes_per_grid"] = dataset["emg"].shape[-2]
    hparams["nr_of_outputs"] = dataset["kinematics"].shape[-1]
    model = model.__class__(**hparams)

    zarr_path = Path("data/datasets") / dataset["zarr_file_path"]
    Path("data/logs/").mkdir(parents=True, exist_ok=True)

    loader = _create_datamodule(
        zarr_path,
        window_size=dataset["emg"].shape[-1],
        window_stride=dataset["device_information"]["samples_per_frame"],
    )
    trainer = _create_trainer("RaulNet_models", max_epochs=50)
    trainer.fit(model, datamodule=loader)

    return model


def _get_next_version_number(logs_dir: Path) -> int:
    """Get the next version number for per-finger models."""
    model_dirs = list(logs_dir.glob("*_*"))
    if not model_dirs:
        return 0
    sorted_dirs = sorted(model_dirs, key=lambda x: int(x.parts[-1].split("_")[0]))
    return int(sorted_dirs[-1].name.split("_")[0]) + 1


def train_per_finger(
    model: L.LightningModule, dataset: dict, _: bool, __: CustomLogger
) -> None:
    """
    Train separate RaulNet models for each finger.

    Parameters
    ----------
    model : L.LightningModule
        The RaulNet model template to train.
    dataset : dict
        The dataset to train the models with.
    """
    torch.set_float32_matmul_precision("medium")
    torch.backends.cudnn.benchmark = True

    Path("data/logs/").mkdir(parents=True, exist_ok=True)
    zarr_path = Path("data/datasets") / dataset["zarr_file_path"]
    version_nr = _get_next_version_number(Path("data/logs/RaulNet_models_per_finger/"))

    for i in range(3):
        hparams = dict(model.hparams)
        hparams["input_length__samples"] = dataset["emg"].shape[-1]
        finger_model = model.__class__(**hparams)

        target_transform = Index(indices=[i + 1], dim="joint")
        loader = _create_datamodule(
            zarr_path,
            window_size=dataset["emg"].shape[-1],
            window_stride=dataset["device_information"]["samples_per_frame"],
            target_transform=target_transform,
        )
        trainer = _create_trainer(
            "RaulNet_models_per_finger",
            max_epochs=20,
            version=f"{version_nr}_{i}",
        )
        trainer.fit(finger_model, datamodule=loader)


def predict(
    model: L.LightningModule, input_data: np.ndarray, is_classifier: bool
) -> list[Any] | None:
    """
    Predict with a RaulNet model.

    Parameters
    ----------
    model : L.LightningModule
        The RaulNet model to predict with.
    input_data : np.ndarray
        The input data with shape (n_features, n_samples).
    is_classifier : bool
        Whether the model is a classifier.

    Returns
    -------
    list[float] | None
        The predicted output, or None for classifiers.
    """
    if is_classifier:
        return None

    with torch.inference_mode():
        tensor_input = torch.from_numpy(input_data).float().to(model.device)[None, ...]
        output = model(tensor_input).cpu().numpy()[0]
        return list(output)


def predict_per_finger(
    models: list[L.LightningModule], input_data: np.ndarray, is_classifier: bool
) -> list[float] | None:
    """
    Predict with per-finger RaulNet models.

    Parameters
    ----------
    models : list[L.LightningModule]
        List of 3 RaulNet models (one per finger).
    input_data : np.ndarray
        The input data with shape (n_features, n_samples).
    is_classifier : bool
        Whether the models are classifiers.

    Returns
    -------
    list[float] | None
        Predictions padded with zeros at start and end, or None for classifiers.
    """
    if is_classifier:
        return None

    with torch.inference_mode():
        predictions = []
        for finger_model in models:
            tensor_input = torch.from_numpy(input_data).float().to(finger_model.device)[None, ...]
            predictions.append(finger_model(tensor_input))

        combined = torch.cat(predictions).cpu().numpy()[:, 0]
        return [0] + list(combined) + [0]
