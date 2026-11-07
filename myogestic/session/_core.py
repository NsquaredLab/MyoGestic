from __future__ import annotations

import contextlib
import gc
import json
import logging
import os
import re
import shutil
import stat
import sys
import threading
import time
import uuid
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import zarr
import zarr.storage

# Zarr 3's synchronous API starts an IO thread even for a local store. Pyodide
# uses Zarr 2's synchronous directory/zip stores instead; both write ordinary
# Zarr arrays that open_session_store can read on desktop as well.
_ZARR_V3 = int(zarr.__version__.split(".")[0]) >= 3
if _ZARR_V3:
    from zarr.codecs import BloscCodec, BytesCodec, ZstdCodec

if TYPE_CHECKING:
    from myogestic.stream import StreamInfo

log = logging.getLogger(__name__)

if _ZARR_V3 and find_spec("zarrs") is not None:
    zarr.config.set({"codec_pipeline.path": "zarrs.ZarrsCodecPipeline"})

#: ``meta.json`` schema version. Bump whenever its on-disk shape changes.
#: Version 4 supports the optional ``finished`` flag; older files remain readable.
#: Readers must stay tolerant of older, unversioned meta.json files
#: (see `open_session_store`), so this is informational rather than enforced.
_META_SCHEMA_VERSION = 4

#: Value of ``meta.json``'s ``pose_convention``, stamped on every session this build
#: writes. Signed and normalised, ``+1`` in the direction the control's address names —
#: what a `ControlBus` emits, so a recording made through one is in it by construction.
#:
#: The stamp exists so a reader never has to guess. A session without it predates the
#: question and is in the pre-2.5 convention, where negative meant flexion; that is what
#: `myogestic.tools.migrate_vhi_sessions` converts, and it is why the stamp has to be
#: written rather than inferred. Unstamped, a session recorded today would read as legacy
#: and be flipped by a migration it does not need.
POSE_CONVENTION = "standard"

#: Rows an event stream buffers before one batched zarr write. Measured on zarr 3.2.1: a
#: single-row append into a partially filled chunk costs ~1.5 ms (read, decompress, rewrite,
#: recompress the chunk); 32 rows appended at once cost ~0.04 ms per row. The predict thread
#: has a 31 ms budget per tick and may feed ten of these streams.
EVENT_CHUNK_ROWS = 1024

#: Signal streams: byte shuffle + LZ4. Every append re-encodes the open chunk, so speed
#: counts as much as ratio. Measured on real takes (320 ch at 2048 Hz, 64-sample appends):
#: 7% smaller than zarr's default zstd and 14% less append time, timestamps 2-4x smaller;
#: Blosc zstd 5 was 12% smaller but tripled the append time. Event streams (predictions,
#: controls) are low-entropy and compress best with plain zstd, zarr's default.
if _ZARR_V3:
    _SIGNAL_CODECS = {"codecs": (BytesCodec(), BloscCodec(cname="lz4", clevel=5, shuffle="shuffle"))}
    _EVENT_CODECS = {"codecs": (BytesCodec(), ZstdCodec(level=0))}
else:
    from numcodecs import Blosc, Zstd, blosc

    # Blosc otherwise creates native codec threads, independently of Python's
    # Thread API. One thread also keeps the browser's codec work on this frame.
    blosc.set_nthreads(1)
    _SIGNAL_CODECS = {"compressor": Blosc(cname="lz4", clevel=5, shuffle=Blosc.SHUFFLE)}
    _EVENT_CODECS = {"compressor": Zstd(level=0)}
#: A buffer older than this is flushed on the next append, whatever its size, so a quiet
#: stream still reaches disk within a second.
EVENT_FLUSH_SECONDS = 1.0


@dataclass
class _EventBuffer:
    rows: list[np.ndarray] = field(default_factory=list)
    times: list[float] = field(default_factory=list)
    since: float | None = None  # time.monotonic() of the oldest buffered row
    dead: bool = False  # set by _flush_locked on IO failure; append_event returns early if true


