import pickle
import numpy as np
import matplotlib.pyplot as plt

from myogestic.models.interface import MyogesticModelInterface


def main():
    device_information = {"sampling_frequency": 2000, "samples_per_frame": 18}
    model_interface = MyogesticModelInterface(device_information)
    recordings = [
        r"data\recordings\MindMove_Recording_20240530_115505896810_rest_default.pkl",
        r"data\recordings\MindMove_Recording_20240530_115522545011_fist_default.pkl",
    ]

    recordings_data = {}
    for recording in recordings:
        with open(recording, "rb") as f:
            rec = pickle.load(f)
            recordings_data[rec["task"]] = rec

    dataset = model_interface.create_dataset(recordings_data)
    dataset["epochs"] = 1000

    model = model_interface.train_model(dataset)

    model_interface.save_model("tests/models.cbm")
    with open("tests/models.pkl", "wb") as f:
        pickle.dump(dataset, f)

    model_interface.load_model("tests/models.cbm")
    with open(
        r"data\predictions\MyoGestic_Prediction_20240530_122703431948_default.pkl",
        "rb",
    ) as f:
        prediction = pickle.load(f)

    emg = prediction["emg"]

    # Slice emg into windows of 18 samples
    emg_windows = np.array([emg[:, i : i + 18] for i in range(0, emg.shape[1], 18)])

    for window in emg_windows:
        prediction = model_interface.predict(window)
        print(prediction)


if __name__ == "__main__":
    main()
