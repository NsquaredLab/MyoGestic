"""The committed VS Code entries must actually run what they claim.

`.vscode/launch.json` is shipped configuration: someone presses F5 and expects a
window. Nothing else in this repository would notice if a `program` path went stale
after a rename, if an entry named a `preLaunchTask` that does not exist, or if the
interpreter it points at were one `uv` never creates — and each of those fails at the
press of the key, which is the worst place to find out.

What is checked here: the files parse, every target resolves, every task label
referenced exists, and every example that a configuration launches also has a
smoke test (`tests/test_examples.py`) proving it wires up. What is *not* checkable
here, and is documented in the file itself: whether a window opens, whether a
Virtual Hand answers, and whether a human watching the hand agrees with it.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAUNCH = ROOT / ".vscode" / "launch.json"
TASKS = ROOT / ".vscode" / "tasks.json"


def _read_jsonc(path: pathlib.Path) -> dict:
    """Parse VS Code's JSON-with-comments.

    Only whole-line `//` comments are stripped, which is why the files use only
    whole-line comments: a general strip would have to parse strings to avoid
    mangling a `//` inside one.
    """
    kept = [
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("//")
    ]
    return json.loads("\n".join(kept))


@pytest.fixture(scope="module")
def launch() -> dict:
    return _read_jsonc(LAUNCH)


@pytest.fixture(scope="module")
def tasks() -> dict:
    return _read_jsonc(TASKS)


def _resolve(value: str) -> pathlib.Path:
    """Expand the one VS Code variable these files use."""
    return pathlib.Path(value.replace("${workspaceFolder}", str(ROOT)))


def test_both_files_are_committed_not_just_present():
    """`.vscode/` is gitignored wholesale; these two are named back in."""
    import subprocess

    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", ".vscode/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert ".vscode/launch.json" in listed
    assert ".vscode/tasks.json" in listed


def test_the_files_parse(launch, tasks):
    assert launch["configurations"], "no configurations at all"
    assert tasks["tasks"], "no tasks at all"


def _configs(launch) -> list[dict]:
    return launch["configurations"]


def test_every_program_path_exists(launch):
    """The failure a rename causes, caught here instead of at F5."""
    for config in _configs(launch):
        if "program" not in config:
            continue
        target = _resolve(config["program"])
        assert target.is_file(), f"{config['name']}: {target} does not exist"


def test_every_module_is_importable(launch):
    """`module` entries name a real module with a `__main__` entry point."""
    import importlib.util

    for config in _configs(launch):
        module = config.get("module")
        if module is None:
            continue
        spec = importlib.util.find_spec(module)
        assert spec is not None, f"{config['name']}: no module {module!r}"
        source = pathlib.Path(spec.origin).read_text()
        assert '__name__ == "__main__"' in source, (
            f"{config['name']}: {module} has no __main__ guard, so running it as a "
            f"module would do nothing"
        )


def test_each_configuration_launches_something(launch):
    """Exactly one of `program` / `module`, or VS Code has nothing to run."""
    for config in _configs(launch):
        targets = {"program", "module"} & set(config)
        assert len(targets) == 1, f"{config['name']}: has {targets or 'neither'}"


def test_every_referenced_task_exists(launch, tasks):
    """A missing preLaunchTask stops the launch with a modal, before any code runs."""
    labels = {task["label"] for task in tasks["tasks"]}
    for config in _configs(launch):
        task = config.get("preLaunchTask")
        assert task in labels, f"{config['name']}: no task named {task!r} (have {labels})"


def test_every_configuration_uses_the_projects_interpreter(launch):
    """`uv run` cannot host a debugger, so the venv interpreter is the contract."""
    expected = "${workspaceFolder}/.venv/bin/python"
    for config in _configs(launch):
        assert config.get("python") == expected, f"{config['name']}: wrong interpreter"
        assert config.get("cwd") == "${workspaceFolder}", (
            f"{config['name']}: needs an explicit cwd — examples create `sessions/` "
            f"relative to it, so a different cwd scatters recordings"
        )


def test_the_sync_tasks_install_without_pruning(tasks):
    """`--inexact` or the task uninstalls the caller's dev tools on every F5."""
    for task in tasks["tasks"]:
        command = task["command"]
        if "uv sync" not in command:
            continue
        assert "--inexact" in command, f"{task['label']}: a bare `uv sync` prunes extras"


