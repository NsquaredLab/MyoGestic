"""Contract tests for the static website API inventory."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "website/scripts/gen_api.py"


@pytest.fixture(scope="module")
def api():
    assert SCRIPT.is_file(), "website/scripts/gen_api.py is missing"
    subprocess.run(["uv", "run", "--extra", "docs", "python", str(SCRIPT)], cwd=ROOT, check=True)
    return json.loads((ROOT / "website/src/generated/api.json").read_text(encoding="utf-8"))


def test_pipeline_signature_and_page(api):
    pipeline = api["symbols"]["myogestic.ml.Pipeline"]
    assert pipeline["kind"] == "class"
    assert "predict_hz" in pipeline["signature"]
    assert "__init__" not in pipeline["members"]
    assert "myogestic.ml.Pipeline" in [d["path"] for d in api["pages"]["api/ml"]]
    assert api["inventory"]["myogestic.ml.Pipeline"] == (
        "/MyoGestic/api/ml/#myogestic.ml.Pipeline"
    )


def test_pipeline_omits_undocumented_members(api):
    pipeline = api["symbols"]["myogestic.ml.Pipeline"]
    assert "myogestic.ml.Pipeline.extract" in pipeline["members"]
    for name in ("app", "predict_hz", "input_streams", "model"):
        path = f"myogestic.ml.Pipeline.{name}"
        assert path not in pipeline["members"]
        assert path not in api["symbols"]
        assert path not in api["inventory"]


def test_long_and_short_signatures(api):
    assert api["symbols"]["myogestic.ml.Pipeline"]["signature"] == (
        "Pipeline(\n"
        "    app: App,\n"
        "    predict_hz: float = 50.0,\n"
        "    *,\n"
        "    input_streams: Sequence[str] | None = None,\n"
        ")"
    )
    short = api["symbols"]["myogestic.recipes.features.mav"]["signature"]
    assert len(short) <= 80
    assert "\n" not in short


def test_member_selection_and_nested_signature_expressions(tmp_path):
    """Explicit selections and legacy destinations survive the default filter."""
    package = tmp_path / "myogestic"
    package.mkdir()
    (package / "__init__.py").write_text('''
class Container:
    """Documented container."""
    hidden = None
    visible = 1
    """Documented attribute."""
    class InitOnly:
        def __init__(self):
            """Constructor documentation is merged into the class."""
class Selected:
    """Explicit member selection."""
    hidden = None
    other = None
class Legacy:
    value = None
def long_function(first: dict[str, tuple[int, int]] = {"a,b": (1, 2)}, /, *, second: str = "x,y") -> tuple[int, str]:
    """A long signature with commas inside types and defaults."""
''')
    docs = tmp_path / "docs/api"
    docs.mkdir(parents=True)
    (docs / "fixture.md").write_text(
        "::: myogestic.Container\n\n"
        "::: myogestic.Selected\n    options:\n      members: [hidden]\n\n"
        "::: myogestic.Legacy\n\n"
        "::: myogestic.long_function\n"
    )
    legacy = tmp_path / "website/tests/legacy-symbols.txt"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("myogestic.Legacy.value\tattribute\tapi/fixture/#$\n")
    code = """
import importlib.util
import json
import sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("gen_api", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ROOT = Path(sys.argv[2])
# Load the fixture by path so this checkout's editable install cannot shadow it.
load = module.griffe.load
module.griffe.load = lambda *args, **kwargs: load(module.ROOT / "myogestic", **kwargs)
print(json.dumps(module.build_api()))
"""
    result = subprocess.run(
        ["uv", "run", "--extra", "docs", "python", "-c", code, str(SCRIPT), str(tmp_path)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    symbols = json.loads(result.stdout)["symbols"]
    assert "myogestic.Container.hidden" not in symbols
    assert "myogestic.Container.visible" in symbols
    assert "myogestic.Container.InitOnly" in symbols
    assert "myogestic.Selected.hidden" in symbols
    assert "myogestic.Selected.other" not in symbols
    assert "myogestic.Legacy.value" in symbols
    signature = symbols["myogestic.long_function"]["signature"]
    lines = signature.splitlines()
    assert len(lines) == 6
    assert lines[1].startswith("    first: dict[str, tuple[int, int]] = ")
    assert lines[2:4] == ["    /,", "    *,"]
    assert lines[4].startswith("    second: str = ")
    assert lines[-1] == ") -> tuple[int, str]"


def test_private_names_are_filtered_and_aliases_resolve(api):
    assert not any(
        part.startswith("_") for path in api["symbols"] for part in path.split(".")
    )
    assert api["inventory"]["myogestic.core.App"] == api["inventory"]["myogestic.App"]
    assert api["symbols"]["myogestic.App"]["members"][0].startswith("myogestic.App.")


def test_numpy_docstrings_and_directive_options(api):
    sections = api["symbols"]["myogestic.ml.Pipeline"]["docstring"]
    parameters = next(s["value"] for s in sections if s["kind"] == "parameters")
    assert any(p["name"] == "predict_hz" and p["description"] for p in parameters)
    directive = next(d for d in api["pages"]["api/core"] if d["path"].endswith("install_vhi"))
    assert directive["options"]["members"] == ["main"]


def test_generator_is_static_and_deterministic(api):
    code = """
import builtins
import importlib.util
import json
import sys
original_import = builtins.__import__
def static_import(name, *args, **kwargs):
    if name == "myogestic" or name.startswith("myogestic."):
        raise AssertionError("Generator imported package code: " + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = static_import
spec = importlib.util.spec_from_file_location("gen_api", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(module.build_api()))
"""
    result = subprocess.run(
        ["uv", "run", "--extra", "docs", "python", "-c", code, str(SCRIPT)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == api


def test_inherited_public_members_and_aliases(api):
    assert "myogestic.widgets.PostProcessor.filter" in api["symbols"]
    assert "myogestic.outputs.LSLOutlet.push" in api["symbols"]
    assert "myogestic._controls_map.Continuous" in api["inventory"]


def test_legacy_inventory_destinations_are_generated(api):
    """Aliases use the saved URI's destination, which can differ from the name."""
    for line in (ROOT / "website/tests/legacy-symbols.txt").read_text(encoding="utf-8").splitlines():
        name, _, uri = line.split("\t")
        page, anchor = uri.split("#")
        target = anchor.replace("$", name)
        assert target in api["symbols"], (name, uri)
        assert name in api["inventory"], name
        assert any(
            target == directive["path"] or target.startswith(directive["path"] + ".")
            for directive in api["pages"][page.rstrip("/")]
        ), (name, uri)
