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
from myogestic.remote import RemoteTarget

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"

#: VHI's manifest, one address per control — exactly the spellings it advertises, and
#: nothing else. There is no second name for any of these: the bare digit where a digit
#: bends one way, an explicit axis where it does not. Kept in step by
#: tests/test_v2_contract.py.
ADDRESSES = (
    "thumb.flexion", "thumb.abduction", "index", "middle", "ring", "little",
    "wrist.flexion", "wrist.abduction", "wrist.rotation",
)
VHI_MANIFEST = [
    *(
        Capability(f"vhi.prediction.{address}", "continuous", -1.0, 1.0, 0.0)
        for address in ADDRESSES
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

#: The namespaces this suite has a manifest for. A page teaching a reader to write their
#: *own* target necessarily names addresses in a namespace nothing here exports, and
#: resolving those against this manifest would fail for the wrong reason — not "this mapping
#: is wrong" but "the test does not know what it points at". Inventing a manifest for them
#: would only test the invention, so those blocks are checked as far as `load_control_map`
#: and no further.
SHIPPED_NAMESPACES = {cap.address.split(".", 1)[0] for cap in MANIFEST}


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
    control_map = load_control_map(raw)
    foreign = sorted(
        {
            address.split(".", 1)[0]
            for address in control_map.addresses()
            if address.split(".", 1)[0] not in SHIPPED_NAMESPACES
        }
    )
    if foreign:
        pytest.skip(f"{where}: names {foreign}, which no shipped target exports")
    controls = resolve(control_map, MANIFEST)
    # Binding is the point: `resolve` cannot see a routing conflict, because two aliases
    # sharing a control is only wrong once something has to put them on one wire. The
    # keyboard target is left **disarmed**, which is its default — it binds and claims its
    # aliases without any way to press anything, so this suite cannot type.
    bus = ControlBus(
        controls,
        targets=[RemoteTarget(client=_Client(), interface=_Interface()), KeyboardTarget()],
        hz=50,
    )
    bus.stop()
    assert controls.dofs, where


class _Outlet:
    """Stands in for one control's LSL outlet: enough for a target to bind and rest."""

    def push(self, sample) -> None: ...

    def flush(self) -> None: ...

    def stop(self) -> None: ...


class _Interface:
    """Stands in for `virtual_hand()`: hands out one sink per address."""

    def stream_outlet(self, name, *, n_channels=None) -> _Outlet:
        return _Outlet()


class _Client:
    """A control client that answers the manifest — the whole contract now."""

    def capabilities(self):
        return VHI_MANIFEST

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
        ControlBus(controls, targets=[RemoteTarget(client=_Client(), interface=_Interface())], hz=50)


# There used to be a second conflict case here: `vhi.prediction.thumb` and
# `vhi.prediction.thumb.flexion` were two advertised names for one control, so a map could
# collide without any address repeating. That is gone at the source — a target
# advertises one spelling per control and gives each its own stream — so two aliases
# reaching one control now always means two aliases naming one address, which is what the
# test above checks.
