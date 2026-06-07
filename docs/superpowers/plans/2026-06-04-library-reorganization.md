# MyoGestic Library Reorganization Plan

> **For agentic workers:** This is a **refactor** plan — behavior must not change. There are no new failing-tests-first; each task is verified by the **existing** test suite staying green plus an examples import smoke-check. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Tidy the package layout (group the session implementation, slim `core.py`, clarify `ml`/`models`, document `tools/` audiences, group VHI modules) **without breaking any public import path**.

**Architecture:** Internal-only moves first (session subpackage, core helper extraction), then path-affecting moves. **Backwards compatibility is NOT required** — clean breaks are fine. When a path changes, move the file and update **every in-repo caller** (examples + tests), then delete the old path. No compatibility shims.

**Tech stack:** Python 3.12+, `uv`, pytest. Run tests with `uv run pytest`.

**Scope decisions (agreed):**
- #1 `session/` subpackage — yes.
- #2 slim `core.py` — yes.
- #3 keep `myogestic.models` public; dedup persistence; clarify docs.
- #4 `tools/` — **docs-only** (do NOT move `emg_generator.py`/`lsl_dummy.py`; the `-m` calls + examples depend on the path).
- #5 `vhi/` grouping — yes, **clean break** (no shim): move the modules and update all callers (6 examples + tests + `install_vhi` + widgets); drop `myogestic.interfaces`.

**Packaging:** one combined PR/branch (`refactor/library-organization`), one commit per task.

**Global invariant — run after every task:**
```bash
uv run pytest -q                      # must stay green — main already includes PR #7's stale-test fixes, so 0 failures is the baseline
# examples import smoke-check (no hardware/GUI; just import-parse):
for f in $(git ls-files 'examples/**/*.py'); do uv run python -c "import ast,sys; ast.parse(open('$f').read())" || echo "PARSE FAIL $f"; done
```
> Note: PR #7 (stale `test_interfaces.py`/`test_public_api.py` fixes) is **merged into `main`**, so the baseline is a fully green suite — any failure during this refactor is something we introduced.

---

## Task 1: `session/` subpackage

Group the session facade + its three private modules into one package. Public path `myogestic.session.*` is unchanged.

**Files:**
- Move: `myogestic/_session_core.py` → `myogestic/session/_core.py`
- Move: `myogestic/_session_io.py` → `myogestic/session/_io.py`
- Move: `myogestic/_session_windows.py` → `myogestic/session/_windows.py`
- Move: `myogestic/session.py` → `myogestic/session/__init__.py`
- Modify: `tests/test_recording_race.py`, `tests/test_session_pack.py`

- [ ] **Step 1: Create the package and move files (preserve history)**

```bash
mkdir -p myogestic/session
git mv myogestic/_session_core.py    myogestic/session/_core.py
git mv myogestic/_session_io.py      myogestic/session/_io.py
git mv myogestic/_session_windows.py myogestic/session/_windows.py
git mv myogestic/session.py          myogestic/session/__init__.py
```

- [ ] **Step 2: Fix intra-package imports to relative**

In `myogestic/session/__init__.py` change the three absolute imports:
```python
from myogestic.session._core import LabelEvent, Recording, Session
from myogestic.session._io import open_session_store
from myogestic.session._windows import iter_aligned_windows, iter_labeled_windows
```
In `myogestic/session/_io.py`:
```python
from myogestic.session._core import LabelEvent, Session
```
In `myogestic/session/_windows.py`:
```python
from myogestic.session._io import open_session_store
```
(`__all__` in `__init__.py` is unchanged.)

- [ ] **Step 3: Update the two tests that used the private path**

`tests/test_recording_race.py`:
```python
from myogestic.session import Session
```
`tests/test_session_pack.py` (it monkeypatches `sc.time.strftime`, so it needs the module object):
```python
import myogestic.session._core as sc
```

- [ ] **Step 4: Check for any other references to the old private modules**

Run: `git grep -n "_session_core\|_session_io\|_session_windows" -- '*.py'`
Expected: only matches inside `myogestic/session/` and the two updated tests. Fix any stragglers.

