from __future__ import annotations

import json
import threading
import time
import zipfile
from pathlib import Path

import numpy as np
import zarr
import zarr.storage

from myogestic.session._core import LabelEvent, Session
from myogestic.stream import ChannelGrid, StreamInfo


def recover_session(path: str | Path) -> Path:
    """Pack a crashed take's folder with the normal, verified archive path.

    Stop the recording process before calling this. Requires the ``meta.json``
    checkpoint written by current recorders; older crashed folders without one
    cannot be recovered this way. The original folder is removed only after
    packing succeeds. An unfinished take stays marked ``finished=False``.

    Only data already written to disk can be recovered. Buffered event rows,
    labels and extras changed since the last checkpoint, and finalize-hook
    outputs may be missing. Recovery does not resume acquisition or run hooks.

    Parameters
    ----------
    path
        The unpacked take folder, not its parent or an existing archive.

    Returns
    -------
    pathlib.Path
        The packed ``.mg.zip`` path, readable by `open_session_store` and
        `myogestic.widgets.SessionManager`.

    Examples
    --------
    >>> from myogestic.session import recover_session
    >>> archive = recover_session("data/P-001/recordings/P-001_20261107-0930")
    """
    folder = Path(path)
    if not folder.is_dir():
        raise ValueError(f"Recovery requires an unpacked session folder: {folder}")
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    with open_session_store(folder) as session:
        # open_session_store deliberately skips the constructor: recovery must use
        # this folder, never create another take or reopen its arrays for writing.
        session._stem = folder.name
        session._started = time.strptime(meta["created"], "%Y-%m-%dT%H:%M:%S")
        session.save_meta(
            meta.get("app_name", ""),
            class_names=meta.get("class_names"),
            class_codes=meta.get("class_codes"),
            control_space=meta.get("control_space"),
            control_spaces=meta.get("control_spaces"),
            finished=meta.get("finished", True),
        )
        return session.pack_to_zip()


def open_session_store(path: str | Path) -> Session:
    """Open a saved session folder or .mg.zip as a read-only Session.

    Folder sessions keep the existing layout and use
    `zarr.open_array(str(path / "<stream>.zarr"), mode="r")`. Zip sessions use
    a `zarr.storage.ZipStore` and read the same array paths inside the archive.

    Examples
    --------
    >>> from myogestic.session import open_session_store
    >>> session = open_session_store("sessions/demo.mg.zip")
    >>> info = session.stream_info("emg")
    >>> session.close()
    """
    p = Path(path)
    zip_store = None
    if p.is_dir():
        meta = json.loads((p / "meta.json").read_text(encoding="utf-8"))
        labels_file = p / "labels.json"
        labels = json.loads(labels_file.read_text(encoding="utf-8")) if labels_file.exists() else []

        def open_array(name: str) -> zarr.Array:
            return zarr.open_array(str(p / name), mode="r")

    elif p.suffix == ".zip":  # .mg.zip, and older .session.zip takes
        zip_store = zarr.storage.ZipStore(p, mode="r")
        with zipfile.ZipFile(p) as zf:
            names = set(zf.namelist())
            meta = json.loads(zf.read("meta.json"))
            labels = json.loads(zf.read("labels.json")) if "labels.json" in names else []

        def open_array(name: str) -> zarr.Array:
            return zarr.open_array(store=zip_store, path=name, mode="r")

    else:
        raise ValueError(f"Unsupported session path: {p}")

    session = Session.__new__(Session)
    session.path = p
    session.stores = {}
    session.ts_stores = {}
    session.label_track = [
        LabelEvent(
            timestamp=float(label.get("timestamp", 0.0)),
            class_index=int(label.get("class_index", -1)),
        )
        for label in labels
        if isinstance(label, dict)
    ]
    session._streams_info = {}
    session.class_names = list(meta.get("class_names") or [])
    session.extras = dict(meta.get("extras") or {})
    session._pose_convention = meta.get("pose_convention")
    # `Session.__new__` skips `__init__`, so every attribute a caller can read has to
    # be set here or it raises AttributeError instead of coming back empty. `name` is
    # written to meta.json precisely so it survives this trip.
    session.name = str(meta.get("name") or "")
    session.participant = str(meta.get("participant") or "")
    session.kind = p.parent.name if p.parent.name in ("recordings", "predictions") else ""
    # Always set (None for folder sessions): keeps Session.close() safe even
    # though open_session_store bypasses __init__ via Session.__new__.
    session._zip_store = zip_store
    # A loaded session is read-only: frozen, with no buffers, so freeze() is a no-op and
    # append_event drops instead of raising AttributeError on the attributes __init__ set.
    session._event_lock = threading.RLock()
    session._event_buffers = {}
    session._event_streams = list(meta.get("event_streams") or [])
    session._finalising = True

    for name, info in meta.get("streams", {}).items():
        data = open_array(f"{name}.zarr")
        session.stores[name] = data
        session.ts_stores[name] = open_array(f"{name}_timestamps.zarr")
        grids_raw = info.get("channel_grids")
        channel_grids = (
            [ChannelGrid(label=g["label"], cells=g["cells"]) for g in grids_raw]
            if grids_raw is not None
            else None
        )
        session._streams_info[name] = StreamInfo(
            n_channels=int(info.get("n_channels", data.shape[1] if data.ndim > 1 else 1)),
            fs=float(info.get("fs", 0.0)),
            dtype=np.dtype(info.get("dtype", data.dtype)),
            channel_names=info.get("channel_names"),
            channel_grids=channel_grids,
        )
    return session
