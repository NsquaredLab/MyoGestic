import pickle
import numpy as np
import matplotlib.pyplot as plt


def main():
    with open(
        r"data\recordings\MindMove_Recording_20240530_115505896810_rest_default.pkl",
        "rb",
    ) as f:
        recording_rest = pickle.load(f)

    with open(
        r"data\recordings\MindMove_Recording_20240530_115522545011_fist_default.pkl",
        "rb",
    ) as f:
        recording_fist = pickle.load(f)
    print(recording_rest.keys())

    emg = recording_rest["emg"]
    emg_fist = recording_fist["emg"]
    norm = np.max([np.max(np.abs(emg)), np.max(np.abs(emg_fist))]) / 2
    emg /= norm
    emg_fist /= norm

    [
        plt.plot(channel + i, color="lightgrey", alpha=0.5)
        for i, channel in enumerate(emg_fist)
    ]
    [plt.plot(channel + i, color="red") for i, channel in enumerate(emg)]

    plt.show()


if __name__ == "__main__":
    main()
