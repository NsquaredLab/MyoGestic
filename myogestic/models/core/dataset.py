from __future__ import annotations

import math
import pickle
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import torch
import zarr
from myoverse.datasets import DatasetCreator, Modality
from PySide6.QtCore import QObject
from scipy.signal import butter, sosfilt

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.user_config import (
    BUFFER_SIZE__CHUNKS,
    BUFFER_SIZE__SAMPLES,
    CHANNELS,
    GROUND_TRUTH_INDICES_TO_KEEP,
)
from myogestic.utils.config import CONFIG_REGISTRY

if TYPE_CHECKING:
    from myogestic.gui.widgets.logger import CustomLogger


class MyoGesticDataset(QObject):
    def __init__(
        self, device_information: dict[str, Any], logger: CustomLogger, parent
    ) -> None:
        super().__init__(parent)

        from myogestic.gui.myogestic import MyoGestic

        self._main_window: MyoGestic = parent

        self.logger = logger

        self.device_information = device_information
        self.sampling_frequency: int = self.device_information["sampling_frequency"]
        self.samples_per_frame: int = self.device_information["samples_per_frame"]

        # Offline processing buffer size
        if BUFFER_SIZE__SAMPLES == -1:
            self.buffer_size__chunks = BUFFER_SIZE__CHUNKS
        else:
            self.buffer_size__chunks = math.ceil(BUFFER_SIZE__SAMPLES / self.samples_per_frame)
        self.buffer_size__samples = self.buffer_size__chunks * self.samples_per_frame

        # Online processing state
        self.emg_buffer: list[np.ndarray] | None = None
        self.dataset_bad_channels: list[int] | None = None
        self.dataset_mean: dict[str, float] = {}
        self.dataset_std: dict[str, float] = {}

        # Store device for online preprocessing
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Precompute notch filter coefficients
        self._notch_sos = butter(
            4, (47, 53), "bandstop", output="sos", fs=self.sampling_frequency
        )

    def _create_feature_transform(self, feature_name: str):
        """Create a feature transform instance for the given feature name."""
        feature_cls = CONFIG_REGISTRY.features_map[feature_name]
        if feature_name == "Identity":
            return feature_cls()
        return feature_cls(window_size=self.buffer_size__samples)

    def _extract_feature_vector(self, feature_result: torch.Tensor) -> torch.Tensor:
        """Extract the feature vector from transform output, handling different shapes."""
        if feature_result.ndim == 1:
            return feature_result
        return feature_result[..., -1]

    def create_dataset(
        self,
        dataset: dict[str, dict],
        selected_features: list[str],
        file_name: str,
        recording_interface_from_recordings: str,
    ) -> dict:
        # Accumulate bad channels. Maybe more channels get added between recordings
        bad_channels: list[int] = []

        selected_interface = self._main_window.selected_visual_interface
        if selected_interface is None:
            interface_tuple = CONFIG_REGISTRY.visual_interfaces_map[
                recording_interface_from_recordings
            ]
            ground_truth__task_map = interface_tuple[1].ground_truth__task_map
            ground_truth__nr_of_recording_values = interface_tuple[1].ground_truth__nr_of_recording_values
        else:
            ground_truth__task_map = selected_interface.recording_interface_ui.ground_truth__task_map
            ground_truth__nr_of_recording_values = (
                selected_interface.recording_interface_ui.ground_truth__nr_of_recording_values
            )

            if selected_interface.name != recording_interface_from_recordings:
                self.logger.print(
                    f"Warning: The selected visual interface is not the same as the one used for recording. "
                    f"Using {recording_interface_from_recordings} instead of {selected_interface.name}.",
                    LoggerLevel.WARNING,
                )

        biosignal_data = {}
        ground_truth_data = {}
        for task, recording in dataset.items():
            if task.lower() not in ground_truth__task_map.keys():
                self.logger.print(
                    f"Task not recognized: {task.lower()}", LoggerLevel.WARNING
                )
                continue

            task_label: str = str(ground_truth__task_map[task.lower()])

            recording_bad_channels = recording["bad_channels"]
            bad_channels.extend(recording_bad_channels)

            biosignal = np.concatenate(recording["biosignal"][CHANNELS].T).T

            if recording_bad_channels:
                biosignal = np.delete(biosignal, recording_bad_channels, axis=0)

            if not recording["use_as_classification"]:
                ground_truth = recording["ground_truth"]
                ground_truth = np.array(
                    [
                        np.interp(
                            np.linspace(0, 1, biosignal.shape[1]),
                            np.linspace(0, 1, ground_truth.shape[1]),
                            k,
                        )
                        for k in ground_truth
                    ]
                )

                ground_truth_data[task_label] = ground_truth
            else:
                ground_truth_data[task_label] = np.zeros(
                    (
                        ground_truth__nr_of_recording_values,
                        biosignal.shape[-1],
                    )
                )

            biosignal_data[task_label] = biosignal

        # Determine ground truth indices to keep
        if GROUND_TRUTH_INDICES_TO_KEEP == "all":
            ground_truth_indices_to_keep = list(range(ground_truth__nr_of_recording_values))
        else:
            ground_truth_indices_to_keep = list(
                GROUND_TRUTH_INDICES_TO_KEEP[recording_interface_from_recordings]
            )

        # Filter ground truth to only keep selected indices
        for task_label in ground_truth_data:
            ground_truth_data[task_label] = ground_truth_data[task_label][
                ground_truth_indices_to_keep
            ]

        # Apply notch filter to biosignal data
        for task_label in biosignal_data:
            biosignal_data[task_label] = sosfilt(
                self._notch_sos, biosignal_data[task_label], axis=-1
            ).astype(np.float32)

        # Save temporary pickle files for DatasetCreator
        Path("data/datasets").mkdir(parents=True, exist_ok=True)
        emg_pkl_path = Path(f"data/datasets/{file_name}_emg.pkl")
        gt_pkl_path = Path(f"data/datasets/{file_name}_gt.pkl")

        with open(emg_pkl_path, "wb") as f:
            pickle.dump(biosignal_data, f)
        with open(gt_pkl_path, "wb") as f:
            pickle.dump(ground_truth_data, f)

        # Create dataset using MyoVerse v2 DatasetCreator
        save_path = Path(f"data/datasets/{file_name}.zip")
        creator = DatasetCreator(
            modalities={
                "emg": Modality(path=emg_pkl_path, dims=("channel", "time")),
                "kinematics": Modality(path=gt_pkl_path, dims=("joint", "time")),
            },
            sampling_frequency=float(self.sampling_frequency),
            tasks_to_use=list(biosignal_data.keys()),
            save_path=save_path,
            test_ratio=0.0,  # No test split for training datasets
            val_ratio=0.2,
            debug_level=1,
        )
        creator.create()

        # Clean up temporary pickle files
        emg_pkl_path.unlink()
        gt_pkl_path.unlink()

        # Open dataset to compute feature statistics
        store = zarr.open(zarr.storage.ZipStore(save_path, mode="r"), mode="r")

        # Compute features and their statistics for each task
        training_means = {feature: [] for feature in selected_features}
        training_stds = {feature: [] for feature in selected_features}
        all_emg_features = []
        all_kinematics = []
        all_classes = []

        for task_label in biosignal_data.keys():
            # Load raw EMG data
            emg_data = store["training"]["emg"][task_label][:]

            # Chunk the data into windows
            n_samples = emg_data.shape[-1]
            n_windows = (n_samples - self.buffer_size__samples) // self.samples_per_frame + 1

            task_features = []
            for feature_name in selected_features:
                feature_transform = self._create_feature_transform(feature_name)

                # Apply feature to each window
                windows_features = []
                for i in range(n_windows):
                    start_idx = i * self.samples_per_frame
                    end_idx = start_idx + self.buffer_size__samples
                    window = emg_data[..., start_idx:end_idx]

                    # Convert to tensor and apply transform
                    window_tensor = torch.from_numpy(window).float().rename("channel", "time")
                    feature_result = feature_transform(window_tensor)
                    feature_vec = self._extract_feature_vector(feature_result)
                    windows_features.append(feature_vec.rename(None).numpy())

                windows_features = np.stack(windows_features, axis=0)  # (n_windows, channels)
                task_features.append(windows_features)

            # Stack features: (n_windows, n_features * channels)
            task_features = np.concatenate(task_features, axis=-1)
            all_emg_features.append(task_features)

            # Get kinematics - average over each window
            kinematics = store["training"]["kinematics"][task_label][:]
            windows_kinematics = []
            for i in range(n_windows):
                start_idx = i * self.samples_per_frame
                end_idx = start_idx + self.buffer_size__samples
                window_kin = kinematics[..., start_idx:end_idx]
                windows_kinematics.append(np.mean(window_kin, axis=-1))
            windows_kinematics = np.stack(windows_kinematics, axis=0)
            all_kinematics.append(windows_kinematics)

            # Class labels
            all_classes.extend([int(task_label)] * n_windows)

        # Concatenate all tasks
        training_emg = np.concatenate(all_emg_features, axis=0)
        training_kinematics = np.concatenate(all_kinematics, axis=0)
        training_class = np.array(all_classes)

        # Compute mean and std per feature block
        n_channels = biosignal_data[list(biosignal_data.keys())[0]].shape[0]
        feature_start = 0
        for feature_name in selected_features:
            feature_end = feature_start + n_channels
            feature_data = training_emg[:, feature_start:feature_end]
            training_means[feature_name] = float(feature_data.mean())
            training_stds[feature_name] = float(feature_data.std())

            # Standardize this feature block
            training_emg[:, feature_start:feature_end] = (
                feature_data - training_means[feature_name]
            ) / training_stds[feature_name]

            feature_start = feature_end

        print("Dataset created")

        return {
            "emg": training_emg,
            "classes": training_class,
            "kinematics": training_kinematics,
            "mean": training_means,
            "std": training_stds,
            "bad_channels": list(set(bad_channels)),
            "selected_features": selected_features,
            "device_information": self.device_information,
            "visual_interface": recording_interface_from_recordings,
            "zarr_file_path": file_name + ".zip",
        }

    def preprocess_data(
        self, data: np.ndarray, bad_channels: list[int], selected_features: list[str]
    ) -> np.ndarray | None:
        """
        Preprocess incoming EMG data for real-time prediction.

        Uses GPU-accelerated TensorTransforms from MyoVerse v2.
        """
        self.emg_buffer.append(data[CHANNELS])
        if len(self.emg_buffer) > self.buffer_size__chunks:
            self.emg_buffer.pop(0)

            # Concatenate buffer
            frame_data = np.concatenate(self.emg_buffer, axis=-1)

            # Remove bad channels
            combined_bad_channels = list(set(bad_channels + self.dataset_bad_channels))
            if combined_bad_channels:
                frame_data = np.delete(frame_data, combined_bad_channels, axis=1)

            # Apply notch filter (numpy, on CPU)
            frame_data = sosfilt(self._notch_sos, frame_data, axis=-1)

            # Convert to tensor on device (GPU if available)
            frame_tensor = torch.from_numpy(frame_data.astype(np.float32)).to(
                self._device
            )
            frame_tensor = frame_tensor.rename("channel", "time")

            # Apply feature transforms
            all_features = []
            for feature_name in selected_features:
                feature_transform = self._create_feature_transform(feature_name)
                feature_result = feature_transform(frame_tensor)
                feature_vec = self._extract_feature_vector(feature_result)

                # Standardize
                mean = self.dataset_mean[feature_name]
                std = self.dataset_std[feature_name]
                feature_vec = (feature_vec - mean) / std

                all_features.append(feature_vec)

            # Stack features: (1, n_features * channels)
            result = torch.cat(all_features, dim=-1).unsqueeze(0)

            # Convert to numpy (move to CPU if needed)
            return result.rename(None).cpu().numpy()

        return None

    def set_online_parameters(self, dataset_information: dict) -> None:
        self.dataset_bad_channels = dataset_information["bad_channels"]
        self.dataset_mean = dataset_information["mean"]
        self.dataset_std = dataset_information["std"]
        self.emg_buffer: list[np.ndarray] = []