def _robust_rmtree(path: Path, *, retries: int = 5, delay_s: float = 0.1) -> None:
    """``shutil.rmtree`` that tolerates Windows file-handle lag.

    On POSIX the first ``rmtree`` of a zarr folder always succeeds (open files can
    be unlinked). On Windows a recently written chunk or antivirus scan can
    briefly hold a handle, causing ``PermissionError`` with WinError 32.
    Force a GC to drop any lingering zarr handles, clear the read-only bit
    Windows sets on locked files, and retry a few times before giving up.
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


def _install_windows_zarr_atomic_write_retry(*, retries: int = 10, delay_s: float = 0.05) -> None:
    """Make zarr's atomic chunk-write tolerate Windows file-handle lag.

    zarr commits every chunk by writing a temp file and atomically renaming it
    over the destination (``zarr.storage._local._atomic_write``). On POSIX that
    rename never fails; on Windows the underlying ``MoveFileEx`` raises
    ``PermissionError`` (WinError 5 / 32) whenever another handle to the file is
    still open, for example during antivirus scanning or search indexing.
    High-rate recording repeatedly grows arrays through [`Session.append`][]
    and renames trailing chunks, increasing exposure to this race.

    Retry the rename itself. Retrying ``zarr.Array.append`` is unsafe because
    it persists the resized shape before writing chunks; a partial failure
    would leave the retry writing at the wrong offset.

    This Windows-only wrapper applies bounded back-off to ``_atomic_write``.
    If zarr's internals change, the guard skips the patch.
    """
    if sys.platform != "win32":
        return
    try:
        import zarr.storage._local as _zlocal

        _orig_safe_move = getattr(_zlocal, "_safe_move", None)

        @contextlib.contextmanager
        def _atomic_write_retry(path, mode, exclusive=False):  # noqa: ANN001, ANN202
            tmp_path = path.with_suffix(f".{uuid.uuid4().hex}.partial")
            try:
                with tmp_path.open(mode) as f:
                    yield f
                for attempt in range(retries):
                    try:
                        if exclusive and _orig_safe_move is not None:
                            _orig_safe_move(tmp_path, path)
                        else:
                            tmp_path.replace(path)
                        break
                    except PermissionError:
                        if attempt == retries - 1:
                            raise
                        gc.collect()
                        time.sleep(delay_s * (attempt + 1))
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise

        # LocalStore.set looks the name up as a module global at call time, so
        # rebinding it here takes effect for every subsequent chunk write.
        _zlocal._atomic_write = _atomic_write_retry
    except Exception:
        log.debug("could not install Windows zarr atomic-write retry", exc_info=True)


_install_windows_zarr_atomic_write_retry()


@dataclass
class LabelEvent:
    """A class selection at an LSL timestamp in the session's label track.

    Recorded whenever the user clicks a class button in
    [`RecordingControls`][myogestic.widgets.RecordingControls]. The label track is a
    chronological list of these events; the recording-window iterators
    ([`iter_labeled_windows`][myogestic.session.iter_labeled_windows],
    [`iter_aligned_windows`][myogestic.session.iter_aligned_windows]) walk it to decide
    which sample range gets which class index.

    Attributes
    ----------
    timestamp
        LSL clock time (seconds) when the label was emitted. Mint one by hand
        with ``mne_lsl.lsl.local_clock()``.
    class_index
        Index into the session's ``class_names`` list. ``-1`` is the unlabeled
        sentinel (the iterators skip it).

    Examples
    --------
    >>> from myogestic.session import LabelEvent
    >>> event = LabelEvent(timestamp=123.0, class_index=1)
    >>> event.class_index
    1
    """

    timestamp: float
    class_index: int  # -1 = unlabeled


@dataclass
class Recording:
    """A single labeled trial, extracted from a Session.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.session import Recording
    >>> recording = Recording(
    ...     1, "Fist", np.zeros((3, 2), dtype=np.float32), np.arange(3, dtype=np.float64)
    ... )
    >>> (recording.class_name, recording.data.shape)
    ('Fist', (3, 2))
    """

    class_index: int
    class_name: str
    data: np.ndarray  # (n_samples, n_channels)
    timestamps: np.ndarray  # (n_samples,)


#: Cap on the slug appended to an archive name — long enough to be recognisable,
#: short enough to keep the whole path under filesystem limits.
_SLUG_MAX = 40

#: Suffix of a packed take. Readers accept any ``.zip`` holding a ``meta.json``, so
#: older takes, named ``.session.zip`` (or renamed by hand), still open and list.
ARCHIVE_SUFFIX = ".mg.zip"


def _slug(name: str) -> str:
    """Filename-safe form of a user-typed session name, or ``""`` if nothing survives.

    Replaces characters outside ASCII alphanumerics, ``-`` and ``_`` with
    dashes. This excludes path separators, ``..`` and non-portable characters.
    """
    kept = "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "-" for c in name)
    return "-".join(filter(None, kept.split("-")))[:_SLUG_MAX].strip("-_")


#: The time part of every file name, local time to the minute. The exact start
#: stays in ``meta.json``.
STAMP_FORMAT = "%Y%m%d-%H%M"


def _code(name: str, width: int, position: int) -> str:
    """Use ``width`` letters of the first word, then one per further word. Rest → R, Re.

    A number stays whole (Pose 10 → P10). A name with no ASCII letter or digit is
    called by its position: C3.
    """
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        return f"C{position}"
    rest = "".join(w if w.isdigit() else w[0].lower() for w in words[1:])
    return words[0][:width].capitalize() + rest


def class_codes(
    class_names: Sequence[str], pinned: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Build short class codes for file names. Rest → R, Three-Finger-Pinch → Tfp.

    A code is the first letter of the first word, plus the first letter of each
    further word (a number stays whole). Where two codes would match, ignoring
    case, both take more letters of their first word until they differ: Rest and
    Ring become Re and Ri. Codes are worked out over the whole list, so a class
    keeps its code in every take of an app. Classes alike to the last letter
    (``Rest`` and ``rest``) get their position appended, ``Rest1`` and ``Rest2``:
    pin a code to choose an alternative.

    Parameters
    ----------
    class_names
        The app's classes, usually ``ctx.class_names``.
    pinned
        Codes the app fixes itself, by class name; the rest are worked out
        around them. Pin the codes once an app has recorded data: adding a class
        later can otherwise change the codes of the ones it clashes with.

    Returns
    -------
    dict
        Class name to code, in ``class_names`` order.

    Raises
    ------
    ValueError
        A pinned code is not ASCII letters and digits, or two pinned codes match.

    Examples
    --------
    >>> class_codes(["Rest", "Thumb", "Index", "Middle", "Ring", "Little"])
    {'Rest': 'Re', 'Thumb': 'T', 'Index': 'I', 'Middle': 'M', 'Ring': 'Ri', 'Little': 'L'}
    >>> class_codes(["Rest", "Fist", "Three-Finger-Pinch"], {"Rest": "0"})
    {'Rest': '0', 'Fist': 'F', 'Three-Finger-Pinch': 'Tfp'}
    """
    pinned = dict(pinned or {})
    taken: set[str] = set()
    for code in pinned.values():
        if not re.fullmatch(r"[A-Za-z0-9]+", code) or code.lower() in taken:
            raise ValueError(
                f"class_codes: pin distinct codes of ASCII letters and digits, not {code!r}"
            )
        taken.add(code.lower())
    codes = {name: pinned[name] for name in class_names if name in pinned}
    position: dict[str, int] = {}
    for i, name in enumerate(class_names):
        position.setdefault(name, i + 1)
    todo = [name for name in position if name not in codes]
    width = 1
    while todo:
        if width > max(len(_code(name, 99, position[name])) for name in todo):
            for name in todo:  # alike to the last letter: number them by position
                code = _code(name, 99, position[name]) + str(position[name])
                while code.lower() in taken:
                    code += "0"
                codes[name] = code
                taken.add(code.lower())
            break
        candidates = {name: _code(name, width, position[name]) for name in todo}
        counts: dict[str, int] = {}
        for code in candidates.values():
            counts[code.lower()] = counts.get(code.lower(), 0) + 1
        clashing = []
        for name, code in candidates.items():
            if counts[code.lower()] == 1 and code.lower() not in taken:
                codes[name] = code
                taken.add(code.lower())
            else:
                clashing.append(name)
        todo, width = clashing, width + 1
    return {name: codes[name] for name in class_names}


