import pickle

from myogestic.models.interface import MyoGesticModelInterface

device_information = {
    "sampling_frequency": 2048,
    "samples_per_frame": 64,
}
model_interface = MyoGesticModelInterface(device_information=device_information)
selected_recordings = {}
selected_dataset = {}


def _get_dict_from_recording(recording: str) -> dict:
    with open(recording, "rb") as f:
        data = pickle.load(f)
    return data


def _test_dataset_creation():
    recording_1 = _get_dict_from_recording(
        r"data\recordings\MindMove_Recording_20240526_165111343123_index_default.pkl"
    )
    recording_2 = _get_dict_from_recording(
        r"data\recordings\MindMove_Recording_20240526_165244773300_index_default.pkl"
    )
    selected_recordings[recording_1["task"]] = recording_1
    selected_recordings[recording_2["task"]] = recording_2

    selected_dataset = model_interface.create_dataset(dataset=selected_recordings)

    training_x = selected_dataset["x"]
    training_y = selected_dataset["y"]

    bad_channels = selected_dataset["bad_channels"]

    print("Training:", training_x.shape, training_y.shape)
    print("Bad channels:", bad_channels)


def _test_model_training(): ...


def main():
    _test_dataset_creation()
    _test_model_training()


if __name__ == "__main__":
    main()
