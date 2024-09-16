from __future__ import annotations

import math
from typing import Any, TYPE_CHECKING

import numpy as np

from doc_octopy.datasets.filters.temporal import SOSFrequencyFilter
from doc_octopy.datasets.supervised import EMGDataset
from doc_octopy.datatypes import EMGData
from myogestic.gui.widgets.logger import LoggerLevel
from scipy.signal import butter

from myogestic.models.config import FEATURES_MAP

if TYPE_CHECKING:
    from myogestic.gui.widgets.logger import CustomLogger

from PySide6.QtCore import QObject


class MyogesticDataset(QObject):
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
        self, dataset: dict[str, dict], selected_features: list[str]
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

            task_label: int = self.task_to_class_map[task.lower()]

            recording_bad_channels = recording["bad_channels"]
            bad_channels.extend(recording_bad_channels)

            emg = recording["emg"]
            if len(recording_bad_channels) > 0:
                emg = np.delete(emg, recording_bad_channels, axis=0)

            if recording["use_kinematics"]:
                kinematics = recording["kinematics"]
                # TODO: Implement kinematics processing

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

                # kinematics = np.stack(
                #     [
                #         kinematics[..., i : i + self.buffer_size_samples]
                #         for i in range(
                #             0,
                #             kinematics.shape[-1] - self.buffer_size_samples,
                #             self.samples_per_frame,
                #         )
                #     ],
                #     axis=0,
                # )
                #
                # training_kinematics.append(kinematics.mean(axis=-1))

            else:
                ground_truth_data[task_label] = np.zeros((emg.shape[0], 9))

            emg_data[task_label] = emg
            # emg = np.stack(
            #     [
            #         emg[..., i : i + self.buffer_size_samples]
            #         for i in range(
            #             0,
            #             emg.shape[-1] - self.buffer_size_samples,
            #             self.samples_per_frame,
            #         )
            #     ],
            #     axis=0,
            # )[None, ...]
            #
            # emg = EMGDataset(emg_data=e
            #
            # emg = SOSFrequencyFilter(
            #     sos_filter_coefficients=butter(
            #         4,
            #         (47, 53),
            #         "bandstop",
            #         output="sos",
            #         fs=self.sampling_frequency,
            #     ),
            #     append_result_to_input=False,
            # )(emg)
            #
            # for feature in selected_features:
            #     training_data_emg[feature][task_label] = FEATURES_MAP[feature](
            #         window_size=self.buffer_size_samples
            #     )(emg)[0]
            #
            # # Create dataset for training
            # classes = (
            #     np.zeros(training_data_emg[feature][task_label].shape[0]) + task_label
            # )
            #
            # training_data_classes[task_label] = classes

        # training_x = np.concatenate(list(training_data_emg.values()), axis=0)

        dataset = EMGDataset(
            emg_data=emg_data,
            ground_truth_data=ground_truth_data,
            save_path="",
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
            emg_filter_pipeline_after_chunking=[[FEATURES_MAP[feature]] for feature in selected_features],
            emg_representations_to_filter_after_chunking=["Last"],
            ground_truth_filter_pipeline_before_chunking=[],
            ground_truth_representations_to_filter_before_chunking=["Input"],
            ground_truth_filter_pipeline_after_chunking=[],
            ground_truth_representations_to_filter_after_chunking=["Last"],
        )

        dataset.create_dataset()

        # training_means = {
        #     key: np.concatenate(list(training_data_emg[key].values()), axis=0).mean()
        #     for key in selected_features
        # }
        # training_stds = {
        #     key: np.concatenate(list(training_data_emg[key].values()), axis=0).std()
        #     for key in selected_features
        # }
        #
        # training_emg = {}
        #
        # task_group = {task: {} for task in training_data_classes.keys()}
        # for feature in training_data_emg.keys():
        #     for task in training_data_emg[feature].keys():
        #         task_group[task][feature] = training_data_emg[feature][task]
        #         task_group[task][feature] = (
        #             task_group[task][feature] - training_means[feature]
        #         ) / training_stds[feature]
        #
        # for task in task_group:
        #     temp = np.concatenate(list(task_group[task].values()), axis=-1)
        #     temp = temp.reshape(temp.shape[0], -1)
        #
        #     training_emg[task] = temp
        #
        # training_emg = np.concatenate(list(training_emg.values()), axis=0)
        # training_class = np.concatenate(list(training_data_classes.values()), axis=0)
        # training_kinematics = (
        #     np.concatenate(training_kinematics, axis=0)
        #     if len(training_kinematics) > 0
        #     else []
        # )

        return {
            "emg": training_emg,
            "classes": training_class,
            "kinematics": training_kinematics,
            "mean": training_means,
            "std": training_stds,
            "bad_channels": list(set(bad_channels)),
        }

    def preprocess_data(
        self, data: np.ndarray, bad_channels: list[int], selected_features
    ) -> np.ndarray:
        self.emg_buffer.append(data)
        if len(self.emg_buffer) > self.buffer_size:
            self.emg_buffer.pop(0)

            frame_data = np.concatenate(self.emg_buffer, axis=-1)[None, None]

            bad_channels = list(set(bad_channels + self.dataset_bad_channels))
            if len(bad_channels) > 0:
                frame_data = np.delete(frame_data, bad_channels, axis=2)

            frame_data = SOSFrequencyFilter(
                sos_filter_coefficients=butter(
                    4,
                    (47, 53),
                    "bandstop",
                    output="sos",
                    fs=self.sampling_frequency,
                ),
                append_result_to_input=False,
            )(frame_data)

            emg_concat = []
            for feature in selected_features:
                temp = FEATURES_MAP[feature](window_size=self.buffer_size_samples)(
                    frame_data
                )[0]

                temp = (temp - self.dataset_mean[feature]) / self.dataset_std[feature]

                emg_concat.append(temp)

            frame_data = np.concatenate(emg_concat, axis=-1)

            frame_data = frame_data.reshape(1, -1)

            return frame_data

    def set_online_parameters(self, dataset_information: dict) -> None:
        self.dataset_bad_channels = dataset_information["bad_channels"]
        self.dataset_mean = dataset_information["mean"]
        self.dataset_std = dataset_information["std"]
        self.emg_buffer: list[np.ndarray] = []
