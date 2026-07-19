from __future__ import annotations

import gc
import json
import logging
import os
import shutil
import stat
import time
import uuid
import zipfile
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import zarr
import zarr.storage

if TYPE_CHECKING:
    from myogestic.stream import StreamInfo

log = logging.getLogger(__name__)

if find_spec("zarrs") is not None:
    zarr.config.set({"codec_pipeline.path": "zarrs.ZarrsCodecPipeline"})

#: ``meta.json`` schema version. Bump whenever the on-disk shape of a
#: per-stream entry changes (e.g. a new field). Readers must stay tolerant
#: of older, unversioned meta.json files (see `open_session_store`), so
#: this is informational rather than enforced. Bumped to 2 for
#: `channel_names` + `channel_grids` (see `StreamInfo.channel_grids`).
_META_SCHEMA_VERSION = 2


def _robust_rmtree(path: Path, *, retries: int = 5, delay_s: float = 0.1) -> None:
    """``shutil.rmtree`` that tolerates Windows file-handle lag.

    On POSIX a single ``rmtree`` of a zarr folder always succeeds (open files can
    be unlinked). On Windows a just-written chunk - or an antivirus scan - can
    briefly hold a handle, so deletion raises ``PermissionError`` (WinError 32).
    Force a GC to drop any lingering zarr handles, clear the read-only bit
    Windows sets on locked files, and retry a few times before giving up.

    Notes
    -----
    A no-op-different behaviour on POSIX: the first attempt succeeds, so the
    retry/GC path is Windows-only in practice.
    """

    def _force_writable(func, p, _exc):  # noqa: ANN001
        os.chmod(p, stat.S_IWRITE)
        func(p)

    for attempt in range(retries):
        try:
            shutil.rmtree(path, onexc=_force_writable)
            return
        except OSError:
            if attempt == retries - 1:
                raise
            gc.collect()
            time.sleep(delay_s)


@dataclass
class LabelEvent:
    """One entry in a session's label track: "at LSL time T, the user picked class N".

    Recorded whenever the user clicks a class button in
    :func:`~myogestic.widgets.panels.recording.recording_controls`. The label track is
    a chronological list of these events; the recording-window
    iterators (:func:`~myogestic.session.iter_labeled_windows`,
    :func:`~myogestic.session.iter_aligned_windows`) walk the track to
    decide which sample range gets which class index.

    Attributes
    ----------
    timestamp
        LSL clock time (seconds) when the label was emitted.
        Use ``mne_lsl.lsl.local_clock()`` if you ever need to mint
        one by hand.
    class_index
        Index into the session's ``class_names`` list.
        ``-1`` is the unlabeled sentinel (the iterators skip it).
    """

    timestamp: float
    class_index: int  # -1 = unlabeled


@dataclass
class Recording:
    """A single labeled trial, extracted from a Session."""

    class_index: int
    class_name: str
    data: np.ndarray  # (n_samples, n_channels)
    timestamps: np.ndarray  # (n_samples,)


