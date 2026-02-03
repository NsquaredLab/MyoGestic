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
from myogestic.gui.widgets.logger import CustomLogger


from lightning.pytorch.callbacks import Callback


class GUIProgressCallback(Callback):
    """Callback to send training progress to GUI logger."""

    def __init__(self, gui_logger: CustomLogger | None = None):
        super().__init__()
        self.gui_logger = gui_logger

    def on_train_epoch_end(self, trainer: L.Trainer, pl_module: L.LightningModule) -> None:
        epoch = trainer.current_epoch
        max_epochs = trainer.max_epochs
        metrics = trainer.callback_metrics
        loss = metrics.get("train/loss", metrics.get("loss_epoch", 0))
        
        msg = f"Epoch {epoch + 1}/{max_epochs} - Loss: {loss:.6f}"
        if self.gui_logger:
            self.gui_logger.print(msg)
        else:
            print(msg)

    def on_train_start(self, trainer: L.Trainer, pl_module: L.LightningModule) -> None:
        if self.gui_logger:
            self.gui_logger.print(f"Training started (max {trainer.max_epochs} epochs)")

    def on_train_end(self, trainer: L.Trainer, pl_module: L.LightningModule) -> None:
        if self.gui_logger:
            self.gui_logger.print("Training completed!")


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
    # weights_only=False needed for PyTorch 2.6+ compatibility with Lightning checkpoints
    loaded_model = model.__class__.load_from_checkpoint(
        model_path, map_location=device, weights_only=False
    )
    return loaded_model.to(device).eval().requires_grad_(False)


def _get_num_workers() -> int:
    """Get the number of workers for data loading based on platform."""
    if platform.system() == "Windows":
        return 0
    return multiprocessing.cpu_count() - 1


class TrainOnlyDataModule(L.LightningDataModule):
    """DataModule for training with preprocessed numpy arrays.

    This DataModule accepts already feature-extracted EMG data and kinematics
    from the dataset creation process, avoiding the need to reload from zarr.
    """

    def __init__(
        self,
        emg_data: np.ndarray,
        kinematics_data: np.ndarray,
        batch_size: int = 64,
        num_workers: int = 0,
    ):
        """Initialize the DataModule with preprocessed data.

        Parameters
        ----------
        emg_data : np.ndarray
            Preprocessed EMG features with shape (n_samples, n_features * channels, time).
        kinematics_data : np.ndarray
            Target kinematics with shape (n_samples, n_outputs).
        batch_size : int
            Batch size for training. Default is 64.
        num_workers : int
            Number of workers for data loading. Default is 0.
        """
        super().__init__()
        self.emg_data = emg_data
        self.kinematics_data = kinematics_data
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.train_dataset = None

    def setup(self, stage: str | None = None) -> None:
        if stage == "fit" or stage is None:
            # Create a simple TensorDataset from the preprocessed arrays
            emg_tensor = torch.from_numpy(self.emg_data).float()
            kin_tensor = torch.from_numpy(self.kinematics_data).float()

            # Add input_channels dimension: (n_samples, features*channels, time) -> (n_samples, 1, features*channels, time)
            emg_tensor = emg_tensor.unsqueeze(1)

            self.train_dataset = torch.utils.data.TensorDataset(emg_tensor, kin_tensor)

    def train_dataloader(self):
        return torch.utils.data.DataLoader(
            self.train_dataset,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.num_workers,
            pin_memory=True,
            persistent_workers=platform.system() != "Windows" and self.num_workers > 0,
        )


def _create_datamodule(
    emg_data: np.ndarray,
    kinematics_data: np.ndarray,
    batch_size: int = 64,
) -> TrainOnlyDataModule:
    """Create a DataModule for training with preprocessed arrays.

    Parameters
    ----------
    emg_data : np.ndarray
        Preprocessed EMG features with shape (n_samples, n_features * channels, time).
    kinematics_data : np.ndarray
        Target kinematics with shape (n_samples, n_outputs).
    batch_size : int
        Batch size for training. Default is 64.

    Returns
    -------
    TrainOnlyDataModule
        DataModule ready for training.
    """
    num_workers = _get_num_workers()
    return TrainOnlyDataModule(
        emg_data=emg_data,
        kinematics_data=kinematics_data,
        batch_size=batch_size,
        num_workers=num_workers,
    )


def _create_trainer(
    logger_name: str,
    max_epochs: int,
    version: str | None = None,
    gui_logger: CustomLogger | None = None,
) -> L.Trainer:
    """Create a Lightning Trainer with standard configuration."""
    callbacks = [
        StochasticWeightAveraging(swa_lrs=1e-4, swa_epoch_start=0.5, annealing_epochs=5),
        ModelCheckpoint(monitor="train/loss", mode="min", save_top_k=1, save_last=True),
        GUIProgressCallback(gui_logger),
    ]
    
    return L.Trainer(
        accelerator="auto",
        devices=1,
        callbacks=callbacks,
        precision="16-mixed",
        max_epochs=max_epochs,
        logger=CSVLogger(
            name=logger_name,
            save_dir=str(Path("data/logs/").resolve()),
            version=version,
        ),
        enable_checkpointing=True,
        enable_model_summary=False,  # Disable summary output
        enable_progress_bar=False,  # Disable console progress bar
        deterministic=False,
    )


def train(
    model: L.LightningModule, dataset: dict, _: bool, gui_logger: CustomLogger
) -> L.LightningModule:
    """
    Train a RaulNet model using preprocessed features from the dataset.

    Parameters
    ----------
    model : L.LightningModule
        The RaulNet model to train.
    dataset : dict
        The dataset containing preprocessed EMG features and kinematics.
        Expected keys:
        - "emg": np.ndarray with shape (n_samples, n_features * channels, time)
        - "kinematics": np.ndarray with shape (n_samples, n_outputs)
        - "buffer_size__samples": int (used for model configuration)
    gui_logger : CustomLogger
        Logger for outputting training progress to the GUI.

    Returns
    -------
    L.LightningModule
        The trained RaulNet model.
    """
    torch.set_float32_matmul_precision("medium")
    torch.backends.cudnn.benchmark = True

    # Get preprocessed data from dataset
    emg_data = dataset["emg"]
    kinematics_data = dataset["kinematics"]

    # Configure model with correct input dimensions
    # emg_data shape: (n_samples, n_features * channels, time)
    hparams = dict(model.hparams)
    hparams["input_length__samples"] = emg_data.shape[-1]  # time dimension
    hparams["nr_of_electrodes_per_grid"] = emg_data.shape[-2]  # features * channels
    hparams["nr_of_outputs"] = kinematics_data.shape[-1]
    model = model.__class__(**hparams)

    Path("data/logs/").mkdir(parents=True, exist_ok=True)

    loader = _create_datamodule(emg_data, kinematics_data)
    trainer = _create_trainer("RaulNet_models", max_epochs=50, gui_logger=gui_logger)
    trainer.fit(model, datamodule=loader)

    return model


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
        The preprocessed input data with shape (1, n_features * channels, time).
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
        tensor_input = torch.from_numpy(input_data).float().to(model.device)
        # Add input_channels dimension: (batch, channels, time) -> (batch, 1, channels, time)
        # This matches the training data shape from TrainOnlyDataModule
        tensor_input = tensor_input.unsqueeze(1)
        output = model(tensor_input).cpu().numpy()[0]
        return list(output)
