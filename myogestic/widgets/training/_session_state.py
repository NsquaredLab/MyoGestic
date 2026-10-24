from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
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


def get_state(widget_id: str) -> SessionWidgetState:
    return _states.setdefault(widget_id, SessionWidgetState())


def scan_sessions(base_path: str) -> list[dict]:
    """Find all session folders and .zip archives that contain a meta.json."""
    base = Path(base_path)
    sessions = []
    if not base.is_dir():
        return sessions
    for d in sorted(base.iterdir(), reverse=True):
        row = _session_row(d)
        if row is not None:
            sessions.append(row)
    return sessions


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
            "date_str": _date_str(meta, path),
            "streams_str": _streams_str(streams_meta),
            "n_labels": len(labels),
            "label_counts": _label_counts(labels),
            "streams": list(streams_meta.keys()),
            "class_names": list(meta.get("class_names") or []),
            "duration_s": float(meta.get("duration_s", 0.0)),
            "class_seconds": dict(meta.get("class_seconds") or {}),
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
    path = str(Path(path).resolve())  # match the resolved paths stored on rows
    if state.participant is None and any(s["path"] == path for s in state.sessions):
        return
    found = scan_sessions(str(Path(path).parent))
    recorded = next((row for row in found if row["path"] == path), None)
    if recorded is None:
        return
    # Packing can finish after the operator has switched participant.
    if state.participant is not None and recorded["participant"] != state.participant:
        return
    if state.participant:
        # A scan can see the folder while packing is still running. Drop that
        # vanished row once its archive arrives, retaining picks from elsewhere.
        parent = Path(path).parent
        found_paths = {row["path"] for row in found}
        state.sessions[:] = [
            row for row in state.sessions
            if Path(row["path"]).parent != parent or row["path"] in found_paths
        ]
    existing = {row["path"]: row for row in state.sessions}
    if path in existing:
        existing[path]["selected"] = True
    else:
        recorded["selected"] = True
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

    state.deactivated_classes &= classes_in_pool
    return classes_in_pool, classes_in_pool - state.deactivated_classes