class Session:
    """One recording session on disk: per-stream Zarr arrays + a label track.

    Created when the user clicks **Record**, finalised when they click
    **Stop**. While active, every acquisition thread that has its
    stream registered appends to the session's Zarr stores; UI label
    clicks emit :class:`LabelEvent` entries onto the label track.
    Closing the session writes ``meta.json`` and ``labels.json``
    alongside the Zarr folders, and optionally packs the whole tree
    into a portable ``.session.zip``.

    Layout on disk (one folder per recording, named with the start
    timestamp)::

        sessions/2026-05-17_14-23-05/
            emg.zarr/                  # shape (n_samples, n_channels)
            emg_timestamps.zarr/       # shape (n_samples,) float64
            vhi_control.zarr/          # any additional stream
            vhi_control_timestamps.zarr/
            meta.json                  # streams_info, app_name, class_names
            labels.json                # the LabelEvent list

    Read sessions back with :func:`~myogestic.session.open_session_store`,
    which transparently handles both folders and ``.session.zip``
    archives.

    Parameters
    ----------
    base_path
        Parent directory; the session creates a
        timestamp-named subdirectory inside. Default ``"sessions"``
        (created if missing).
    """

    def __init__(self, base_path: str = "sessions"):
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        # Append a short random suffix so two sessions started within the same
        # wall-clock second (e.g. Stop then immediately Record) never share a
        # folder. pack_to_zip() runs on a daemon thread and shutil.rmtree()s its
        # own folder; a shared name would let the old session's pack thread wipe
        # the new recording's data (and collide on the <name>.session.zip path).
        self.path = Path(base_path) / f"{ts}_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        self.stores: dict[str, zarr.Array] = {}
        self.ts_stores: dict[str, zarr.Array] = {}
        self.label_track: list[LabelEvent] = []
        self.class_names: list[str] = []  # populated by save_meta / open_session_store
        self._streams_info: dict[str, StreamInfo] = {}
        # Anchors a ZipStore's lifetime when opened from a .session.zip (see
        # open_session_store): zarr reads arrays lazily from the archive, so the
        # store handle must outlive this Session. Assigned there, never read.
        self._zip_store: zarr.storage.ZipStore | None = None

    def init_stream(self, stream_name: str, info: StreamInfo) -> None:
        """Called once per stream when recording starts."""
        self._streams_info[stream_name] = info
        self.stores[stream_name] = zarr.open_array(
            str(self.path / f"{stream_name}.zarr"),
            mode="w",
            shape=(0, info.n_channels),
            chunks=(int(info.fs), info.n_channels),
            dtype=info.dtype,
        )
        self.ts_stores[stream_name] = zarr.open_array(
            str(self.path / f"{stream_name}_timestamps.zarr"),
            mode="w",
            shape=(0,),
            chunks=(int(info.fs),),
            dtype=np.float64,
        )

    def append(self, stream_name: str, data: np.ndarray, timestamps: np.ndarray) -> None:
        """Called from acquire loop when recording. data: (n_samples, n_channels)."""
        # Defense-in-depth: Stream.detach_session() (under its lock) is what
        # actually prevents an append from racing pack_to_zip()'s clear(); this
        # guard keeps a stray/late append from raising KeyError if the stores
        # were already finalised, rather than crashing the caller's thread.
        store = self.stores.get(stream_name)
        ts_store = self.ts_stores.get(stream_name)
        if store is None or ts_store is None:
            # Should not happen now that Stream.detach_session() drains
            # in-flight appends before pack_to_zip() clears the stores; log
            # it so a future regression that drops samples is observable
            # rather than silent.
            log.debug("dropping late append for finalised stream %r", stream_name)
            return
        store.append(data)
        ts_store.append(timestamps)

    def add_label(self, class_index: int, timestamp: float | None = None) -> None:
        """Append a label event to the session's label track.

        Parameters
        ----------
        class_index
            Class index for the event; ``-1`` marks a rest / no-class boundary.
        timestamp
            Event time in seconds (``mne_lsl`` clock). Defaults to the current
            ``local_clock()`` when omitted.
        """
        from mne_lsl.lsl import local_clock

        ts = timestamp if timestamp is not None else local_clock()
        self.label_track.append(LabelEvent(timestamp=ts, class_index=class_index))

    def save_meta(self, app_name: str, class_names: list[str] | None = None) -> None:
        """Write meta.json + labels.json to the session folder.

        Parameters
        ----------
        app_name
            Identifier for the producing app.
        class_names
            Optional human-readable names for label class indices.
            Persisting them makes old sessions self-describing: readers can
            render labels without an external lookup.
        """
        meta: dict[str, object] = {
            "schema_version": _META_SCHEMA_VERSION,
            "app_name": app_name,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "streams": {
                name: {
                    "n_channels": info.n_channels,
                    "fs": info.fs,
                    "dtype": str(info.dtype),
                    "channel_names": info.channel_names,
                    "channel_grids": (
                        [{"label": g.label, "cells": g.cells} for g in info.channel_grids]
                        if info.channel_grids is not None
                        else None
                    ),
                }
                for name, info in self._streams_info.items()
            },
        }
        if class_names is not None:
            meta["class_names"] = list(class_names)
        (self.path / "meta.json").write_text(json.dumps(meta, indent=2))
        labels = [
            {"timestamp": e.timestamp, "class_index": e.class_index} for e in self.label_track
        ]
        (self.path / "labels.json").write_text(json.dumps(labels, indent=2))

    def pack_to_zip(self) -> Path:
        """Pack the session folder into a single `<name>.session.zip` file.

        Uses ZIP_STORED (no compression). Zarr chunks are already compressed
        internally; an outer compression layer would add CPU for little gain.
        """
        # zarr v3 arrays expose no explicit close, so drop refs and force a GC
        # to release the underlying chunk-file handles. On POSIX this is belt-
        # and-braces (open files can be unlinked anyway); on Windows it is
        # required - the later rmtree/replace fail with WinError 32 if any
        # handle into the folder is still open.
        self.stores.clear()
        self.ts_stores.clear()
        gc.collect()

        zip_path = self.path.with_name(self.path.name + ".session.zip")
        tmp_path = zip_path.with_suffix(zip_path.suffix + ".tmp")
        if tmp_path.exists():
            tmp_path.unlink()

        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_STORED) as zf:
            for f in self.path.rglob("*"):
                if f.is_file():
                    zf.write(f, arcname=str(f.relative_to(self.path)))

        try:
            with zipfile.ZipFile(tmp_path) as zf:
                names = zf.namelist()
                if "meta.json" not in names:
                    raise RuntimeError("meta.json missing in packed zip")
            store = zarr.storage.ZipStore(tmp_path, mode="r")
            try:
                for name in self._streams_info:
                    zarr.open_array(store=store, path=f"{name}.zarr", mode="r")
            finally:
                store.close()
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        # os.replace (not Path.rename): atomic overwrite on both OSes - Windows
        # rename raises if the destination already exists.
        os.replace(tmp_path, zip_path)
        _robust_rmtree(self.path)
        self.path = zip_path
        return zip_path

    def get_trials(
        self,
        stream_name: str,
        pre_s: float = 0.0,
        post_s: float = 0.0,
        class_names: list[str] | None = None,
    ) -> list[Recording]:
        """Extract discrete labeled windows for classification training."""
        data = np.array(self.stores[stream_name])
        ts = np.array(self.ts_stores[stream_name])
        if len(ts) == 0 or len(self.label_track) == 0:
            return []

        trials = []
        for i, event in enumerate(self.label_track):
            if event.class_index == -1:
                continue

            idx_start = int(np.argmin(np.abs(ts - (event.timestamp - pre_s))))
            if i + 1 < len(self.label_track):
                idx_end = int(np.argmin(np.abs(ts - self.label_track[i + 1].timestamp)))
            elif post_s > 0:
                idx_end = int(np.argmin(np.abs(ts - (event.timestamp + post_s))))
            else:
                idx_end = len(ts)

            if idx_end <= idx_start:
                continue

            name = class_names[event.class_index] if class_names else str(event.class_index)
            trials.append(
                Recording(
                    class_index=event.class_index,
                    class_name=name,
                    data=data[idx_start:idx_end],
                    timestamps=ts[idx_start:idx_end],
                )
            )
        return trials

    def get_continuous(self, stream_name: str) -> tuple[np.ndarray, np.ndarray]:
        """Return full stream data + timestamps for regression training."""
        return np.array(self.stores[stream_name]), np.array(self.ts_stores[stream_name])

    def stream_info(self, stream_name: str) -> StreamInfo:
        """Public accessor for a stream's StreamInfo."""
        return self._streams_info[stream_name]

    def close(self) -> None:
        """Release file handles held by this session.

        Closes the ``ZipStore`` opened by :func:`open_session_store` for a
        ``.session.zip`` and drops the array references. Safe to call more than
        once. On Windows an open ``ZipStore`` keeps the archive **locked**, so
        close the session before moving or deleting the ``.session.zip``. Use as
        a context manager (``with open_session_store(p) as s: ...``) to do this
        automatically.
        """
        store = getattr(self, "_zip_store", None)
        if store is not None:
            try:
                store.close()
            except Exception:  # noqa: BLE001 - best-effort release on teardown
                log.debug("ZipStore close failed for %s", self.path, exc_info=True)
            self._zip_store = None
        self.stores.clear()
        self.ts_stores.clear()

    def __enter__(self) -> Session:
        """Return self so a session can be used as a context manager."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close file handles on context exit."""
        self.close()