- [ ] **Step 5: Verify**

Run the global invariant (pytest + examples parse). Also:
`uv run python -c "from myogestic.session import Session, Recording, LabelEvent, open_session_store, iter_labeled_windows, iter_aligned_windows; print('session facade ok')"`
Expected: green, no import errors.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: group session implementation into a session/ subpackage"
```

---

## Task 2: Slim `core.py` — extract platform/asset helpers

Move the incidental asset/icon/platform helpers (used only inside `core.py`) into a private `_platform.py`.

**Files:**
- Create: `myogestic/_platform.py`
- Modify: `myogestic/core.py`

- [ ] **Step 1: Create `myogestic/_platform.py`**

Move the three functions verbatim from `core.py` (`_assets_folder`, `_register_assets_folder`, `_try_set_macos_dock_icon`) plus the imports they need (e.g. `os`, `platform`, `pathlib`, the hello_imgui import they use). Give it a module docstring:
```python
"""Platform / asset-folder helpers for the App runtime (macOS dock icon,
hello_imgui asset registration). Extracted from core.py to keep App focused."""
```

- [ ] **Step 2: Import them in `core.py` and delete the originals**

At the top of `core.py` add:
```python
from myogestic._platform import (
    _assets_folder,
    _register_assets_folder,
    _try_set_macos_dock_icon,
)
```
Delete the three function definitions from `core.py`. (Call sites inside `core.py` are unchanged — same names.)

- [ ] **Step 3: Verify**

Run the global invariant. Also confirm the app entry imports:
`uv run python -c "from myogestic import App; print('core ok')"`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: extract platform/asset helpers from core.py into _platform.py"
```

---

## Task 3: Dedup model persistence + clarify `ml`/`models` docs

Today there are two model-persistence pairs: `myogestic.models.save_model/load_model` (joblib) and `myogestic.ml.save_pickle/load_pickle` (pickle, wired as the `pipeline.save_model` hook). Make **`models.save_model/load_model` the single implementation** and have `ml` re-export them under the existing names, so both public names keep working with one behavior.

**Files:**
- Modify: `myogestic/ml/persistence.py`
- Modify: `myogestic/ml/__init__.py` (docstring cross-ref), `myogestic/models/__init__.py` (docstring cross-ref)

- [ ] **Step 1: Make `ml/persistence.py` re-export the canonical helpers**

Replace the bespoke pickle bodies of `save_pickle`/`load_pickle` with thin wrappers over the joblib helpers so there is one implementation:
```python
"""Model-persistence hooks for ``pipeline.save_model`` / ``pipeline.load_model``.

Single implementation lives in ``myogestic.models`` (joblib-based, handles
picklable estimators incl. NumPy-heavy ones). These names are kept for the
pipeline hook API and back-compat.
"""
from pathlib import Path
from typing import Any

from myogestic.models import load_model, save_model


def save_pickle(model: Any, path: str | Path) -> str:
    return save_model(model, str(path))


def load_pickle(path: str | Path) -> Any:
    return load_model(str(path))
```
> Verify `myogestic.ml.__init__` still re-exports `save_pickle`/`load_pickle` (it does today); keep those exports so `from myogestic.ml import save_pickle, load_pickle` is unchanged.

- [ ] **Step 2: Add cross-reference docstrings**

In `myogestic/ml/__init__.py` docstring, add one line: *"For estimator constructor recipes (CatBoost/sklearn) and model persistence, see `myogestic.models`."*
In `myogestic/models/__init__.py` docstring, add one line: *"For the training/predict pipeline lifecycle that consumes these models, see `myogestic.ml`."*

- [ ] **Step 3: Verify behavior unchanged (round-trip)**