_class_codes = class_codes  # for methods whose parameter shadows the name


def _joined_codes(codes: Sequence[str]) -> str:
    """``R+F+P`` while it fits the slug limit, else the first three and a count."""
    joined = "+".join(codes)
    if len(joined) > _SLUG_MAX:
        joined = "+".join(codes[:3]) + f"+{len(codes) - 3}-more"
    return joined


def take_stem(stem: str, kind: str, codes: Sequence[str], name: str) -> str:
    """The one place a take's archive name is built, before ``-2`` and the suffix.

    ``stem`` is ``<ID>_<YYYYMMDD-HHMM>``. In ``predictions`` the take's ``name``
    (``follow-F``, ``guided``) or else ``free`` plus the recorded codes
    (``free-F``); anywhere else the recorded codes then the name (``R+F_practice``).
    """
    joined, slug = _joined_codes(codes), _slug(name)
    if kind == "predictions":
        what = slug or (f"free-{joined}" if joined else "free")
    else:
        what = "_".join(filter(None, (joined, slug)))
    return f"{stem}_{what}" if what else stem


def _claim_path(parent: Path, stem: str, suffix: str) -> Path:
    """Claim ``parent/stem+suffix``, or ``stem-2``, ``stem-3`` … when that is taken.

    Creates the file empty and exclusively, so two takes packing at once (two
    stops in one minute, or every pending take at shutdown) never share a name.
    """
    ordinal = 1
    while True:
        path = parent / (f"{stem}{suffix}" if ordinal == 1 else f"{stem}-{ordinal}{suffix}")
        try:
            path.open("x").close()
        except FileExistsError:
            ordinal += 1
            continue
        return path


def model_path(root: str | Path, participant: str, model: str) -> Path:
    """Claim a new model file, ``root/ID/models/<ID>_<YYYYMMDD-HHMM>_<model>.joblib``.

    Parameters
    ----------
    root
        Data root, usually ``"data"``.
    participant
        Pseudonymized ID; empty puts the model in ``root/models``.
    model
        The model's type, such as ``"spar-mlp"``, lowercased into the name.

    Returns
    -------
    pathlib.Path
        A new, empty file, ``-2``, ``-3`` … when another model of that type was
        saved in the same minute, never overwriting one. Save the model over it.

    Examples
    --------
    >>> model_path("data", "P-023", "SPAR MLP").name  # doctest: +SKIP
    'P-023_20261105-1535_spar-mlp.joblib'
    """
    stamp = labelled_path(root, participant, kind="models")
    stamp.parent.mkdir(parents=True, exist_ok=True)
    return _claim_path(stamp.parent, f"{stamp.name}_{_slug(model.lower()) or 'model'}", ".joblib")


