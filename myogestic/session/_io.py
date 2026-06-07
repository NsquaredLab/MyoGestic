from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import zarr
import zarr.storage

from myogestic.session._core import LabelEvent, Session
from myogestic.stream import StreamInfo


def open_session_store(path: str | Path) -> Session:
    """Open a saved session folder or .session.zip as a read-only Session.

    Folder sessions keep the existing layout and use
    `zarr.open_array(str(path / "<stream>.zarr"), mode="r")`. Zip sessions use
    a `zarr.storage.ZipStore` and read the same array paths inside the archive.
    """
    p = Path(path)
    zip_store = None
    if p.is_dir():
        meta = json.loads((p / "meta.json").read_text())
        labels_file = p / "labels.json"
        labels = json.loads(labels_file.read_text()) if labels_file.exists() else []

        def open_array(name: str) -> zarr.Array:
            return zarr.open_array(str(p / name), mode="r")

    elif p.name.endswith(".session.zip"):
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
    if zip_store is not None:
        session._zip_store = zip_store

    for name, info in meta.get("streams", {}).items():
        data = open_array(f"{name}.zarr")
        session.stores[name] = data
        session.ts_stores[name] = open_array(f"{name}_timestamps.zarr")
        session._streams_info[name] = StreamInfo(
            n_channels=int(info.get("n_channels", data.shape[1] if data.ndim > 1 else 1)),
            fs=float(info.get("fs", 0.0)),
            dtype=np.dtype(info.get("dtype", data.dtype)),
            channel_names=info.get("channel_names"),
        )
    return session
