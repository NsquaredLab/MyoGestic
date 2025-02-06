import os
import sys
from pathlib import Path
from datetime import datetime
from importlib import import_module
from inspect import getsource
import toml
from docutils import nodes
from docutils.parsers.rst import Directive
from sphinx import addnodes
from sphinx_gallery.sorting import FileNameSortKey
import torch._dynamo  # noqa
import myogestic # noqa

# Setup paths
base_dir = Path.cwd().parent.parent
sys.path.insert(0, str(base_dir))
sys.path.insert(0, os.path.abspath('..'))
sys.path.insert(0, os.path.abspath('../..'))
sys.path.insert(0, os.path.abspath('../../myogestic'))

# Project Information
poetry_info = toml.load(base_dir / "pyproject.toml")["tool"]["poetry"]
project = "MyoGestic"
author = ", ".join(poetry_info["authors"])
release = poetry_info["version"]
copyright = (
    f"2023 - {datetime.now().year}, n-squared lab, FAU Erlangen-Nürnberg, Germany"
)


def process_readme(readme_path: Path) -> str:
    """Processes the README.md file and generates the modified content."""
    print(readme_path)

    with readme_path.open() as f:
        lines = f.read().split("\n")

    line_indices = [i for i, line in enumerate(lines) if "[!" in line]
    line_ranges = find_line_ranges(lines, line_indices)

    # Format lines
    for start, end in line_ranges.items():
        lines[start] = f"```{{{lines[start][4:].strip().replace(']', '').lower()}}}\n"
        for i in range(start + 1, end + 1):
            lines[i] = lines[i].replace("> ", "") + "\n"
        lines[end] += "```\n"

    return "\n".join(lines)


def find_line_ranges(lines, indices):
    """Finds the range of lines connected to each matched line index."""
    line_ranges = {}
    for i, start in enumerate(indices):
        for j in range(start, len(lines) - 1):
            if ">" in lines[j] and ">" not in lines[j + 1]:
                line_ranges[start] = j
                break
    return line_ranges


# Process README and save
modified_readme = process_readme(base_dir / "README.md")
with (Path.cwd()/ "README.md").open("w+") as readme_file:
    readme_file.write(modified_readme)

# Sphinx Configuration
extensions = [
    "sphinx.ext.autodoc",
    # "sphinx_autodoc_typehints",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx_gallery.gen_gallery",
    "sphinx_toolbox.more_autodoc.autotypeddict",
    "sphinx.ext.doctest",
    "rinoh.frontend.sphinx",
    "enum_tools.autoenum",
    "myst_parser",
    "sphinxcontrib.youtube",
    "sphinxcontrib.pdfembed",
]

numpydoc_class_members_toctree = False
autodoc_default_options = {"members": True, "inherited-members": False}
autodoc_inherit_docstrings = True
autoclass_content = "both"
autodoc_typehints = "description"
autodoc_member_order = "groupwise"
autosummary_generate = True
autosummary_generate_overwrite = True
autosummary_imported_members = False

templates_path = ["templates"]
exclude_patterns = ["auto_examples/", "Thumbs.db", ".DS_Store"]

html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]
html_css_files = ["custom.css"]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "scipy": ("https://docs.scipy.org/doc/scipy/reference/", None),
    "matplotlib": ("https://matplotlib.org/stable/", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "sklearn": ("https://scikit-learn.org/stable/", None),
    "torch": ("https://pytorch.org/docs/stable/", None),
    "torchvision": ("https://pytorch.org/vision/stable/", None),
    "PySide6": (
        "https://doc.qt.io/qtforpython-6/",
        "https://doc.qt.io/qtforpython-6/objects.inv",
    ),
}

sphinx_gallery_conf = {
    "examples_dirs": str(base_dir / "examples"),
    "gallery_dirs": "auto_examples",
    "filename_pattern": r"\.py",
    "remove_config_comments": True,
    "show_memory": True,
    "within_subsection_order": FileNameSortKey,
    "plot_gallery": True,
    "download_all_examples": False,
}

suppress_warnings = ["config.cache"]


class PrettyPrintIterable(Directive):
    """Directive to pretty print an iterable object in the documentation."""

    required_arguments = 1

    def run(self):
        module_path, member_name = self.arguments[0].rsplit(".", 1)
        src = getsource(import_module(module_path)).split("\n")
        code = _get_iter_source(src, member_name)
        literal = nodes.literal_block(code, code)
        literal["language"] = "python"
        return [
            addnodes.desc_name(text=member_name),
            addnodes.desc_content("", literal),
        ]


def _get_iter_source(src, varname):
    """Fetches the source code of an iterable."""
    start = end = None
    open_brackets = closed_brackets = 0
    for i, line in enumerate(src):
        if line.startswith(varname):
            if start is None:
                start = i
        if start is not None:
            open_brackets += sum(line.count(b) for b in "([{")
            closed_brackets += sum(line.count(b) for b in ")]}")
        if open_brackets > 0 and (open_brackets - closed_brackets == 0):
            end = i + 1
            break
    return "\n".join(src[start:end])


def skip_modules(app, what, name, obj, skip, options):
    exclude_modules = ["auto_examples/*", "README.md"]
    return any(name.startswith(excluded) for excluded in exclude_modules) or skip


def setup(app):
    app.add_directive("pprint", PrettyPrintIterable)
    app.connect("autodoc-skip-member", skip_modules)