#: Each packed folder (resolved) to the archive it became, for this process. The
#: archive can have a different name from its folder. This map lets a folder path
#: find its take and lets the take list hide a folder whose removal failed.
PACKED_FOLDERS: dict[Path, Path] = {}


#: The folders under ``data/<ID>/`` that hold takes: ``recordings/`` for takes
#: made while idle, ``predictions/`` for takes made beside a live model. Trained
#: models go in ``models/``.
TAKE_KINDS = ("recordings", "predictions")
#: Every folder ``data/<ID>/`` (and ``data/`` itself, for takes with no ID) is split into.
KINDS = (*TAKE_KINDS, "models")


def participant_dir(root: str | Path, participant: str = "", kind: str = "recordings") -> Path:
    """Return the folder that holds one kind of file for one participant.

    Parameters
    ----------
    root
        Data root, usually ``"data"``.
    participant
        Pseudonymized ID, reduced to a safe single path segment.
    kind
        ``"recordings"``, ``"predictions"`` or ``"models"``. ``""`` drops the
        kind level, for tools that keep their own layout.

    Returns
    -------
    pathlib.Path
        ``root/ID/kind``, or ``root/kind`` when the ID has no usable
        characters. Nothing is created.

    Examples
    --------
    >>> participant_dir("data", "P-014", "models").as_posix()
    'data/P-014/models'
    """
    return Path(root, _slug(participant), kind)


def labelled_path(
    base_path: str | Path,
    participant: str = "",
    suffix: str = "",
    *,
    kind: str = "recordings",
    when: time.struct_time | None = None,
) -> Path:
    """Build a timestamped path in a participant's folder for one kind of file.

    Parameters
    ----------
    base_path
        Data root, usually ``"data"``.
    participant
        Pseudonymized ID, reduced to a safe single path segment. An empty
        slug drops the participant level and the filename prefix.
    suffix
        Optional filename suffix, appended after an underscore, such as
        ``"spar-mlp.joblib"``.
    kind
        Subfolder, see `participant_dir`. Default ``"recordings"``.
    when
        Local time to stamp, from `time.localtime`. Default: now.

    Returns
    -------
    pathlib.Path
        ``base/ID/kind/ID_YYYYMMDD-HHMM[_suffix]`` or
        ``base/kind/YYYYMMDD-HHMM[_suffix]``, in local time. No directories are
        created and no name is reserved: two files in one minute share it.
    """
    participant = _slug(participant)
    stamp = time.strftime(STAMP_FORMAT, when or time.localtime())
    stem = "_".join(filter(None, (participant, stamp, suffix)))
    return participant_dir(base_path, participant, kind) / stem


def _unique_stem(parent: Path, stem: str) -> str:
    """Find a folder name no live recording uses and none packed earlier in this process."""
    candidate = stem
    ordinal = 2
    while (parent / candidate).exists() or (parent / candidate).resolve() in PACKED_FOLDERS:
        candidate = f"{stem}-{ordinal}"
        ordinal += 1
    return candidate


@dataclass(frozen=True)
class RecordedTime:
    """Recorded durations across the takes directly in one folder.

    Attributes
    ----------
    takes
        Number of session folders and archives, including legacy takes.
    total_s
        Sum of sample-clock durations in seconds; legacy takes contribute zero.
    per_class
        Recorded seconds for each gesture name, summed across takes.
    """

    takes: int
    total_s: float
    per_class: dict[str, float]


def _read_session_metadata(path: Path) -> tuple[dict, list] | None:
    """Read a folder or zip's metadata and labels without opening its arrays."""
    try:
        if path.is_dir() and (path / "meta.json").exists():
            meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
            labels_file = path / "labels.json"
            labels = (
                json.loads(labels_file.read_text(encoding="utf-8")) if labels_file.exists() else []
            )
        elif path.is_file() and path.name.endswith(".zip"):
            # Renamed archives remain discoverable by the picker and totals.
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                if "meta.json" not in names:
                    return None
                meta = json.loads(archive.read("meta.json"))
                labels = json.loads(archive.read("labels.json")) if "labels.json" in names else []
        else:
            return None
        return (meta, labels) if isinstance(meta, dict) and isinstance(labels, list) else None
    except (OSError, ValueError, zipfile.BadZipFile):
        return None


