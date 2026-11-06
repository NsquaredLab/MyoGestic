"""The file-name standard: <ID>_<YYYYMMDD-HHMM>_<what>.mg.zip, with class codes."""

import json
import zipfile

import numpy as np
import pytest

from myogestic.session import Session, class_codes
from myogestic.stream import StreamInfo
from myogestic.widgets.training._session_state import packed_session_path, scan_sessions

KAPPA = ["Rest", "Thumb", "Index", "Middle", "Ring", "Little", "Fist"]
GALVANI = [
    "Rest",
    "Fist",
    "Pinch",
    "Three-Finger-Pinch",
    "Thumb-Flex",
    "Index-Flex",
    "Middle-Flex",
    "Ring-Flex",
    "Pinky-Flex",
]


def test_codes_take_one_letter_and_more_only_where_two_clash():
    assert class_codes(KAPPA) == {
        "Rest": "Re",
        "Thumb": "T",
        "Index": "I",
        "Middle": "M",
        "Ring": "Ri",
        "Little": "L",
        "Fist": "F",
    }
    assert class_codes(GALVANI) == dict(
        zip(GALVANI, ["R", "F", "P", "Tfp", "Tf", "If", "Mf", "Rf", "Pf"], strict=True)
    )
    assert class_codes(["Pinch", "Pinky"]) == {"Pinch": "Pinc", "Pinky": "Pink"}


def test_pinned_codes_win_and_the_rest_work_around_them():
    codes = class_codes(["Rest", "Ring", "Fist"], {"Rest": "R"})
    assert codes == {"Rest": "R", "Ring": "Ri", "Fist": "F"}


@pytest.mark.parametrize("pinned", [{"Rest": "R+"}, {"Rest": "R", "Ring": "r"}, {"Rest": ""}])
def test_pinned_codes_must_be_distinct_letters_and_digits(pinned):
    with pytest.raises(ValueError, match="pin distinct codes"):
        class_codes(["Rest", "Ring"], pinned)


def test_classes_alike_to_the_last_letter_are_numbered_unless_pinned():
    assert class_codes(["Rest", "rest"]) == {"Rest": "Rest1", "rest": "Rest2"}
    assert class_codes(["Rest", "rest"], {"rest": "R0"}) == {"Rest": "R", "rest": "R0"}
    assert class_codes(["...", "___", "Fist"]) == {"...": "C1", "___": "C2", "Fist": "F"}


@pytest.fixture
def minute(monkeypatch):
    """Every take starts in the same minute."""
    monkeypatch.setattr("myogestic.session._core.time.strftime", lambda *a: "20261105-1533")


def _take(tmp_path, labels=(), *, kind="recordings", name="", classes=GALVANI, pinned=None):
    session = Session(str(tmp_path), participant="P-023", kind=kind)
    session.init_stream("emg", StreamInfo(n_channels=1, fs=10.0))
    session.append("emg", np.zeros((11, 1)), np.arange(11.0))
    for index, label in enumerate(labels):
        session.add_label(classes.index(label), timestamp=float(index))
    session.name = name
    session.save_meta("test", class_names=classes, class_codes=pinned)
    return session.pack_to_zip()


def test_takes_in_one_minute_differ_by_what_and_repeat_with_a_number(tmp_path, minute):
    names = [
        _take(tmp_path, ["Rest"]).name,
        _take(tmp_path, ["Fist"]).name,
        _take(tmp_path, ["Fist"]).name,
        _take(tmp_path, ["Rest", "Three-Finger-Pinch"], name="practice").name,
        _take(tmp_path).name,
    ]
    assert names == [
        "P-023_20261105-1533_R.mg.zip",
        "P-023_20261105-1533_F.mg.zip",
        "P-023_20261105-1533_F-2.mg.zip",
        "P-023_20261105-1533_R+Tfp_practice.mg.zip",
        "P-023_20261105-1533.mg.zip",
    ]
    assert all(
        p.parent == tmp_path / "P-023" / "recordings" for p in (tmp_path / "P-023").rglob("*.zip")
    )


def test_a_long_set_names_its_first_three_codes_and_counts_the_rest(tmp_path, minute):
    classes = [f"Gesture-{word}-Long-Name" for word in "ABCDEFGHIJ"]
    archive = _take(tmp_path, classes, classes=classes)
    assert archive.name == "P-023_20261105-1533_Galn+Gbln+Gcln+7-more.mg.zip"


def test_prediction_takes_say_free_guided_or_what_they_followed(tmp_path, minute):
    names = [
        _take(tmp_path, kind="predictions").name,
        _take(tmp_path, ["Fist"], kind="predictions").name,
        _take(tmp_path, ["Rest", "Fist", "Pinch"], kind="predictions", name="guided").name,
        _take(tmp_path, kind="predictions", name="follow-F").name,
    ]
    assert names == [
        "P-023_20261105-1533_free.mg.zip",
        "P-023_20261105-1533_free-F.mg.zip",
        "P-023_20261105-1533_guided.mg.zip",
        "P-023_20261105-1533_follow-F.mg.zip",
    ]


def test_meta_json_keeps_every_class_code_with_the_pins(tmp_path, minute):
    archive = _take(tmp_path, ["Rest"], classes=KAPPA, pinned={"Rest": "R"})
    assert archive.name == "P-023_20261105-1533_R.mg.zip"
    with zipfile.ZipFile(archive) as packed:
        meta = json.loads(packed.read("meta.json"))
    assert meta["class_codes"] == class_codes(KAPPA, {"Rest": "R"})
    assert meta["class_codes"]["Ring"] == "Ri"


def test_a_folder_finds_its_own_archive_not_another_take_of_that_minute(tmp_path, minute):
    first = Session(str(tmp_path), participant="P-023")
    first.init_stream("emg", StreamInfo(n_channels=1, fs=10.0))
    folder = first.path
    first.save_meta("test")
    archive = first.pack_to_zip()
    second = Session(str(tmp_path), participant="P-023")  # same minute

    assert packed_session_path(folder) == archive
    assert second.path == folder.with_name(f"{folder.name}-2")  # never the packed one's
    assert packed_session_path(second.path) is None
    second.save_meta("test")  # a folder lists once it has metadata
    assert {row["path"] for row in scan_sessions(str(tmp_path / "P-023"))} == {
        str(archive),
        str(second.path),
    }
    # Packing elsewhere: the temporary archive is named after its folder.
    (second.path.parent / f"{second.path.name}.mg.zip.tmp").touch()
    assert {row["path"] for row in scan_sessions(str(tmp_path / "P-023"))} == {str(archive)}
