"""Validate and explain **any** TOML control map — yours, not this repository's.

    uv run --extra grpc python tools/inspect_control_map.py path/to/your.toml

Point it at a file and it says what that file declares: every alias, where each one
sends its value, the weight each target gets, and the gates you wrote. Then, if a target
is reachable, it resolves the map against that target's own manifest and says what each
alias actually *became* — which is where the semantics come from, so it is also where a
wrong address, a duplicated control, or an unrenderable configuration shows up.

With no target running it still checks everything a file alone can be checked for, and
says so rather than pretending. Exit status is 0 when the file is usable, 1 when it is
not, so this works in a pre-commit hook or CI as well as by hand.

Reads one file and, at most, asks a local target what it exports. Writes nothing.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tomllib

RULE = "─" * 78


def _load(path: pathlib.Path):
    """Read and structurally validate the file, or explain why it cannot be used."""
    from myogestic.controls import load_control_map

    if not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        return None
    if path.is_dir():
        print(f"error: {path} is a directory, not a control map", file=sys.stderr)
        return None
    try:
        with path.open("rb") as handle:  # "rb" — tomllib requires binary
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        print(f"error: {path} is not valid TOML\n  {exc}", file=sys.stderr)
        return None

    if "dofs" not in raw:
        tables = ", ".join(sorted(raw)) or "nothing"
        print(
            f"error: {path} has no [dofs] table (found: {tables}).\n"
            f"  A control map maps your own output names onto controls a target\n"
            f"  declares:\n\n    [dofs]\n    my_index = \"vhi.prediction.index\"",
            file=sys.stderr,
        )
        return None

    try:
        return load_control_map(raw)
    except ValueError as exc:
        # load_control_map accumulates every fault rather than stopping at the first,
        # so print all of them — fixing one at a time is the slow way.
        print(f"{path} is not a usable control map:\n", file=sys.stderr)
        for line in str(exc).splitlines():
            print(f"  {line}", file=sys.stderr)
        return None


def _describe(control_map) -> None:
    """Print what the file itself says, before any target is involved."""
    print(f"\n{RULE}\nDeclared in the file\n{RULE}")
    width = max(len(alias) for alias in control_map.bindings)
    for alias, binding in control_map.bindings.items():
        gates = []
        if binding.threshold_fraction is not None:
            gates.append(f"threshold_fraction={binding.threshold_fraction}")
        if binding.debounce_s:
            gates.append(f"debounce_s={binding.debounce_s}")
        suffix = f"   [{', '.join(gates)}]" if gates else ""

        if len(binding.targets) == 1:
            ref = binding.targets[0]
            weight = f" x{ref.weight}" if ref.weight != 1.0 else ""
            print(f"  {alias:{width}}  ->  {ref.address}{weight}{suffix}")
        else:
            print(f"  {alias:{width}}  ->  {len(binding.targets)} controls{suffix}")
            for ref in binding.targets:
                weight = f"x{ref.weight}" if ref.weight != 1.0 else "x1.0"
                print(f"  {' ' * width}      {weight:>6}  {ref.address}")

    grouped = [a for a, b in control_map.bindings.items() if len(b.targets) > 1]
    print(
        f"\n  {len(control_map.bindings)} alias(es), "
        f"{len(control_map.addresses())} distinct target control(s), "
        f"{len(grouped)} fanning out to more than one."
    )
    print("  The left column is yours. The right belongs to the target, which is also")
    print("  what decides whether an address takes a number or a held state — so the")
    print("  next section needs one running.")


def _manifest():
    """Ask a local target what it exports, or return None with a reason printed."""
    try:
        from myogestic.vhi import virtual_hand
    except ImportError as exc:  # pragma: no cover - depends on the [grpc] extra
        print(f"  (no gRPC support installed: {exc})")
        return None, None

    client = virtual_hand().control_client()
    capabilities = client.capabilities()
    if capabilities is None:
        print("  No target is running, so there is nothing to resolve against.")
        print("  Everything above is still checked. What needs a target: whether each")
        print("  address exists, what kind it is, its range, and its states.")
        client.stop()
        return None, None
    return capabilities, client


def _resolve(control_map, capabilities) -> bool:
    """Resolve against the manifest and report what each alias became."""
    from myogestic.controls import resolve

    print(f"  The target exports {len(capabilities)} controls.\n")
    try:
        controls = resolve(control_map, capabilities)
    except ValueError as exc:
        print("  This map cannot be used against that target:\n", file=sys.stderr)
        for line in str(exc).splitlines():
            print(f"  {line}", file=sys.stderr)
        return False

    width = max(len(alias) for alias in controls.dofs)
    for alias, dof in controls.dofs.items():
        if hasattr(dof, "states"):
            print(
                f"  {alias:{width}}  HELD STATE  {list(dof.states)[:4]}"
                f"{'...' if len(dof.states) > 4 else ''}  rest={dof.rest!r}"
            )
            if dof.debounce_s:
                print(f"  {' ' * width}    a state must hold {dof.debounce_s}s to count")
        else:
            gate = ""
            if dof.threshold_fraction is not None:
                gate = (
                    f"  gated: a probability >= {dof.threshold_fraction} becomes 1, "
                    f"below it 0"
                )
            print(f"  {alias:{width}}  NUMBER  [{dof.lo:+.1f}, {dof.hi:+.1f}]{gate}")
            for ref in controls.routes[alias]:
                print(f"  {' ' * width}    x{ref.weight:<5} -> {ref.address}")
    print("\n  Every kind, range and state above came from the target, not the file.")
    return _check_for_collisions(controls, capabilities)


def _check_for_collisions(controls, capabilities) -> bool:
    """Report two aliases landing on one physical control.

    `resolve` cannot see this: it checks each address one at a time and every address
    here is real. Two aliases reaching one address is a fact about the *set*, so it only
    surfaces when something has to drive both at once, which is at bind time inside a
    running application. Computed here from the manifest the target already sent, rather
    than by declaring anything to it: a validator must not change what it inspects.
    """
    rendered = {
        cap.address for cap in capabilities if getattr(cap, "kind", "") == "continuous"
    }
    claims: dict[str, set[str]] = {}
    for alias, refs in controls.routes.items():
        if hasattr(controls.dofs[alias], "states"):
            continue  # a held state travels over gRPC, not on a stream
        for ref in refs:
            if ref.address in rendered:
                claims.setdefault(ref.address, set()).add(alias)

    clashes = {address: owners for address, owners in claims.items() if len(owners) > 1}
    if not clashes:
        return True

    print("\n  But two aliases would land on the same control:\n", file=sys.stderr)
    for address, owners in sorted(clashes.items()):
        print(f"  {address}: {', '.join(repr(a) for a in sorted(owners))}", file=sys.stderr)
    print(
        "\n  One control cannot take two outputs. Remove one, or fan a single output\n"
        "  out to several controls instead.",
        file=sys.stderr,
    )
    return False


def main(argv: list[str] | None = None) -> int:
    """Validate one control map; return 0 if it is usable."""
    parser = argparse.ArgumentParser(
        description="Validate and explain a TOML control map.",
        epilog="With a target running it also resolves the map against what that "
        "target exports.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="examples/controls/hand.toml",
        # Kept as a string, not converted by argparse: `pathlib.Path("")` is `.`, which
        # would turn a blank prompt into "that is a directory" instead of "you gave me
        # nothing". VS Code passes a prompt's value through even when it is left blank.
        help="the TOML file to inspect (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    if not args.path.strip():
        print(
            "error: no path given.\n"
            "  Pass a TOML control map, or leave the argument off to use\n"
            "  examples/controls/hand.toml.",
            file=sys.stderr,
        )
        return 1

    path = pathlib.Path(args.path.strip()).expanduser()
    print(f"{RULE}\nControl map: {path}\n{RULE}")

    control_map = _load(path)
    if control_map is None:
        return 1
    if not control_map.bindings:
        print("  [dofs] is empty — nothing is declared.", file=sys.stderr)
        return 1

    _describe(control_map)

    print(f"\n{RULE}\nResolved against a live target\n{RULE}")
    capabilities, client = _manifest()
    if capabilities is None:
        print(f"\n{path.name} is structurally valid.")
        return 0
    try:
        ok = _resolve(control_map, capabilities)
    finally:
        client.stop()
    print(f"\n{path.name} {'is usable against this target.' if ok else 'was refused.'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
