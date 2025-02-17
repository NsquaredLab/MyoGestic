import socket
import time
import pickle as pkl
from typing import Any

import numpy as np


def stream_to_udp(data_array: list[Any], ip: str, port: int, frequency : int | float) -> None:
    """
    Stream data from an array to a UDP port at a given frequency.

    Parameters
    ----------
    data_array : list
        List of data to stream. The elements of the list should be convertable to a utf-8 encoded string.
    ip : str
        IP address to stream to.
    port : int
        Port to stream to.
    frequency : int | float
        Frequency to stream at.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / frequency

    try:
        for data in data_array:
            message = str(data).encode('utf-8')
            sock.sendto(message, (ip, port))
            time.sleep(interval)
    finally:
        sock.close()

if __name__ == '__main__':
    # Example usage
    with open("/home/oj98yqyk/work/datasets/project_x_processed/SCI/003/datasets/results.pkl", "rb") as f:
        data = pkl.load(f)

        predictions = data["predictions"]
        ground_truth = data["ground_truths"][:, 0]

        predictions_temp = np.zeros((predictions.shape[-1], 9))
        predictions_temp[:, [0, 2, 3, 4, 5]] = predictions.T

        ground_truth_temp = np.zeros((ground_truth.shape[-1], 9))
        ground_truth_temp[:, [0, 2, 3, 4, 5]] = ground_truth.T

        data_array = [list(x) for x in np.concatenate((predictions_temp, ground_truth_temp), axis=-1)]

    ip = "127.0.0.1"
    port = 1236
    frequency = 32  # 1 Hz

    stream_to_udp(data_array, ip, port, frequency)