def test_the_examples_the_configurations_launch_are_smoke_tested(launch):
    """Every launched example is covered by tests/test_examples.py, which collects
    `examples/*/[!_]*.py` — so this holds as long as the target lives there."""
    from tests.test_examples import EXAMPLES  # noqa: PLC0415 - the list is the fixture

    covered = {path.resolve() for path in EXAMPLES}
    for config in _configs(launch):
        program = config.get("program")
        if program is None or "/examples/" not in program:
            continue
        assert _resolve(program).resolve() in covered, f"{config['name']}: not smoke-tested"


def test_every_control_file_is_reachable_from_a_configuration(launch):
    """The point of the whole file: no shipped mapping without a way to run it.

    `examples/controls/*.toml` is the public surface a user copies from. One that no
    configuration can reach is one they cannot see working — which is how
    `control_hand.toml` sat in the repository with no consumer at all.
    """
    sources = "\n".join(
        _resolve(config["program"]).read_text()
        for config in _configs(launch)
        if "program" in config
    )
    for control_file in sorted((ROOT / "examples" / "controls").glob("*.toml")):
        assert control_file.name in sources, (
            f"{control_file.name} is shipped but no launch configuration reaches it"
        )


def test_the_names_say_what_needs_a_live_vhi(launch):
    """A configuration that cannot work alone has to say so in the picker."""
    names = [config["name"] for config in _configs(launch)]
    prerequisites = [n for n in names if n.startswith("Prerequisite:")]
    assert len(prerequisites) >= 2, f"expected the VHI prerequisites to be named: {names}"
    assert any("leave running" in n for n in prerequisites), (
        "a long-running prerequisite must say it stays running, or it reads as a "
        "one-shot command that failed to exit"
    )
    rig_check = [
        config
        for config in _configs(launch)
        if "check_vhi_bridge" in config.get("program", "")
    ]
    assert rig_check, "the rig check is not reachable from the picker"
    assert "watch" in rig_check[0]["name"], (
        f"the rig check asks a human to watch the hand and answer; "
        f"{rig_check[0]['name']!r} does not say so"
    )


def test_no_absolute_machine_specific_paths(launch, tasks):
    """A committed file with someone's home directory in it works on one machine."""
    blob = LAUNCH.read_text() + TASKS.read_text()
    active = [
        line for line in blob.splitlines() if not line.lstrip().startswith("//")
    ]
    for line in active:
        assert not re.search(r'"/(Users|home)/', line), f"machine-specific path: {line}"


class TestTheWalkthroughSaysWhichVhiProblemItHit:
    """"Nothing is running" and "running, but pre-v2" need different actions.

    This matters most from the VS Code entries, where the prerequisite launches the
    *installed* release — which is pre-v2. Reporting that as "no target answered" sends
    a reader to launch a renderer that is already up and staring at them.
    """

    @staticmethod
    def _run(unimplemented: bool, capsys) -> str:
        import tools.inspect_canonical_control as walkthrough  # noqa: PLC0415

        class Client:
            def __init__(self) -> None:
                self.unimplemented = unimplemented

            def capabilities(self):
                return None

        assert walkthrough.step_2_ask_the_target(Client()) is None
        return capsys.readouterr().out

    def test_a_pre_v2_build_is_named_as_such(self, capsys):
        out = self._run(True, capsys)
        assert "pre-v2" in out
        assert "VHI_PATH" in out, "it must say how to get a v2 build"
        assert "No target answered" not in out

    def test_a_silent_port_asks_for_a_renderer(self, capsys):
        out = self._run(False, capsys)
        assert "No target answered" in out
        assert "pre-v2" not in out
