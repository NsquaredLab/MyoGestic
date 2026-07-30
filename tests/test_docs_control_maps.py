"""Every `[dofs]` block in the docs must be a mapping a reader could actually use.

`tests/test_docs.py` parses and runs the *Python* blocks. The TOML blocks were unchecked,
and a mapping can be perfectly valid TOML, load without complaint, resolve against a
manifest — and still be refused the moment a target tries to route it, because two aliases
named the same control. That shipped on two pages. It is exactly the failure a reader hits
first, since the docs are what they copy.

So each block is taken the whole way: load, resolve against the manifest, and bind to real
targets — which is where the routing conflict surfaces.

The manifest is the **union** of what the shipped targets export, and both are bound,
because the docs now show one file naming a finger and a key in the same table. A VHI-only
manifest would fail those pages for the wrong reason: not "this mapping is wrong" but "the
test does not know about half of it".
"""

from __future__ import annotations

import pathlib
import tomllib

import pytest

from myogestic.controls import Capability, ControlBus, load_control_map, resolve
from myogestic.keyboard import KeyboardTarget, keyboard_capabilities
from myogestic.vhi import VhiTarget

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"

#: VHI's manifest with its **channels**, which is the part that matters here: the short
#: and axis forms of a digit are two addresses on one channel, so a mapping can name two
#: distinct addresses and still be a conflict. Kept in step by tests/test_v2_contract.py.
CHANNELS = {"thumb": 0, "thumb.abduction": 1, "index": 2, "middle": 3, "ring": 4, "little": 5}
VHI_MANIFEST = [
    *(
        Capability(f"vhi.prediction.{form}", "continuous", -1.0, 1.0, 0.0, channel=channel)
        for digit, channel in CHANNELS.items()
        for form in ({digit, f"{digit}.flexion"} if "." not in digit else {digit})
    ),
    Capability(
        "vhi.control.gesture",
        "discrete",
        states=("Rest", "Fist", "Pointing"),
        rest_state="Rest",
    ),
]


#: Everything the shipped targets export. A block may name controls on either.
MANIFEST = [*VHI_MANIFEST, *keyboard_capabilities()]


def _dof_blocks() -> list[tuple[str, int, str]]:
    """Every fenced ```toml block containing a `[dofs]` table, with where it came from."""
    found = []
    for page in sorted(DOCS.rglob("*.md")):
        if "superpowers" in page.parts:  # plans and specs are records, not instructions
            continue
        lines = page.read_text().splitlines()
        start = None
        for number, line in enumerate(lines, 1):
            if start is None and line.strip().startswith("```toml"):
                start = number
            elif start is not None and line.strip() == "```":
                block = "\n".join(lines[start : number - 1])
                if "[dofs]" in block or "= \"vhi." in block:
                    found.append((str(page.relative_to(DOCS)), start, block))
                start = None
    return found


BLOCKS = _dof_blocks()


def test_the_docs_actually_contain_mapping_examples():
    """A rename or a fence style change must not silently empty this suite."""
    assert BLOCKS, "no ```toml [dofs] blocks found — has the docs' TOML moved?"


@pytest.mark.parametrize(
    "page,line,block", BLOCKS, ids=[f"{p}:{n}" for p, n, _ in BLOCKS]
)
def test_a_documented_mapping_loads_resolves_and_routes(page, line, block):
    where = f"{page}:{line}"
    raw = tomllib.loads(block)
    if "dofs" not in raw:  # a fragment showing one entry, not a whole file
        raw = {"dofs": raw}
    controls = resolve(load_control_map(raw), MANIFEST)
    # Binding is the point: `resolve` cannot see a routing conflict, because two aliases
    # sharing a control is only wrong once something has to put them on one wire. The
    # keyboard target is left **disarmed**, which is its default — it binds and claims its
    # aliases without any way to press anything, so this suite cannot type.
    bus = ControlBus(
        controls,
        targets=[VhiTarget(_Outlet(), client=_Client()), KeyboardTarget()],
        hz=50,
    )
    bus.stop()
    assert controls.dofs, where


class _Outlet:
    """Stands in for an LSL outlet: enough for a target to bind and rest."""

    n_channels = 9

    def push(self, frame) -> None: ...

    def flush(self) -> None: ...

    def stop(self) -> None: ...


class _Reply:
    """An accepted declaration. Channels come from the manifest, so nothing else is read."""

    accepted = True
    verdicts = ()
    continuous_encoding = 1  # CANONICAL
    continuous_channel_order = ()
    standard_version = "1"
    control_pose_stream_name = ""
    control_pose_channel_order = ()
    control_pose_encoding = 0


class _Client:
    """A canonical client that answers the manifest and accepts every declaration."""

    def capabilities(self):
        return VHI_MANIFEST

    def declare(self, controls, client_name="", control_pose=""):
        return _Reply()

    def set_control(self, continuous=None, discrete=None) -> None: ...


def test_the_check_would_have_caught_the_defect_it_was_written_for():
    """The mapping two doc pages actually shipped: three aliases on one control.

    Without this, the suite above could pass by never reaching the conflict at all.
    """
    shipped = {
        "dofs": {
            "my_index": "vhi.prediction.index",
            "fist": ["vhi.prediction.index", "vhi.prediction.middle"],
        }
    }
    controls = resolve(load_control_map(shipped), VHI_MANIFEST)
    with pytest.raises(ValueError, match="both map to"):
        ControlBus(controls, targets=[VhiTarget(_Outlet(), client=_Client())], hz=50)


def test_a_conflict_between_the_short_and_axis_form_is_caught_too():
    """`vhi.prediction.thumb` and `vhi.prediction.thumb.flexion` are one channel.

    Two different addresses, so only a channel-aware check sees it — which is why the
    manifest above carries channels rather than just names.
    """
    aliased = {
        "dofs": {
            "a": "vhi.prediction.thumb",
            "b": "vhi.prediction.thumb.flexion",
        }
    }
    controls = resolve(load_control_map(aliased), VHI_MANIFEST)
    with pytest.raises(ValueError, match="both map to"):
        ControlBus(controls, targets=[VhiTarget(_Outlet(), client=_Client())], hz=50)
