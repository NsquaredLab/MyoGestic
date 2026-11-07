"""Generate the website's API data from source without importing MyoGestic."""

from __future__ import annotations

import json
import logging
import re
from io import StringIO
from pathlib import Path
from textwrap import dedent
from tokenize import OP, generate_tokens

import griffe
import yaml

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "website/src/generated/api.json"
DIRECTIVE = re.compile(r"^::: ([\w.]+)\s*$")
SECTION_KINDS = {
    "text", "parameters", "returns", "yields", "raises", "attributes", "examples",
    "notes", "warns", "other",
}


def public(path: str) -> bool:
    """Return whether every component is public."""
    return all(not part.startswith("_") for part in path.split("."))


def directives(path: Path) -> list[dict]:
    """Read standalone directives and their indented YAML configuration."""
    lines = path.read_text(encoding="utf-8").splitlines()
    result = []
    fence = None
    index = 0
    while index < len(lines):
        line = lines[index]
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
        match = DIRECTIVE.match(line) if fence is None else None
        index += 1
        if not match:
            continue
        block = []
        while index < len(lines) and (not lines[index].strip() or lines[index].startswith("    ")):
            block.append(lines[index])
            index += 1
        config = yaml.safe_load(dedent("\n".join(block))) or {}
        options = config.get("options", {})
        if not isinstance(options, dict):
            raise ValueError(f"{path}: options for {match[1]} must be a mapping")
        result.append({"path": match[1], "options": options})
    return result


def sections(obj: griffe.Object) -> list[dict]:
    """Serialize NumPy sections, retaining Markdown in descriptions and examples."""
    result = []
    docstrings = [obj.docstring]
    if obj.is_class and "__init__" in obj.members:
        docstrings.append(obj.members["__init__"].docstring)
    for docstring in docstrings:
        if not docstring:
            continue
        for section in docstring.parsed:
            kind = section.kind.value
            title = getattr(section, "title", None)
            value = section.value
            if kind == "examples":
                value = "\n\n".join(
                    f"```pycon\n{text}\n```" if part.value == "examples" else text
                    for part, text in value
                )
            elif isinstance(value, list):
                value = [
                    {
                        "name": getattr(param, "name", ""),
                        "annotation": str(getattr(param, "annotation", "") or ""),
                        "description": getattr(param, "description", ""),
                        "default": (str(param.value) if getattr(param, "value", None) is not None else None),
                    }
                    for param in value
                ]
            elif not isinstance(value, str):
                value = getattr(value, "description", str(value))
            result.append({
                "kind": kind if kind in SECTION_KINDS else "other",
                **({"title": title or kind.replace("_", " ").title()} if title or kind not in SECTION_KINDS else {}),
                "value": value,
            })
    return result


def format_signature(signature: str) -> str:
    """Break long signatures at parameter boundaries, preserving nested expressions."""
    if len(signature) <= 80:
        return signature
    depth = 0
    parameters = []
    start = 0
    opening = signature.index("(")
    for token in generate_tokens(StringIO(signature).readline):
        if token.type != OP:
            continue
        if token.string in "([{":
            depth += 1
            if depth == 1:
                start = token.end[1]
        elif token.string in ")]}":
            depth -= 1
            if depth == 0:
                if signature[start:token.start[1]].strip():
                    parameters.append(signature[start:token.start[1]].strip())
                closing = token.start[1]
                break
        elif token.string == "," and depth == 1:
            parameters.append(signature[start:token.start[1]].strip())
            start = token.end[1]
    return (
        signature[:opening + 1] + "\n"
        + "".join(f"    {parameter},\n" for parameter in parameters)
        + signature[closing:]
    )


