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


VARIABLE = re.compile(r"\$\{(file|fileDirname|input:[A-Za-z]+)\}")


def test_every_fixed_program_path_exists(launch):
    """The failure a rename causes, caught here instead of at F5.

    `${file}` entries are exempt by design — they launch whatever the user has open,
    which is the whole point of them.
    """
    for config in _configs(launch):
        program = config.get("program")
        if program is None or VARIABLE.search(program):
            continue
        target = _resolve(program)
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
    """`uv run` cannot host a debugger, so the venv interpreter is the contract.

    It must be *this* project's venv even for a user's own file kept elsewhere: that is
    what makes `${file}` work against this checkout without the user installing anything.
    """
    posix = "${workspaceFolder}/.venv/bin/python"
    windows = "${workspaceFolder}\\.venv\\Scripts\\python.exe"
    for config in _configs(launch):
        assert config.get("python") == posix, f"{config['name']}: wrong interpreter"
        # A committed file is used on Windows too, where that path does not exist.
        assert config.get("windows", {}).get("python") == windows, (
            f"{config['name']}: no Windows interpreter override"
        )


def test_a_cwd_is_always_set_and_follows_the_right_thing(launch):
    """Never inherited: relative paths inside an app depend on it.

    A user's own file gets `${fileDirname}`, so a control map beside it resolves the way
    it does when they run it by hand. A repository entry gets the workspace, because the
    examples create `sessions/` relative to cwd.
    """
    for config in _configs(launch):
        cwd = config.get("cwd")
        assert cwd in {"${workspaceFolder}", "${fileDirname}"}, (
            f"{config['name']}: cwd is {cwd!r}"
        )
        program = config.get("program", "")
        if "${file}" in program or "inspect_control_map" in program:
            assert cwd == "${fileDirname}", (
                f"{config['name']}: a generic entry must follow the user's file"
            )
        elif "/examples/" in program:
            assert cwd == "${workspaceFolder}", f"{config['name']}: wrong cwd"


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
        if "program" in config and not VARIABLE.search(config["program"])
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
        import tools.inspect_control as walkthrough  # noqa: PLC0415

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


class TestTheGenericEntriesComeFirstAndWork:
    """The primary workflow is a user's *own* file, not this repository's examples.

    That is a product decision, so it is pinned: the entries that launch `${file}` must
    exist, must be first in the picker, and must not be crowded out by example entries
    that only demonstrate something.
    """

    @pytest.fixture(scope="class")
    def configs(self) -> list[dict]:
        return _read_jsonc(LAUNCH)["configurations"]

    def test_a_run_and_a_debug_entry_both_launch_the_open_file(self, configs):
        generic = [c for c in configs if c.get("program") == "${file}"]
        names = [c["name"] for c in generic]
        assert len(generic) == 2, f"expected a Run and a Debug entry, got {names}"
        assert any(c.get("noDebug") for c in generic), "one must run without debugging"
        assert any(not c.get("noDebug") for c in generic), "one must run under it"

    def test_the_debug_entry_steps_into_myogestic(self, configs):
        debug = next(
            c for c in configs if c.get("program") == "${file}" and not c.get("noDebug")
        )
        assert debug.get("justMyCode") is False, (
            "resolving a control map happens inside the library; stepping has to reach it"
        )

    def test_the_generic_entries_are_the_first_thing_in_the_picker(self, configs):
        """VS Code orders by presentation group, so the group prefix is the ordering."""
        groups = [c.get("presentation", {}).get("group", "") for c in configs]
        assert all(groups), "every entry needs a presentation group or ordering is a toss-up"
        first = min(groups)
        for config, group in zip(configs, groups, strict=True):
            if group == first:
                assert "${file}" in str(config.get("program", "")) or "inspect_control_map" in str(
                    config.get("program", "")
                ), f"{config['name']} is in the first group but is not for the user's own files"

    def test_every_entry_says_what_kind_of_thing_it_is(self, configs):
        """A name is what a user reads in the picker, so the prefix carries the sort.

        "Playground:" is something to try, "Example:" is a reference app to read,
        "Prerequisite:" is a thing to start first. The distinction matters more than the
        directory an entry happens to point into — both playgrounds live under
        `examples/` and neither is a demonstration of an EMG pipeline.
        """
        allowed = ("Playground:", "Example:", "Reference:", "Prerequisite:", "Rig check:")
        for config in configs:
            program = config.get("program", "")
            if "${file}" in program or "inspect_control_map" in program:
                continue  # the generic entries are named for the action, not the kind
            assert config["name"].startswith(allowed), config["name"]

    def test_the_playground_is_reachable_and_named_as_such(self, configs):
        """The entry a user is pointed at first to see VHI 2 move."""
        playgrounds = [c for c in configs if c["name"].startswith("Playground:")]
        assert playgrounds, "no playground entry"
        assert any("control_map_studio" in c.get("program", "") for c in playgrounds)
        assert any("no VHI needed" in c["name"] for c in playgrounds), (
            "the editor-only playground must say it needs no renderer"
        )

    def test_every_input_reference_is_declared(self):
        """An undeclared ${input:...} fails the launch with a variable-resolution error."""
        launch = _read_jsonc(LAUNCH)
        declared = {entry["id"] for entry in launch.get("inputs", [])}
        referenced = set(re.findall(r"\$\{input:([A-Za-z0-9_]+)\}", LAUNCH.read_text()))
        assert referenced, "the prompt entry is gone"
        assert referenced <= declared, f"undeclared inputs: {referenced - declared}"

    def test_no_input_default_relies_on_an_unexpanded_variable(self):
        """VS Code does not substitute into an input's default, so `${file}` there would
        be offered to the user literally."""
        for entry in _read_jsonc(LAUNCH).get("inputs", []):
            assert "${" not in entry.get("default", ""), entry["id"]

    def test_the_inspector_the_entries_point_at_takes_a_path(self):
        """The generic inspector must accept an arbitrary path, or the entries lie."""
        import subprocess  # noqa: PLC0415

        tool = ROOT / "tools" / "inspect_control_map.py"
        assert tool.is_file()
        result = subprocess.run(
            [str(ROOT / ".venv" / "bin" / "python"), str(tool), "--help"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, result.stderr
        assert "path" in result.stdout, "no positional path argument"
