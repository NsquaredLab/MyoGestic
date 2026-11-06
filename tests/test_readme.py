"""Keep the README's public imports usable without starting its GUI."""

import ast
import importlib
import re
from pathlib import Path


def test_quickstart_imports_resolve():
    """Resolve every imported name in the README's Python examples."""
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"^```python\n(.*?)\n```", readme, flags=re.MULTILINE | re.DOTALL)
    imports = [
        node
        for code in blocks
        for node in ast.walk(ast.parse(code))
        if isinstance(node, ast.ImportFrom)
    ]
    assert imports, "The README must include the Quick start imports"
    for node in imports:
        assert node.module and not node.level, "README examples must use absolute imports"
        module = importlib.import_module(node.module)
        for name in node.names:
            assert hasattr(module, name.name), f"from {node.module} import {name.name} does not resolve"
