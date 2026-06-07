from __future__ import annotations

import json
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SessionWidgetState:
    sessions: list[dict] = field(default_factory=list)
    folder_dialog: object | None = None
    last_load_msg: str = ""
    deactivated_classes: set[int] = field(default_factory=set)


_states: dict[str, SessionWidgetState] = {}


def get_state(widget_id: str) -> SessionWidgetState:
    return _states.setdefault(widget_id, SessionWidgetState())


def scan_sessions(base_path: str) -> list[dict]:
    """Find all session folders and .session.zip archives with meta.json."""
    base = Path(base_path)
    sessions = []
    if not base.exists():
        return sessions
    for d in sorted(base.iterdir(), reverse=True):
        row = _session_row(d)
        if row is not None:
            sessions.append(row)
    return sessions


def _session_row(path: Path) -> dict | None:
    try:
        if path.is_dir() and (path / "meta.json").exists():
            meta = json.loads((path / "meta.json").read_text())
            labels_file = path / "labels.json"
            labels = json.loads(labels_file.read_text()) if labels_file.exists() else []
        elif path.is_file() and path.name.endswith(".session.zip"):
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
                if "meta.json" not in names:
                    return None
                meta = json.loads(zf.read("meta.json"))
                labels = json.loads(zf.read("labels.json")) if "labels.json" in names else []
        else:
            return None

        streams_meta = meta.get("streams", {})
        return {
            "path": str(path),
            "name": path.name,
            "date_str": _date_str(meta, path),
            "streams_str": _streams_str(streams_meta),
            "n_labels": len(labels),
            "label_counts": _label_counts(labels),
            "streams": list(streams_meta.keys()),
            "class_names": list(meta.get("class_names") or []),
            "selected": False,
        }
    except Exception:
        return None


def _label_counts(labels: list[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for lbl in labels:
        if not isinstance(lbl, dict):
            continue
        ci = lbl.get("class_index", -1)
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
    if any(s["path"] == path for s in state.sessions):
        return
    for row in scan_sessions(str(Path(path).parent)):
        if row["path"] == path:
            row["selected"] = True
            state.sessions.insert(0, row)
            break


def load_session_files(state: SessionWidgetState, paths: list[str]) -> None:
    """Load selected paths from the native file picker into widget state."""
    existing_paths = {s["path"] for s in state.sessions}
    added = 0
    by_parent: dict[str, list[str]] = defaultdict(list)
    for path_str in paths:
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
