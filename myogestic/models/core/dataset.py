from __future__ import annotations

import math
from pathlib import Path
from typing import Any, TYPE_CHECKING

import numpy as np
import zarr
from myoverse.datasets.filters.generic import ApplyFunctionFilter, IndexDataFilter
from myoverse.datasets.filters.temporal import SOSFrequencyFilter
from myoverse.datasets.supervised import EMGDataset
from myoverse.datatypes import EMGData
from scipy.signal import butter

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.utils.config import CONFIG_REGISTRY

if TYPE_CHECKING:
    from myogestic.gui.widgets.logger import CustomLogger

from PySide6.QtCore import QObject

from myogestic.user_config import (
    CHANNELS,
    BUFFER_SIZE__CHUNKS,
    BUFFER_SIZE__SAMPLES,
    GROUND_TRUTH_INDICES_TO_KEEP,
)


def standardize_data(data: np.ndarray, mean: float, std: float) -> np.ndarray:
    return (data - mean) / std


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

        # Offline processing
        self.buffer_size__chunks: int = (
            BUFFER_SIZE__CHUNKS
            if BUFFER_SIZE__SAMPLES == -1
            else math.ceil(BUFFER_SIZE__SAMPLES / self.samples_per_frame)
        )
        self.buffer_size__samples: int = (
            self.buffer_size__chunks * self.samples_per_frame
        )

        # Online processing
        self.emg_buffer: list[np.ndarray] | None = None
        self.dataset_bad_channels: list[int] | None = None
        self.dataset_mean: float = 0.0
        self.dataset_std: float = 1.0

    def create_dataset(
        self, dataset: dict[str, dict], selected_features: list[str], file_name: str, recording_interface_from_recordings: str
    ) -> dict:
        # Accumulate bad channels. Maybe more channels get added between recordings
        bad_channels: list[int] = []

        if self._main_window.selected_visual_interface is None:
            visual_interface_to_use=CONFIG_REGISTRY.visual_interfaces_map[recording_interface_from_recordings]
            ground_truth__task_map=visual_interface_to_use[1].ground_truth__task_map
            ground_truth__nr_of_recording_values=visual_interface_to_use[1].ground_truth__nr_of_recording_values
        else:
            visual_interface_to_use = self._main_window.selected_visual_interface
            ground_truth__task_map = visual_interface_to_use.recording_interface_ui.ground_truth__task_map
            ground_truth__nr_of_recording_values = visual_interface_to_use.recording_interface_ui.ground_truth__nr_of_recording_values

            if visual_interface_to_use.name != recording_interface_from_recordings:
                self.logger.print(
                    f"Warning: The selected visual interface is not the same as the one used for recording. "
                    f"Using {recording_interface_from_recordings} instead of {visual_interface_to_use.name}.",
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

            if len(recording_bad_channels) > 0:
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

        biosignal_filter_pipeline_after_chunking = []
        for feature in selected_features:
            temp = [
                SOSFrequencyFilter(
                    sos_filter_coefficients=butter(
                        4,
                        (47, 53),
                        "bandstop",
                        output="sos",
                        fs=self.sampling_frequency,
                    ),
                    input_is_chunked=True,
                    forwards_and_backwards=False,
                )
            ]
            try:
                temp.append(
                    CONFIG_REGISTRY.features_map[feature](
                        is_output=True,
                        window_size=self.buffer_size__samples,  # noqa
                        input_is_chunked=True,
                    )
                )
            except TypeError:
                temp.append(
                    CONFIG_REGISTRY.features_map[feature](
                        is_output=True, input_is_chunked=True
                    )
                )

            biosignal_filter_pipeline_after_chunking.append(temp)

        ground_truth_indices_to_keep = (
            tuple(
                np.arange(
                    self._main_window.selected_visual_interface.recording_interface_ui.ground_truth__nr_of_recording_values
                )
            )
            if GROUND_TRUTH_INDICES_TO_KEEP == "all"
            else tuple(GROUND_TRUTH_INDICES_TO_KEEP[recording_interface_from_recordings])
        )

        dataset = EMGDataset(
            emg_data=biosignal_data,
            ground_truth_data=ground_truth_data,
            ground_truth_data_type="virtual_hand",
            save_path=Path(f"data/datasets/{file_name}.zarr"),
            sampling_frequency=self.sampling_frequency,
            tasks_to_use=list(biosignal_data.keys()),
            chunk_size=self.buffer_size__samples,
            chunk_shift=self.samples_per_frame,
            emg_filter_pipeline_after_chunking=biosignal_filter_pipeline_after_chunking,
            emg_representations_to_filter_after_chunking=[["EMG_Chunkizer"]]
            * len(selected_features),
            ground_truth_filter_pipeline_before_chunking=[
                [
                    IndexDataFilter(
                        indices=(ground_truth_indices_to_keep,), input_is_chunked=False
                    )
                ]
            ],
            ground_truth_representations_to_filter_before_chunking=[["Input"]],
            ground_truth_filter_pipeline_after_chunking=[
                [
                    ApplyFunctionFilter(
                        is_output=True, function=np.mean, axis=-1, input_is_chunked=True
                    )
                ]
            ],
            ground_truth_representations_to_filter_after_chunking=[["Last"]],
            debug_level=1,
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

            training_means[key], training_stds[key] = (
                emg_per_key.mean(),
                emg_per_key.std(),
            )
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
            "visual_interface": recording_interface_from_recordings,
            "zarr_file_path": file_name + ".zarr",
        }

    def preprocess_data(
        self, data: np.ndarray, bad_channels: list[int], selected_features
    ) -> np.ndarray:
        self.emg_buffer.append(data[CHANNELS])
        if len(self.emg_buffer) > self.buffer_size__chunks:
            self.emg_buffer.pop(0)

            frame_data = np.concatenate(self.emg_buffer, axis=-1)[None]

            bad_channels = list(set(bad_channels + self.dataset_bad_channels))
            if len(bad_channels) > 0:
                frame_data = np.delete(frame_data, bad_channels, axis=2)

            frame_data = EMGData(
                input_data=frame_data, sampling_frequency=self.sampling_frequency
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
                    forwards_and_backwards=False,
                    input_is_chunked=False,
                ),
                representations_to_filter=["Input"],
            )

            emg_filters = []
            for feature in selected_features:
                try:
                    emg_filters.append(
                        CONFIG_REGISTRY.features_map[feature](
                            is_output=False,
                            window_size=self.buffer_size__samples,
                            input_is_chunked=False,
                        )
                    )
                except TypeError:
                    emg_filters.append(
                        CONFIG_REGISTRY.features_map[feature](is_output=False, input_is_chunked=False)
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
                            input_is_chunked=False,
                        ),
                    ]
                    for feature, emg_filter in zip(selected_features, emg_filters)
                ],
                representations_to_filter=[["SOSFilter"] * len(selected_features)],
            )

            frame_data = np.concatenate(
                [x for x in frame_data.output_representations.values()], axis=1
            )

            return frame_data
        return None

    def set_online_parameters(self, dataset_information: dict) -> None:
        self.dataset_bad_channels = dataset_information["bad_channels"]
        self.dataset_mean = dataset_information["mean"]
        self.dataset_std = dataset_information["std"]
        self.emg_buffer: list[np.ndarray] = []
