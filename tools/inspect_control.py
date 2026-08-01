"""A narrated walk through the control standard, end to end.

Run it to *see* the system work rather than read about it:

    uv run --extra grpc python tools/inspect_control.py

Safe anywhere. With no Virtual Hand running it still loads the real config file and shows
what a mapping is *before* a target has answered — which is the design, not a degraded
mode. Launch a VHI first and the same script asks what it exports, resolves the mapping
against that, and drives a weighted fan-out onto the hand.

It creates a transient LSL outlet per stream the mapping names — one per DOF against a
VHI — and, if a VHI is up, moves its hand. It writes no files, changes no configuration,
and leaves the hand at rest.
"""

from __future__ import annotations

import pathlib
import time
import tomllib

import numpy as np

from myogestic.controls import ControlBus, load_control_map, resolve, substitute_rest
from myogestic.vhi import vhi_targets, virtual_hand

#: The real file a user copies and edits.
CONTROL_FILE = (
    pathlib.Path(__file__).resolve().parent.parent / "examples" / "controls" / "hand.toml"
)

#: The same form, driven by a classifier rather than a regressor.
CLASSIFIER_FILE = CONTROL_FILE.with_name("classification.toml")

RULE = "─" * 78


def heading(n: int, text: str) -> None:
    """Print a numbered section rule."""
    print(f"\n{RULE}\n{n}. {text}\n{RULE}")


def step_1_the_file():
    """Load the TOML. Two vocabularies meet, and neither owns the other."""
    heading(1, f"The declaration — {CONTROL_FILE.relative_to(CONTROL_FILE.parents[2])}")
    print("  The file, minus its comments:\n")
    for line in CONTROL_FILE.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            print("   " + line)

    # tomllib lives here, in the application, not in the library: load_control_map takes a
    # Mapping, so MyoGestic reads no configuration files. TOML is what a human wants to
    # edit, which is why the shipped example is TOML.
    with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
        control_map = load_control_map(tomllib.load(handle))

    print("\n  load_control_map(tomllib.load(f)) ->")
    for alias, binding in control_map.bindings.items():
        routes = ", ".join(
            ref.address + (f" x{ref.weight}" if ref.weight != 1.0 else "")
            for ref in binding.targets
        )
        gate = f"   debounce={binding.debounce_s}s" if binding.debounce_s else ""
        print(f"    {alias:14s} -> {routes}{gate}")

    print("\n  LEFT is yours: these aliases are your model's output names. Nothing")
    print("  prescribes them and nothing reads meaning out of them.")
    print("  RIGHT belongs to the target. Note what is absent: no channel numbers, and no")
    print("  kinds or ranges — whether an address takes a number or a held state is the")
    print("  target's to declare, so a mapping alone cannot say.")
    return control_map


def step_2_ask_the_target(client):
    """The manifest: what this target exports, in its own words."""
    heading(2, "Ask the target what it exports")
    capabilities = client.capabilities()
    if capabilities is None:
        print("  No target answered.")
        print("   - So the mapping stays UNRESOLVED, and that is correct rather than a")
        print("     failure: nothing here may invent what an address means.")
        print("   - An application that launches its own renderer therefore resolves")
        print("     *after* startup, not at import. Every shipped example does exactly")
        print("     that — see _ensure_vhi() in examples/synthetic/*.py.")
        print("\n  Launch a Virtual Hand and run this again to see steps 3 to 5.")
        return None

    print(f"  This target exports {len(capabilities)} controls, and describes each:\n")
    for cap in capabilities:
        if cap.kind == "continuous":
            where = f"channel {cap.channel}" if cap.channel >= 0 else "not streamed"
            print(f"    {cap.address:34s} number [{cap.lo:+.1f},{cap.hi:+.1f}]  {where}")
        else:
            print(f"    {cap.address:34s} held state, {len(cap.states)} of them")
    print("\n  Every semantic fact above came from the target. MyoGestic hard-codes none")
    print("  of it, so a build that grows a control needs no change on this side.")
    return capabilities


def step_3_resolve(control_map, capabilities):
    """Meaning arrives — from the target, not from here."""
    heading(3, "Resolve the mapping against it")
    controls = resolve(control_map, capabilities)
    for alias, dof in controls.dofs.items():
        if hasattr(dof, "states"):
            print(
                f"    {alias:14s} HELD STATE  {list(dof.states)[:3]}... "
                f"rest={dof.rest!r} debounce={dof.debounce_s}s"
            )
        else:
            routes = [(r.address.split(".")[-1], r.weight) for r in controls.routes[alias]]
            print(f"    {alias:14s} NUMBER  [{dof.lo:+.1f},{dof.hi:+.1f}] -> {routes}")
    print("\n  `gesture` became a held state because the target said its address is")
    print("  discrete. `fist` became one number reaching several controls. Neither of")
    print("  those facts is written in the file.")

    print("\n  An address this target does not export is refused by name:")
    try:
        resolve(
            load_control_map({"dofs": {"my_wrist": "vhi.prediction.wrist"}}), capabilities
        )
    except ValueError as exc:
        for line in str(exc).splitlines()[:2]:
            print("    " + line[:140])
    return controls


