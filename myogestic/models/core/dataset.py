from __future__ import annotations

import math
from pathlib import Path
from typing import Any, TYPE_CHECKING

import numpy as np
import zarr
from scipy.signal import butter

from doc_octopy.datasets.filters.generic import ApplyFunctionFilter, IndexDataFilter
from doc_octopy.datasets.filters.temporal import SOSFrequencyFilter
from doc_octopy.datasets.supervised import EMGDataset
from doc_octopy.datatypes import EMGData
from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.models.config import CONFIG_REGISTRY

if TYPE_CHECKING:
    from myogestic.gui.widgets.logger import CustomLogger

from PySide6.QtCore import QObject


def standardize_data(data: np.ndarray, mean: float, std: float) -> np.ndarray:
    return (data - mean) / std


class MyoGesticDataset(QObject):
    def __init__(
        self,
        device_information: dict[str, Any],
        logger: CustomLogger,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self.logger = logger

        self.task_to_class_map: dict[str, int] = {
            "rest": 0,
            "index": 1,
            "thumb": 2,
            "middle": 3,
            "ring": 4,
            "pinky": 5,
            "fist": 6,
            "pinch": 7,
            "3fpinch": 8,
            "pointing": 9,
        }

        self.device_information = device_information
        self.sampling_frequency: int = self.device_information["sampling_frequency"]
        self.samples_per_frame: int = self.device_information["samples_per_frame"]

        # Offline processing
        self.default_buffer_size_samples: int = 360
        self.buffer_size = math.ceil(
            self.default_buffer_size_samples / self.samples_per_frame
        )
        self.buffer_size_samples: int = self.buffer_size * self.samples_per_frame

        # Online processing
        self.emg_buffer: list[np.ndarray] = None
        self.dataset_bad_channels: list[int] = None
        self.dataset_mean: float = 0
        self.dataset_std: float = 1

    def create_dataset(
        self, dataset: dict[str, dict], selected_features: list[str], file_name: str
    ) -> dict:
        # Accumulate bad channels. Maybe more channels get added between recordings
        bad_channels: list[int] = []

        emg_data = {}
        ground_truth_data = {}
        for task, recording in dataset.items():
            if task.lower() not in self.task_to_class_map.keys():
                self.logger.print(
                    f"Task not recognized: {task.lower()}", LoggerLevel.WARNING
                )
                continue

            task_label: str = str(self.task_to_class_map[task.lower()])

            recording_bad_channels = recording["bad_channels"]
            bad_channels.extend(recording_bad_channels)

            emg = recording["emg"]
            if len(recording_bad_channels) > 0:
                emg = np.delete(emg, recording_bad_channels, axis=0)

            if recording["use_kinematics"]:
                kinematics = recording["kinematics"]
                # Upsample kinematics 60Hz to 2000 Hz
                kinematics = np.array(
                    [
                        np.interp(
                            np.linspace(0, 1, emg.shape[1]),
                            np.linspace(0, 1, kinematics.shape[1]),
                            k,
                        )
                        for k in kinematics
                    ]
                )

                ground_truth_data[task_label] = kinematics
            else:
                ground_truth_data[task_label] = np.zeros((9, emg.shape[-1]))

            emg_data[task_label] = emg

        emg_filter_pipeline_after_chunking = []
        for feature in selected_features:
            try:
                emg_filter_pipeline_after_chunking.append(
                    [
                        CONFIG_REGISTRY.features_map[feature](
                            is_output=True, window_size=self.buffer_size_samples  # noqa
                        )
                    ]
                )
            except TypeError:
                emg_filter_pipeline_after_chunking.append(
                    [CONFIG_REGISTRY.features_map[feature](is_output=True)]  # noqa
                )

        dataset = EMGDataset(
            emg_data=emg_data,
            ground_truth_data=ground_truth_data,
            ground_truth_data_type="virtual_hand",
            save_path=Path(f"data/datasets/{file_name}.zarr"),
            sampling_frequency=self.sampling_frequency,
            tasks_to_use=list(emg_data.keys()),
            chunk_size=self.buffer_size_samples,
            chunk_shift=self.samples_per_frame,
            emg_filter_pipeline_before_chunking=[
                [
                    SOSFrequencyFilter(
                        sos_filter_coefficients=butter(
                            4,
                            (47, 53),
                            "bandstop",
                            output="sos",
                            fs=self.sampling_frequency,
                        )
                    )
                ]
            ],
            emg_representations_to_filter_before_chunking=["Input"],
            emg_filter_pipeline_after_chunking=emg_filter_pipeline_after_chunking,
            emg_representations_to_filter_after_chunking=["EMG_Chunkizer"]
            * len(selected_features),
            ground_truth_filter_pipeline_before_chunking=[
                [IndexDataFilter(indices=((0, 2, 3, 4, 5),))]
            ],
            ground_truth_representations_to_filter_before_chunking=["Input"],
            ground_truth_filter_pipeline_after_chunking=[
                [ApplyFunctionFilter(is_output=True, function=np.mean, axis=-1)]
            ],
            ground_truth_representations_to_filter_after_chunking=["Last"],
        )

        dataset.create_dataset()

        dataset = zarr.open(f"data/datasets/{file_name}.zarr", mode="r")

        feature_keys = list(dataset["training"]["emg"])
        training_class = dataset["training"]["label"][:, 0].astype(int)
        training_kinematics = dataset["training"]["ground_truth"][
            "ApplyFunctionFilter"
        ][()]

        training_means = {}
        training_stds = {}
        training_emg = []

        for key in feature_keys:
            emg_per_key = dataset["training"]["emg"][key][()]

            training_means[key] = emg_per_key.mean()
            training_stds[key] = emg_per_key.std()
            training_emg.append(
                (emg_per_key - training_means[key]) / training_stds[key]
            )

        training_emg = np.concatenate(training_emg, axis=1)

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
            "zarr_file_path": file_name + ".zarr",
        }

    def preprocess_data(
        self, data: np.ndarray, bad_channels: list[int], selected_features
    ) -> np.ndarray:
        self.emg_buffer.append(data)
        if len(self.emg_buffer) > self.buffer_size:
            self.emg_buffer.pop(0)

            frame_data = np.concatenate(self.emg_buffer, axis=-1)[None]

            bad_channels = list(set(bad_channels + self.dataset_bad_channels))
            if len(bad_channels) > 0:
                frame_data = np.delete(frame_data, bad_channels, axis=2)

            frame_data = EMGData(
                input_data=frame_data,
                sampling_frequency=self.sampling_frequency,
            )

            frame_data.apply_filter(
                SOSFrequencyFilter(
                    sos_filter_coefficients=butter(
                        4,
                        (47, 53),
                        "bandstop",
                        output="sos",
                        fs=self.sampling_frequency,
                    ),
                    name="SOSFilter",
                ),
                representation_to_filter="Input",
            )

            emg_filters = []
            for feature in selected_features:
                try:
                    emg_filters.append(
                        CONFIG_REGISTRY.features_map[feature](
                            is_output=False,
                            window_size=self.buffer_size_samples,  # noqa
                        )
                    )
                except TypeError:
                    emg_filters.append(
                        CONFIG_REGISTRY.features_map[feature](is_output=False)
                    )  # noqa

            frame_data.apply_filter_pipeline(
                [
                    [
                        emg_filter,  # noqa
                        ApplyFunctionFilter(
                            is_output=True,
                            function=standardize_data,
                            mean=self.dataset_mean[feature],
                            std=self.dataset_std[feature],
                            name=feature,
                        ),
                    ]
                    for feature, emg_filter in zip(selected_features, emg_filters)
                ],
                representations_to_filter=["SOSFilter"] * len(selected_features),
            )

            frame_data = np.concatenate(
                [x for x in frame_data.output_representations.values()], axis=1
            )

            return frame_data

    def set_online_parameters(self, dataset_information: dict) -> None:
        self.dataset_bad_channels = dataset_information["bad_channels"]
        self.dataset_mean = dataset_information["mean"]
        self.dataset_std = dataset_information["std"]
        self.emg_buffer: list[np.ndarray] = []