def build_api() -> dict:
    """Collect documented public objects, their members, and resolved aliases."""
    # Diagnostics in NumPy docstrings are not build failures. Keep real loader
    # errors visible while avoiding hundreds of missing-annotation warnings.
    logging.getLogger("griffe").setLevel(logging.ERROR)
    package = griffe.load(
        "myogestic", search_paths=[ROOT], docstring_parser="numpy",
        allow_inspection=False, resolve_aliases=True,
        resolve_external=False, resolve_implicit=True,
    )
    pages = {
        f"api/{path.stem}": directives(path)
        for path in sorted((ROOT / "docs/api").glob("*.md"))
        if path.stem != "index"
    }
    symbols = {}
    inventory = {}
    canonical_urls = {}
    # Keep the frozen inventory's actual destinations, including undocumented
    # constants and any ancestors needed to reach them through a directive.
    legacy_targets = set()
    for line in (ROOT / "website/tests/legacy-symbols.txt").read_text(encoding="utf-8").splitlines():
        name, _, uri = line.split("\t")
        target = uri.split("#")[1].replace("$", name)
        parts = target.split(".")
        legacy_targets.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))

    def collect(obj, path: str, page: str, options: dict, ancestors: frozenset):
        canonical = obj.canonical_path
        if not public(path) or canonical in ancestors:
            return
        members = []
        if obj.is_class or obj.is_module:
            members = [
                (name, member) for name, member in (obj.all_members if obj.is_class else obj.members).items()
                if public(name)
            ]
        chosen = options.get("members", True)
        if chosen is False:
            members = []
        elif isinstance(chosen, list):
            members = [(name, member) for name, member in members if name in chosen]
        paths = []
        for name, member in members:
            try:
                if not member.canonical_path.startswith("myogestic."):
                    continue
                member_path = f"{path}.{name}"
                documented = member.has_docstring or (
                    member.is_class and "__init__" in member.members
                    and member.members["__init__"].has_docstring
                )
                if not documented and not isinstance(chosen, list) and member_path not in legacy_targets:
                    continue
                collect(member, member_path, page, {}, ancestors | {canonical})
                if member_path in symbols:
                    paths.append(member_path)
            except griffe.AliasResolutionError:
                continue  # Optional external imports are not API members.
        signature = None
        if obj.is_class or obj.is_function:
            signature = format_signature(obj.signature(return_type=True, name=path.rsplit(".", 1)[-1]))
        elif obj.is_attribute:
            signature = path.rsplit(".", 1)[-1]
            if obj.annotation is not None:
                signature += f": {obj.annotation}"
            if obj.value is not None:
                signature += f" = {obj.value}"
        symbols[path] = {
            "kind": obj.kind.value, "path": path, "name": path.rsplit(".", 1)[-1],
            "signature": signature, "labels": sorted(obj.labels),
            "bases": [str(base) for base in getattr(obj, "bases", [])],
            "docstring": sections(obj), "members": paths,
        }
        url = f"/MyoGestic/{page}/#{path}"
        inventory.setdefault(path, url)
        canonical_urls.setdefault(canonical, url)

    for page, items in pages.items():
        for directive in items:
            path = directive["path"]
            collect(package[path.removeprefix("myogestic.")], path, page, directive["options"], frozenset())
    # All import aliases for a documented object resolve to the same rendered
    # public anchor, even when the implementation module is private.
    def aliases(obj, path: str, ancestors: frozenset):
        try:
            canonical = obj.canonical_path
            if canonical in canonical_urls:
                inventory.setdefault(path, canonical_urls[canonical])
            if canonical in ancestors or not (obj.is_module or obj.is_class):
                return
            for name, member in (obj.all_members if obj.is_class else obj.members).items():
                if public(name) or isinstance(member, griffe.Module):
                    aliases(member, f"{path}.{name}", ancestors | {canonical})
        except griffe.AliasResolutionError:
            pass

    aliases(package, "myogestic", frozenset())
    for canonical, url in canonical_urls.items():
        inventory.setdefault(canonical, url)
    return {"pages": pages, "symbols": symbols, "inventory": dict(sorted(inventory.items()))}


def main() -> None:
    """Write deterministic, build-local JSON from the checked-out source."""
    data = build_api()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(data['symbols'])} API symbols and {len(data['inventory'])} references in {OUTPUT}")


if __name__ == "__main__":
    main()
