from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from glob import escape
from pathlib import Path
from typing import cast

from myogestic.session._core import _read_session_metadata, _slug


@dataclass
class SessionWidgetState:
    sessions: list[dict] = field(default_factory=list)
    folder_dialog: object | None = None
    last_load_msg: str = ""
    deactivated_classes: set[int] = field(default_factory=set)
    participant: str | None = None


_states: dict[str, SessionWidgetState] = {}
_pending_packs: set[Path] = set()


def get_state(widget_id: str) -> SessionWidgetState:
    return _states.setdefault(widget_id, SessionWidgetState())


def set_session_saving(path: Path, saving: bool) -> None:
    """Track finalization before the pack thread creates its temporary archive."""
    if saving:
        _pending_packs.add(path.resolve())
    else:
        _pending_packs.discard(path.resolve())


def is_session_saving(base_path: str) -> bool:
    """Report pending takes in the folder this manager is showing."""
    base = Path(base_path).resolve()
    return any(path.parent == base for path in _pending_packs.copy())


def _packed_siblings(path: Path, suffix: str = ".session.zip") -> list[Path]:
    return sorted(p for p in path.parent.glob(f"{escape(path.name)}*{suffix}") if p.is_file())


def packed_session_path(path: Path) -> Path | None:
    """Find the archive that replaced a session folder, if it has finished."""
    if path.is_file():
        return None
    return next(iter(_packed_siblings(path)), None)


def scan_sessions(base_path: str) -> list[dict]:
    """Find saved takes, preferring archives to their source folders."""
    base = Path(base_path)
    sessions = []
    if not base.is_dir():
        return sessions
    for d in sorted(base.iterdir(), reverse=True):
        if d.is_dir() and (
            d.resolve() in _pending_packs
            or _packed_siblings(d)
            or _packed_siblings(d, ".session.zip.tmp")
        ):
            continue
        row = _session_row(d)
        if row is not None:
            sessions.append(row)
    return sessions


def reconcile_sessions(state: SessionWidgetState) -> None:
    """Follow packed folders, preserve their ticks, and drop vanished takes."""
    rows: dict[str, dict] = {}
    for row in state.sessions:
        path = Path(row["path"])
        packed = packed_session_path(path)
        if packed is not None:
            replacement = _session_row(packed)
            if replacement is None:
                continue
            replacement["selected"] = row["selected"]
            row = replacement
        elif not path.exists():
            continue
        if row["path"] in rows:
            rows[row["path"]]["selected"] |= row["selected"]
        else:
            rows[row["path"]] = row
    state.sessions[:] = rows.values()


def _session_row(path: Path) -> dict | None:
    try:
        entry = _read_session_metadata(path)
        if entry is None:
            return None
        meta, labels = entry

        streams_meta = meta.get("streams", {})
        return {
            # Resolved path so the same session dedups across spellings
            # (symlinks, /var vs /private/var on macOS, relative vs absolute).
            "path": str(path.resolve()),
            "name": path.name,
            # What the operator called this take, when they named it on Stop.
            "session_name": str(meta.get("name") or ""),
            "participant": _slug(str(meta.get("participant") or "")),
            "created": _created(meta.get("created")),
            "date_str": _date_str(meta, path),
            "streams_str": _streams_str(streams_meta),
            "n_labels": len(labels),
            "label_counts": _label_counts(labels),
            "streams": list(streams_meta.keys()),
            "class_names": list(meta.get("class_names") or []),
            "duration_s": float(meta.get("duration_s", 0.0)),
            "class_seconds": dict(meta.get("class_seconds") or {}),
            "drive": any(key in (meta.get("extras") or {}) for key in ("pipeline", "guided")),
            "guided": "guided" in (meta.get("extras") or {}),
            "selected": False,
        }
    except Exception:
        return None


