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
    return json.loads((ROOT / "website/src/generated/api.json").read_text())


def test_pipeline_signature_and_page(api):
    pipeline = api["symbols"]["myogestic.ml.Pipeline"]
    assert pipeline["kind"] == "class"
    assert "predict_hz" in pipeline["signature"]
    assert "__init__" not in pipeline["members"]
    assert "myogestic.ml.Pipeline" in [d["path"] for d in api["pages"]["api/ml"]]
    assert api["inventory"]["myogestic.ml.Pipeline"] == (
        "/MyoGestic/api/ml/#myogestic.ml.Pipeline"
    )


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
    for line in (ROOT / "website/tests/legacy-symbols.txt").read_text().splitlines():
        name, _, uri = line.split("\t")
        page, anchor = uri.split("#")
        target = anchor.replace("$", name)
        assert target in api["symbols"], (name, uri)
        assert name in api["inventory"], name
        assert any(
            target == directive["path"] or target.startswith(directive["path"] + ".")
            for directive in api["pages"][page.rstrip("/")]
        ), (name, uri)