Run the global invariant, then `uv run pytest tests/test_models.py tests/test_ml.py -q` (these cover persistence). Also a quick round-trip:
```bash
uv run python -c "
from myogestic.ml import save_pickle, load_pickle
import tempfile, os
p = os.path.join(tempfile.mkdtemp(), 'm.joblib')
save_pickle({'w':[1,2,3]}, p); print('roundtrip:', load_pickle(p))
"
```
Expected: `roundtrip: {'w': [1, 2, 3]}`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: single model-persistence implementation; clarify ml vs models"
```

---

## Task 4: `tools/` audience documentation (docs-only)

No file moves. Clarify that `tools/` mixes an end-user installer with dev/test signal generators.

**Files:**
- Create: `myogestic/tools/README.md`

- [ ] **Step 1: Write `myogestic/tools/README.md`**

```markdown
# myogestic.tools

Two audiences live here:

- **End-user:** `install_vhi.py` — downloads the Virtual Hand Interface release
  binary (`python -m myogestic.tools.install_vhi`, console script
  `myogestic-install-vhi`).
- **Development / testing:** `emg_generator.py` and `lsl_dummy.py` — synthetic
  LSL signal generators used by the `examples/` and for local testing
  (`python -m myogestic.tools.emg_generator`). Not needed for normal use.

These intentionally share the `myogestic.tools` namespace; the `-m` entry points
and example imports depend on these paths, so they are not relocated.
```

- [ ] **Step 2: Verify + commit**

Run the global invariant (no code changed). Then:
```bash
git add -A
git commit -m "docs: clarify the two audiences of myogestic.tools"
```

---

## Task 5: `vhi/` subpackage (clean break — no shim)

Group the VHI integration (`interfaces`, the gRPC client, the generated stubs) into `myogestic/vhi/`. `myogestic.interfaces` is **removed**; all callers move to `myogestic.vhi.interfaces`.

**Files:**
- Move: `myogestic/interfaces.py` → `myogestic/vhi/interfaces.py`
- Move: `myogestic/_vhi_client.py` → `myogestic/vhi/_client.py`
- Move: `myogestic/_proto/` → `myogestic/vhi/_proto/`
- Create: `myogestic/vhi/__init__.py`
- Modify (callers): `myogestic/widgets/vhi_movement_palette.py`, `myogestic/widgets/vhi_movement_panel.py`, `myogestic/tools/install_vhi.py`, `tools/gen_proto.py`, **all 6 `examples/synthetic/emg_*.py`**, **`tests/test_interfaces.py`**

- [ ] **Step 1: Move files (preserve history)**

```bash
mkdir -p myogestic/vhi
git mv myogestic/interfaces.py  myogestic/vhi/interfaces.py
git mv myogestic/_vhi_client.py myogestic/vhi/_client.py
git mv myogestic/_proto         myogestic/vhi/_proto
```

- [ ] **Step 2: Create `myogestic/vhi/__init__.py`**

```python
"""Virtual Hand Interface (VHI) integration: output-interface registry, the
gRPC control client, and the generated protobuf stubs."""
from myogestic.vhi.interfaces import InterfaceSpec, virtual_hand