def recorded_time(folder: str | Path) -> RecordedTime:
    """Sum recorded time for the session folders and archives directly in a folder.

    Parameters
    ----------
    folder
        Directory to inspect without recursion. A missing directory is empty.

    Returns
    -------
    RecordedTime
        Take count, total seconds, and seconds per gesture. Sessions without
        duration metadata count as takes with zero seconds.
    """
    base = Path(folder)
    takes, total_s = 0, 0.0
    per_class: dict[str, float] = {}
    if not base.is_dir():
        return RecordedTime(takes, total_s, per_class)
    for path in base.iterdir():
        entry = _read_session_metadata(path)
        if entry is None:
            continue
        meta, _ = entry
        takes += 1
        total_s += float(meta.get("duration_s", 0.0))
        for name, seconds in meta.get("class_seconds", {}).items():
            per_class[name] = per_class.get(name, 0.0) + float(seconds)
    return RecordedTime(takes, total_s, per_class)


class Session:
    """One on-disk recording with per-stream Zarr arrays and a label track.

    Created when the user clicks Record, finalized when they click Stop.
    While active, every acquisition thread with a registered stream appends to the
    session's Zarr stores; UI label clicks emit [`LabelEvent`][] entries onto the
    label track. Metadata is checkpointed at creation and stream declaration with
    ``finished=False``. `save_meta` updates it at stop, and `pack_to_zip` packs the
    tree into a portable ``.mg.zip``.

    Layout on disk (one folder per recording, named with the start minute,
    packed on stop to ``<ID>_<YYYYMMDD-HHMM>_<what>.mg.zip``, see
    [File names](../concepts/file-names.md))::

        data/P-014/recordings/P-014_20260517-1423/
            emg.zarr/                  # shape (n_samples, n_channels)
            emg_timestamps.zarr/       # shape (n_samples,) float64
            vhi_control.zarr/          # any additional stream
            vhi_control_timestamps.zarr/
            meta.json                  # streams_info, app_name, class_names
            labels.json                # the LabelEvent list

    Read sessions back with [`open_session_store`][myogestic.session.open_session_store],
    which handles both folders and ``.mg.zip`` archives.

    Parameters
    ----------
    base_path
        Data root; the session creates a timestamp-named subdirectory in
        ``base_path/ID/kind``. Default ``"data"`` (created if missing).
    participant
        Pseudonymized ID. A safe slug labels the folder and ``meta.json`` and
        nests the recording under ``base_path/ID/kind``. Empty by default,
        which puts the recording directly in ``base_path/kind``.
    kind
        ``"recordings"`` (default) or ``"predictions"``, see `participant_dir`.
        ``""`` writes straight into ``base_path`` (or ``base_path/ID``), for a
        converter or script that keeps its own folder layout.

    Examples
    --------
    >>> from myogestic.session import Session
    >>> session = Session("data")
    >>> session.add_label(0, timestamp=123.0)
    """

    def __init__(
        self, base_path: str = "data", participant: str = "", kind: str = "recordings"
    ) -> None:
        #: Pseudonymised ID only; personal names belong in the local key file.
        self.participant: str = _slug(participant)
        #: ``"recordings"``, ``"predictions"`` or ``""``: decides how the archive is named.
        self.kind: str = kind
        # One clock read for the name and meta.json's ``created``, so both say the same minute.
        self._started = time.localtime()
        labelled = labelled_path(base_path, self.participant, kind=kind, when=self._started)
        parent = labelled.parent
        parent.mkdir(parents=True, exist_ok=True)
        #: ``<ID>_<YYYYMMDD-HHMM>``: the archive's name starts with it.
        self._stem: str = labelled.name
        # A folder never shares a name with a live one or prefixes an archive, so
        # one take's pack thread (which rmtree()s its folder) never touches another
        # take, and the take list can pair a folder with its own archive.
        # Exclusive mkdir handles two recorders choosing the same free name.
        while True:
            self.path = parent / _unique_stem(parent, labelled.name)
            try:
                self.path.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            break
        #: Free-form facts a widget contributed about this recording, merged into
        #: ``meta.json`` under ``"extras"``. For anything the raw arrays cannot
        #: express on their own — a force calibration is the motivating case: the
        #: force is recorded in device counts and the target in %MVC, so without
        #: the zero and MVC that relate them the tracking error is not
        #: recoverable months later. Values must be JSON-serialisable.
        self.extras: dict[str, Any] = {}
        #: Human-readable name for this recording. Set it before `save_meta`
        #: (the recorder widget does so when the user names the session on Stop);
        #: it lands in ``meta.json`` and in the packed archive's filename.
        self.name: str = ""
        self.stores: dict[str, zarr.Array] = {}
        self.ts_stores: dict[str, zarr.Array] = {}
        self.label_track: list[LabelEvent] = []
        self.class_names: list[str] = []  # populated by save_meta / open_session_store
        self._streams_info: dict[str, StreamInfo] = {}
        # Anchors a ZipStore's lifetime when opened from a .mg.zip (see
        # open_session_store): zarr reads arrays lazily from the archive, so the
        # store handle must outlive this Session. Assigned there, never read.
        self._zip_store: zarr.storage.ZipStore | None = None
        # Event streams: one row per tick from the pipeline or the bus, declared on first
        # use and buffered (see EVENT_CHUNK_ROWS). One lock covers declaration, buffering,
        # flush and freeze, because the predict thread, the UI thread and the finalise
        # thread all reach these.
        self._event_lock = threading.RLock()
        self._event_buffers: dict[str, _EventBuffer] = {}
        self._event_streams: list[str] = []
        #: Set by freeze(): no row is accepted and no stream declared after it.
        self._finalising = False
        self.save_meta("", finished=False)

    def _checkpoint_meta(self) -> None:
        """Persist a declaration, never an acquisition chunk or event-buffer flush."""
        with self._event_lock:
            self.save_meta(**self._meta_options, finished=False)

    def init_stream(
        self, stream_name: str, info: StreamInfo, *, chunk_rows: int | None = None
    ) -> None:
        """Called once per stream when recording starts.

        ``chunk_rows`` sizes the zarr chunk; the default is one second of samples. Event
        streams pass `EVENT_CHUNK_ROWS` because their rate is nominal.
        """
        with self._event_lock:
            self._init_stream(stream_name, info, chunk_rows=chunk_rows)

    def _init_stream(
        self, stream_name: str, info: StreamInfo, *, chunk_rows: int | None = None
    ) -> None:
        """Declare arrays and checkpoint together under the event/metadata lock."""
        rows = max(1, int(info.fs) if chunk_rows is None else int(chunk_rows))
        codecs = _SIGNAL_CODECS if chunk_rows is None else _EVENT_CODECS
        self._streams_info[stream_name] = info
        self.stores[stream_name] = zarr.open_array(
            str(self.path / f"{stream_name}.zarr"),
            mode="w",
            shape=(0, info.n_channels),
            chunks=(rows, info.n_channels),
            dtype=info.dtype,
            **codecs,
        )
        self.ts_stores[stream_name] = zarr.open_array(
            str(self.path / f"{stream_name}_timestamps.zarr"),
            mode="w",
            shape=(0,),
            chunks=(rows,),
            dtype=np.float64,
            **codecs,
        )
        self._checkpoint_meta()

    def append(self, stream_name: str, data: np.ndarray, timestamps: np.ndarray) -> None:
        """Called from acquire loop when recording. data: (n_samples, n_channels)."""
        if self._finalising:
            log.debug("dropping late append for frozen session %s", self.path)
            return
        # Stream.detach_session() (under its lock) is what prevents an append from
        # racing pack_to_zip()'s clear(). This guard only keeps a stray late append
        # from raising KeyError on the caller's thread; the log line makes a future
        # regression that drops samples observable rather than silent.
        store = self.stores.get(stream_name)
        ts_store = self.ts_stores.get(stream_name)
        if store is None or ts_store is None:
            log.debug("dropping late append for finalised stream %r", stream_name)
            return
        store.append(data)
        ts_store.append(timestamps)

    @property
    def event_streams(self) -> tuple[str, ...]:
        """Names of the event streams, in declaration order. One row per tick, nominal rate."""
        return tuple(self._event_streams)

    def append_event(
        self,
        name: str,
        values: Any,
        timestamp: float,
        *,
        channel_names: Sequence[str] | None = None,
        fs: float = 1.0,
        dtype: Any = np.float32,
    ) -> None:
        """Append one timestamped row to an event stream, declaring it on first use.

        ``values`` is flattened and cast to ``dtype``; its width is fixed by the first
        call. A later row with another width raises ``ValueError`` to prevent
        ragged arrays. ``fs``
        is the *nominal* rate the declaration carries, so `ReplaySource` can pace the
        stream; the rows are irregular and ``meta.json`` lists the stream under
        ``event_streams`` to say so.

        Rows are buffered and written in batches (`EVENT_CHUNK_ROWS`, `EVENT_FLUSH_SECONDS`).
        After `freeze` a row is dropped with a debug log, like a late `append`.

        Parameters
        ----------
        dtype
            Dtype fixed by the first declaration of ``name``. Later rows are
            coerced to that dtype. Defaults to ``float32`` for signals and
            features. Use ``float64`` for clocks such as LSL timestamps or
            ``local_clock()``. Float32 has about 7 significant digits and loses
            millisecond precision after roughly a day of uptime.
        """
        row = np.asarray(values, dtype=dtype).ravel()
        if row.size == 0:
            raise ValueError(f"{name!r}: an event row needs at least one value")
        with self._event_lock:
            if self._finalising:
                log.debug("dropping event row for frozen session %s", self.path)
                return
            buf = self._event_buffers.get(name)
            if buf is None:
                if name in self.stores:
                    raise ValueError(f"{name!r} is a sampled stream, not an event stream")
                from myogestic.stream import StreamInfo

                self.init_stream(
                    name,
                    StreamInfo(
                        n_channels=int(row.size),
                        fs=float(fs),
                        dtype=np.dtype(dtype),
                        channel_names=list(channel_names) if channel_names else None,
                    ),
                    chunk_rows=EVENT_CHUNK_ROWS,
                )
                self._event_streams.append(name)
                self._checkpoint_meta()
                buf = self._event_buffers[name] = _EventBuffer()
            else:
                # Already declared: the stream's dtype won, not this call's — coerce
                # rather than let a later, differently-typed caller silently drift it.
                row = row.astype(self._streams_info[name].dtype, copy=False)
            width = self._streams_info[name].n_channels
            if row.size != width:
                raise ValueError(f"{name!r} rows are {width} wide, got {row.size}")
            if buf.dead:
                log.debug("dropping event row for dead stream %r", name)
                return
            now = time.monotonic()
            buf.rows.append(row)
            buf.times.append(float(timestamp))
            if buf.since is None:
                buf.since = now
            if len(buf.rows) >= EVENT_CHUNK_ROWS or now - buf.since >= EVENT_FLUSH_SECONDS:
                self._flush_locked(name, buf)

    def _flush_locked(self, name: str, buf: _EventBuffer) -> None:
        """Write a buffer as one batch. Caller holds ``_event_lock``.

        On IO failure, logs once at warning level, marks the buffer dead so later
        append_event calls drop silently, and clears the buffer to avoid retries.
        """
        if not buf.rows:
            return
        try:
            self.stores[name].append(np.stack(buf.rows))
            self.ts_stores[name].append(np.asarray(buf.times, dtype=np.float64))
        except Exception as exc:
            log.warning(
                "event stream %r: flush failed, dropping its rows for the rest of this session: %r",
                name,
                exc,
            )
            buf.dead = True
        finally:
            buf.rows.clear()
            buf.times.clear()
            buf.since = None

    def freeze(self) -> None:
        """Close the session to new rows and flush every event buffer. Idempotent.

        `App.stop_recording` calls this right after detaching the streams and before any
        finalize hook or ``meta.json`` is written, so nothing can declare a stream that the
        metadata does not list. `pack_to_zip` and `discard` call it as well.

        Flushes every buffer even if one fails; per-buffer failures are logged at
        warning level, and the buffer is marked dead to prevent retries.
        """
        with self._event_lock:
            if self._finalising:
                return
            self._finalising = True
            for name, buf in self._event_buffers.items():
                self._flush_locked(name, buf)

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

    def save_meta(
        self,
        app_name: str,
        class_names: list[str] | None = None,
        control_space: Mapping[str, object] | None = None,
        control_spaces: Mapping[str, Mapping[str, object]] | None = None,
        class_codes: Mapping[str, str] | None = None,
        *,
        finished: bool = True,
    ) -> None:
        """Write meta.json + labels.json to the session folder.

        Parameters
        ----------
        app_name
            Identifier for the producing app.
        class_names
            Optional human-readable names for label class indices. Persisting them
            lets readers render saved labels without an external lookup.
        control_space
            Optional control configuration this recording was made under, as produced
            by ``ControlMap.as_control_space()``. Records each value's alias
            and target control. Carries a ``format`` tag; read
            it back with `myogestic.controls.read_control_space`, which refuses a
            pre-alias control space by name instead of reinterpreting it.
        control_spaces
            Additional control configurations keyed by recording stream name. Each
            entry has the same format as ``control_space``. Omitted from metadata
            when empty, preserving the single-link recording format.
        class_codes
            Codes the app pins for some classes, usually ``ctx.class_codes``. The
            rest are worked out by `class_codes`; the whole map is saved as
            ``meta.json``'s ``class_codes`` and names the archive.
        finished
            Whether the take stopped normally. Start and declaration checkpoints
            pass ``False``; finalization uses the default ``True``. Recovery keeps
            an unfinished take marked ``False`` even after it is packed.
        """
        with self._event_lock:
            self._save_meta(
                app_name, class_names, control_space, control_spaces, class_codes, finished=finished
            )

    def _save_meta(
        self,
        app_name: str,
        class_names: list[str] | None,
        control_space: Mapping[str, object] | None,
        control_spaces: Mapping[str, Mapping[str, object]] | None,
        class_codes: Mapping[str, str] | None,
        *,
        finished: bool,
    ) -> None:
        """Write one atomic metadata checkpoint with declarations held stable."""
        # Reused only when another stream is declared, so appends keep their original
        # cost and a later event stream does not erase the app's interpretation keys.
        self._meta_options = {
            "app_name": app_name,
            "class_names": class_names,
            "control_space": control_space,
            "control_spaces": control_spaces,
            "class_codes": class_codes,
        }
        self.class_names = list(class_names or [])
        # Packing a previously saved folder must not relabel legacy pose values
        # as today's convention. A fresh take always carries the current tag.
        convention = getattr(self, "_pose_convention", POSE_CONVENTION)
        meta: dict[str, object] = {
            "schema_version": _META_SCHEMA_VERSION,
            "finished": finished,
            "pose_convention": convention,
            "app_name": app_name,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S", self._started),  # when it started
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
            "event_streams": list(self._event_streams),
        }
        if convention is None:
            meta.pop("pose_convention")
        # Use the same clock as add_label, and only the first nonempty stream:
        # multiple streams describe the same take, not extra recorded time.
        first, last = 0.0, 0.0
        for timestamps in self.ts_stores.values():
            if timestamps.shape[0]:
                first, last = float(timestamps[0]), float(timestamps[-1])
                break
        meta["duration_s"] = max(0.0, last - first)
        seconds: dict[str, float] = {}
        if class_names and self.label_track:
            for i, event in enumerate(self.label_track):
                if not 0 <= event.class_index < len(class_names):
                    continue
                # Existing callers can supply an integer-valued numeric label.
                index = int(event.class_index)
                if index != event.class_index:
                    continue
                end = self.label_track[i + 1].timestamp if i + 1 < len(self.label_track) else last
                elapsed = max(0.0, min(last, end) - max(first, event.timestamp))
                if elapsed:
                    name = class_names[index]
                    seconds[name] = seconds.get(name, 0.0) + elapsed
            meta["class_seconds"] = seconds
        # Reuse the recorded-time keys, ordered by class index rather than event order.
        recorded = sorted(seconds, key=class_names.index) if class_names else []
        codes = _class_codes(class_names, class_codes) if class_names else {}
        self._recorded_codes = [codes[name] for name in recorded]
        if codes:
            meta["class_codes"] = codes
        if self.name:
            meta["name"] = self.name
        if self.participant:
            meta["participant"] = self.participant
        if self.extras:
            meta["extras"] = dict(self.extras)
        if class_names is not None:
            meta["class_names"] = list(class_names)
        if control_space is not None:
            meta["control_space"] = dict(control_space)
        if control_spaces:
            meta["control_spaces"] = {name: dict(space) for name, space in control_spaces.items()}
        labels = [
            {"timestamp": e.timestamp, "class_index": e.class_index} for e in self.label_track
        ]
        # A kill during a checkpoint must leave the previous JSON readable, rather
        # than truncating the only metadata from which recovery can open the arrays.
        for filename, value in (("labels.json", labels), ("meta.json", meta)):
            target = self.path / filename
            temporary = self.path / (filename + ".tmp")
            temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
            os.replace(temporary, target)

    def pack_to_zip(self) -> Path:
        """Pack the session folder into one ``<ID>_<YYYYMMDD-HHMM>_<what>.mg.zip``.

        ``<what>`` comes from `take_stem`: the recorded classes' codes (``R+F``,
        the first three and a count past 40 characters) and the `name`, or
        ``free``, ``guided`` or ``follow-F`` for a take in ``predictions/``.
        ``-2``, ``-3`` … are added only when that whole name is taken.

        Uses ZIP_STORED: zarr chunks are already compressed internally, so an outer
        compression layer would add CPU for little gain.
        """
        self.freeze()
        # zarr v3 arrays expose no explicit close, so drop refs and force a GC to
        # release the chunk-file handles. Required on Windows: the later
        # rmtree/replace fail with WinError 32 while any handle into the folder
        # is still open.
        self.stores.clear()
        self.ts_stores.clear()
        gc.collect()

        stem = take_stem(self._stem, self.kind, getattr(self, "_recorded_codes", []), self.name)
        # Named after the folder, which no other live take shares.
        tmp_path = self.path.with_name(self.path.name + ARCHIVE_SUFFIX + ".tmp")
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
            # Guarded: a session recorded with no connected stream has no arrays
            # to verify, and a `ZipStore` that never opened one raises
            # `AttributeError: _lock` on close. Reachable from the UI — Record
            # before Connect gives exactly this session — so it must pack, not
            # blow up in the finalise thread and report "Pack failed".
            if self._streams_info:
                store = zarr.storage.ZipStore(tmp_path, mode="r")
                try:
                    for name in self._streams_info:
                        zarr.open_array(store=store, path=f"{name}.zarr", mode="r")
                finally:
                    store.close()
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        zip_path = _claim_path(self.path.parent, stem, ARCHIVE_SUFFIX)
        try:
            # os.replace (not Path.rename): Windows rename refuses an existing
            # destination, and the claimed name exists, empty.
            os.replace(tmp_path, zip_path)
        except Exception:
            zip_path.unlink(missing_ok=True)
            raise
        PACKED_FOLDERS[self.path.resolve()] = zip_path
        _robust_rmtree(self.path)
        self.path = zip_path
        return zip_path

    def discard(self) -> None:
        """Delete this session's folder and everything recorded into it.

        Releases Zarr handles before removal, as `pack_to_zip` does. Windows
        cannot remove the folder while any chunk file remains open.
        """
        self.freeze()
        self.stores.clear()
        self.ts_stores.clear()
        gc.collect()
        _robust_rmtree(self.path)

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

        Closes the ``ZipStore`` opened by [`open_session_store`][] for a
        ``.mg.zip`` and drops the array references. Safe to call more than
        once. On Windows an open ``ZipStore`` keeps the archive locked, so
        close the session before moving or deleting the ``.mg.zip``. Use
        ``with open_session_store(p) as s: ...`` for automatic closure.
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