def _label_counts(labels: list[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for lbl in labels:
        if not isinstance(lbl, dict):
            continue
        ci = cast("dict[str, object]", lbl).get("class_index", -1)
        counts[str(ci)] = counts.get(str(ci), 0) + 1
    return counts


def _date_str(meta: dict, path: Path) -> str:
    created = meta.get("created", "")
    try:
        from datetime import datetime

        return datetime.fromisoformat(created).strftime("%b %d %H:%M")
    except (ValueError, TypeError):
        return path.stem.replace("_", " ").replace("-", ":")[:16]


def _streams_str(streams_meta: dict) -> str:
    stream_parts = []
    for sname, sinfo in streams_meta.items():
        n_ch = sinfo.get("n_channels", "?")
        fs = sinfo.get("fs", 0)
        if len(streams_meta) == 1 and fs:
            stream_parts.append(f"{sname} {n_ch}ch {int(fs)}Hz")
        else:
            stream_parts.append(f"{sname} {n_ch}ch")
    return " + ".join(stream_parts) if stream_parts else "—"


def add_recorded_session(path: str, base_path: str = "sessions", title: str = "Sessions") -> None:
    """Register a freshly recorded session as selected."""
    widget_id = f"{title}_{base_path}"
    state = get_state(widget_id)
    reconcile_sessions(state)
    path = str(Path(path).resolve())  # match the resolved paths stored on rows
    if state.participant is None and any(s["path"] == path for s in state.sessions):
        return
    found = scan_sessions(str(Path(path).parent))
    # Explicit registration also handles a failed pack's retained folder,
    # while the pending marker still hides it from ordinary scans.
    recorded = _session_row(Path(path))
    if recorded is None:
        return
    # Packing can finish after the operator has switched participant.
    if state.participant is not None and recorded["participant"] != state.participant:
        return
    existing = {row["path"]: row for row in state.sessions}
    if path in existing:
        existing[path]["selected"] = not recorded["drive"]
    else:
        recorded["selected"] = not recorded["drive"]
        state.sessions.insert(0, recorded)
    if state.participant:
        # Refresh after each take without changing any existing selections.
        state.sessions.extend(
            row for row in found if row["path"] != path and row["path"] not in existing
        )


def load_session_files(state: SessionWidgetState, paths: list[str]) -> None:
    """Load selected paths from the native file picker into widget state."""
    existing_paths = {s["path"] for s in state.sessions}
    added = 0
    by_parent: dict[str, list[str]] = defaultdict(list)
    for raw in paths:
        # Resolve the picked path so it dedups against the already-listed
        # (also resolved) rows instead of being re-added under a different
        # spelling — e.g. the macOS dialog's /private/var vs a /var scan.
        path_str = str(Path(raw).resolve())
        if path_str not in existing_paths:
            by_parent[str(Path(path_str).parent)].append(path_str)

    picked = sum(len(v) for v in by_parent.values())
    for parent, wanted in by_parent.items():
        wanted_set = set(wanted)
        for row in scan_sessions(parent):
            if row["path"] in wanted_set:
                state.sessions.append(row)
                added += 1

    skipped = picked - added
    if added or skipped:
        msg = f"Loaded {added}"
        if skipped:
            msg += f" (skipped {skipped} non-session)"
        state.last_load_msg = msg


def class_pool_and_active(state: SessionWidgetState) -> tuple[set[int], set[int]]:
    """Return classes in selected sessions and the currently active subset."""
    classes_in_pool: set[int] = set()
    for row in state.sessions:
        if row["selected"]:
            for k in row.get("label_counts", {}):
                ci = int(k)
                if ci >= 0:
                    classes_in_pool.add(ci)

    return classes_in_pool, classes_in_pool - state.deactivated_classes


@dataclass(frozen=True)
class SelectionSummary:
    """A snapshot of selected takes and included gesture durations.

    Attributes
    ----------
    n_selected : int
        Number of checked takes, including takes with no labels.
    n_total : int
        Number of takes in the list, including files loaded from elsewhere.
    class_seconds : dict[str, float]
        Seconds per included gesture in checked takes. Older takes without
        duration metadata contribute zero seconds for their recorded labels.
    """

    n_selected: int
    n_total: int
    class_seconds: dict[str, float]


def row_gestures(row: dict, class_names: list[str] | None) -> list[tuple[int | None, str, float]]:
    """Resolve recorded names without inventing an index for an unknown name."""
    names = row.get("class_names") or class_names or []
    seconds = row.get("class_seconds", {})
    gestures = []
    for key in row.get("label_counts", {}):
        ci = int(key)
        if ci >= 0:
            name = names[ci] if ci < len(names) else f"c{ci}"
            # Duration metadata is authoritative about which named gestures occurred.
            if not seconds or name in seconds:
                gestures.append((ci, name, float(seconds.get(name, 0.0))))
    present = {name for _, name, _ in gestures}
    for name, elapsed in seconds.items():
        if name not in present:
            gestures.append((names.index(name) if name in names else None, name, float(elapsed)))
    return gestures


def selection_summary(state: SessionWidgetState, class_names: list[str] | None) -> SelectionSummary:
    """Read the same selected rows and class exclusions used for training."""
    seconds: dict[str, float] = defaultdict(float)
    selected = [row for row in state.sessions if row["selected"]]
    for row in selected:
        for ci, name, elapsed in row_gestures(row, class_names):
            if ci not in state.deactivated_classes:
                seconds[name] += elapsed
    return SelectionSummary(len(selected), len(state.sessions), dict(seconds))


@dataclass
class SessionGroup:
    key: str
    label: str
    rows: list[dict]
    default_open: bool = False


def _created(value: object) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value))
        return stamp.astimezone().replace(tzinfo=None) if stamp.tzinfo else stamp
    except ValueError:
        return None


def group_sessions(
    sessions: list[dict], base_path: str, *, today: date | None = None,
) -> list[SessionGroup]:
    """Group local takes by recorded day, then files loaded from elsewhere."""
    today = today or date.today()
    base = Path(base_path).resolve()
    groups: dict[str, SessionGroup] = {}
    for row in sorted(sessions, key=lambda r: r.get("created") or datetime.min, reverse=True):
        created = row.get("created")
        if Path(row["path"]).parent != base:
            key, label = "loaded", "Loaded"
        elif created is None:
            key, label = "undated", "Undated"
        else:
            day = created.date()
            key = day.isoformat()
            label = ("Today" if day == today else "Yesterday" if day == today - timedelta(days=1)
                     else day.strftime("%b %d"))
        groups.setdefault(key, SessionGroup(key, label, [])).rows.append(row)
    ordered = [g for k, g in groups.items() if k not in {"loaded", "undated"}]
    ordered.extend(groups[k] for k in ("undated", "loaded") if k in groups)
    if ordered:
        ordered[0].default_open = True
    return ordered
