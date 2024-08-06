import pickle
import numpy as np
import matplotlib.pyplot as plt


def main():
    with open(
        "data\datasets\MindMove_Dataset_20240530_115538305280_default.pkl", "rb"
    ) as f:
        dataset = pickle.load(f)
    print(dataset.keys())
    training_x: np.ndarray = dataset["x"]
    training_y: np.ndarray = dataset["y"]

    plt.plot(training_x)
    plt.plot(training_y)
    plt.show()


if __name__ == "__main__":
    main()
