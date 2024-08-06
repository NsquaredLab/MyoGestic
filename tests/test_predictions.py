import pickle
import numpy as np
import matplotlib.pyplot as plt


def main():
    with open(
        r"data\predictions\MyoGestic_Prediction_20240530_122703431948_default.pkl",
        "rb",
    ) as f:
        prediction = pickle.load(f)

    print(prediction.keys())

    emg = prediction["emg"]
    print(emg.max())

    model_information = prediction["model_information"]
    print(model_information)
    print(prediction["bad_channels"])

    [plt.plot(channel + i, color="gray") for i, channel in enumerate(emg)]

    predictions = prediction["predictions"]
    plt.figure()
    plt.plot(predictions)

    plt.show()


if __name__ == "__main__":
    main()