__all__ = ["InterfaceSpec", "virtual_hand"]
```
> Confirm the actual public names exported by the old `interfaces.py` (`InterfaceSpec`, `virtual_hand`, and any others) and list them here.

- [ ] **Step 3: Update internal imports**

- In `myogestic/vhi/interfaces.py`: the lazy `from myogestic._vhi_client import VhiControlClient` becomes `from myogestic.vhi._client import VhiControlClient`.
- In `myogestic/vhi/_client.py`: `from myogestic._proto ...` → `from myogestic.vhi._proto ...`.
- In `myogestic/widgets/vhi_movement_palette.py` and `vhi_movement_panel.py`: `from myogestic._vhi_client import ...` → `from myogestic.vhi._client import ...`.
- In `myogestic/tools/install_vhi.py`: update its `from myogestic.interfaces import _default_install_root` (and any others) → `from myogestic.vhi.interfaces import ...`.
- In all 6 `examples/synthetic/emg_*.py`: `from myogestic.interfaces import virtual_hand` → `from myogestic.vhi import virtual_hand` (the new package re-exports it).
- In `tests/test_interfaces.py`: `from myogestic.interfaces import ...` → `from myogestic.vhi.interfaces import ...`. (Run `git grep -n "myogestic\.interfaces" -- '*.py'` to catch every site; there should be **zero** matches when done.)

- [ ] **Step 4: Fix the generated-proto import path**

The generated `myogestic_vhi_pb2_grpc.py` imports `myogestic_vhi_pb2` (and the package was referenced as `myogestic._proto.*`). After the move:
- In `tools/gen_proto.py`: change `PROTO_DIR = REPO_ROOT / "myogestic" / "_proto"` → `... / "myogestic" / "vhi" / "_proto"`, and update the docstring/comment references from `myogestic._proto.*` to `myogestic.vhi._proto.*`.
- **Confirmed:** `myogestic_vhi_pb2_grpc.py` uses a *relative* import (`from . import myogestic_vhi_pb2 as ...`), so the moved stubs need **no edit** — they resolve within their own package regardless of where it lives. (Still verify via the import check in Step 6.)

- [ ] **Step 5: Confirm the old path is fully removed (no shim)**

There is no `myogestic/interfaces.py` shim — the file was moved in Step 1 and all callers updated in Step 3. Verify nothing still references the old paths:
```bash
git grep -n "myogestic\.interfaces\|myogestic\._vhi_client\|myogestic\._proto\|from myogestic import interfaces" -- '*.py'
```
Expected: **zero** matches. Fix any straggler.

- [ ] **Step 6: Verify imports + grpc stubs resolve**

```bash
uv run python -c "from myogestic.vhi import virtual_hand, InterfaceSpec; print('vhi facade ok')"
uv run python -c "from myogestic.vhi.interfaces import virtual_hand, InterfaceSpec, _default_install_root; print('vhi.interfaces ok')"
uv run python -c "import myogestic.vhi._proto.myogestic_vhi_pb2 as pb; import myogestic.vhi._proto.myogestic_vhi_pb2_grpc as g; print('proto ok')" 2>&1 | tail -2 || echo "(grpc extra may be needed: uv run --extra grpc ...)"
```
Then the global invariant (pytest + examples parse). `tests/test_interfaces.py` now imports from `myogestic.vhi.interfaces`; it should pass (PR #7's fixes are in `main`).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor!: move VHI modules into myogestic/vhi/ (drop myogestic.interfaces)"
```
> The `!` marks a breaking change (removed public `myogestic.interfaces` path).

---

## Final verification & PR

- [ ] **Step 1: Full suite + examples + public API**

```bash
uv run pytest -q
uv run python -c "import myogestic; [__import__('builtins').__import__('myogestic')] ; from myogestic import App, Stream, StreamInfo, Source, Pipeline, Grid, Fr, Px, Context, AppState, EdgeTrigger, TrainingData; print('public API intact')"
for f in $(git ls-files 'examples/**/*.py'); do uv run python -c "import ast; ast.parse(open('$f').read())" || echo "FAIL $f"; done
```

- [ ] **Step 2: Confirm tree shape**

```bash
git diff --stat origin/main..HEAD
find myogestic -maxdepth 1 -name '*.py' | sort   # root should be slimmer: no _session_*, no _vhi_client; interfaces.py is now a shim
ls myogestic/session myogestic/vhi               # new packages exist
```

- [ ] **Step 3: Open the PR**

```bash
git push -u origin refactor/library-organization
gh pr create --base main --title "Refactor: tidy library organization (session/, vhi/, slim core, persistence dedup)" --body "<summary of the 5 items, the non-breaking shim strategy, and verification>"
```

## Risks & notes
- **Highest-risk task is #5** (proto import paths + the shim). If the generated stubs use a package-qualified import, Step 4 is essential; verify with the explicit import check before relying on the suite.
- Keep each task in its own commit so any single move can be reverted independently even though they ship as one PR.
- No production behavior changes anywhere — every change is a move, a re-export, or documentation. The existing suite is the safety net.
- After merge, consider a follow-up to migrate in-repo callers off the `myogestic.interfaces` shim to `myogestic.vhi.interfaces`, then drop the shim in a later major version.