def step_4_drive(control_map, controls, client, capabilities):
    """A weighted fan-out on a real hand."""
    heading(4, "Drive it")
    fanned = [a for a, refs in controls.routes.items() if len(refs) > 1]
    weighted = [a for a in fanned if any(r.weight != 1.0 for r in controls.routes[a])]
    alias = (weighted or fanned or list(controls.routes))[0]
    print(f"  {alias!r} is one output reaching {len(controls.routes[alias])} controls:")
    for ref in controls.routes[alias]:
        print(f"    {ref.address:34s} weight {ref.weight}")

    # `vhi_targets` rather than a target built here: one target writes one stream, and how
    # many streams a map spans is the *renderer's* answer — a VHI publishes one per DOF,
    # another renderer may carry the whole map on one wider stream. `capabilities=` because
    # step 2 already asked, and asking twice would be a second answer to a settled question.
    targets = vhi_targets(control_map, virtual_hand(), client=client, capabilities=capabilities)
    bus = ControlBus(controls, targets=targets, hz=32)
    settled = all(target.negotiate() for target in targets)
    print(f"\n  vhi_targets() -> {len(targets)} target(s), one per stream; negotiate() -> {settled}")
    for target in targets:
        placed = ", ".join(
            f"{address} on channel {channel}"
            for channel, _alias, _weight, _lo, _hi, address in sorted(target._routed)
        )
        print(f"    {target._stream_name or '(no stream named)':38s} {placed or '—'}")
    print("  Nothing above was written here: the names, the grouping and the channels are")
    print("  all the manifest's, which is why a renderer can reshape its wire without this")
    print("  side changing.")

    rendered = _observe(bus, alias)
    if rendered is None:
        print("\n  (VHI_Predict was not readable, so nothing to show)")
    else:
        print(f"\n  commanded {alias}=1.0  ->  the hand rendered:")
        for channel, value in rendered:
            print(f"    channel {channel}: {value:+.2f}")
        print("  Each member got its own weight, then the target's own range. A weight")
        print("  scales a value; it cannot push one past what the target accepts.")
    bus.stop()
    print("\n  bus.stop() delivered rest and flushed it, so the hand released rather")
    print("  than freezing in its last pose. Each target built its own stream, so that")
    print("  released those too.")


def _observe(bus, alias) -> list[tuple[int, float]] | None:
    """Command the alias and read back what the hand actually rendered."""
    from mne_lsl.lsl import StreamInlet, resolve_streams

    inlet = None
    for stream in resolve_streams(timeout=4):
        if stream.name == "VHI_Predict":
            inlet = StreamInlet(stream)
            inlet.open_stream(timeout=5)
    if inlet is None:
        return None

    bus.push({alias: 1.0})
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        inlet.flush()
        time.sleep(0.4)
        data, stamps = inlet.pull_chunk(timeout=0.5)
        if len(stamps):
            frame = np.asarray(data)[-1]
            if abs(frame[:6]).max() > 0.5:
                return [(i, float(v)) for i, v in enumerate(frame[:6]) if abs(v) > 0.05]
    return None


def step_5_classification(capabilities):
    """A classifier reaching the same controls through the same mapping."""
    heading(5, f"Classification — {CLASSIFIER_FILE.name}")
    with CLASSIFIER_FILE.open("rb") as handle:
        controls = resolve(load_control_map(tomllib.load(handle)), capabilities)

    alias = next(a for a, d in controls.dofs.items() if d.threshold_fraction is not None)
    dof = controls.dofs[alias]
    print(f"  {alias!r} declares threshold_fraction = {dof.threshold_fraction}, so its input is")
    print("  read as a classifier's probability rather than a position:\n")
    for probability in (0.0, 0.49, 0.5, 0.73, 1.0):
        gated = substitute_rest(controls, {alias: probability})[alias]
        sent = ", ".join(
            f"{ref.address.split('.')[-1]}={ref.weight * gated:+.2f}"
            for ref in controls.routes[alias]
        )
        print(f"    p={probability:<5} -> activation {gated:.0f}  ->  {sent}")

    print("\n  Below the fraction the value is 0, at or above it 1. Nothing downstream ever")
    print("  sees the probability itself — a continuous address is a *position*, and 0.73")
    print("  there would claim the finger is 73% curled.")
    print("  From the gate on, it is an ordinary control value: the same weighted fan-out a")
    print("  regressor's output travels. Drop the threshold_fraction and this identical")
    print("  mapping serves a regressor emitting 0..1 directly.")


def step_6_commands():
    """Print the commands a reader can run themselves."""
    heading(6, "Commands you can run")
    print("""  This walkthrough, with no Virtual Hand (safe anywhere):
      uv run --extra grpc python tools/inspect_control.py

  Then launch a Virtual Hand and run it again to see the handshake:
      python -m myogestic.tools.install_vhi        # if you have not installed it
      # start VHI from any example's Launch button, or run the binary directly
      uv run --extra grpc python tools/inspect_control.py

  Confirm what the hand actually renders, per control, in signed degrees:
      uv run python tools/check_vhi_bridge.py

  A full application using all of this:
      uv run --extra examples --extra grpc python examples/synthetic/emg_regression.py

  The control files — copy and edit one:
      examples/controls/hand.toml                   a regressor
      examples/controls/classification.toml         a classifier, same mapping form

  The contracts themselves:
      myogestic/controls.py                        the standard
      myogestic/_controls_map.py                   aliases, addresses, resolution
      myogestic/vhi/_proto/myogestic_vhi.proto     the wire contract""")


def main() -> None:
    """Walk all six steps."""
    print(RULE)
    print("The control standard, end to end")
    print(RULE)
    control_map = step_1_the_file()

    client = virtual_hand().control_client()
    try:
        capabilities = step_2_ask_the_target(client)
        if capabilities is not None:
            controls = step_3_resolve(control_map, capabilities)
            step_4_drive(control_map, controls, client, capabilities)
            step_5_classification(capabilities)
    finally:
        client.stop()
    step_6_commands()
    print()


if __name__ == "__main__":
    main()
