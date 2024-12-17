# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import pathlib
import sys
from datetime import datetime
from importlib import import_module
from inspect import getsource

import toml
import torch._dynamo
from docutils import nodes
from docutils.parsers.rst import Directive
from sphinx import addnodes
from sphinx_gallery.sorting import FileNameSortKey

sys.path.insert(0, pathlib.Path(__file__).parents[2].resolve().as_posix())


# Info from poetry config:
info = toml.load("../../pyproject.toml")["tool"]["poetry"]

project = "MyoGestic"
author = ", ".join(info["authors"])
release = info["version"]

copyright = (
    f"2023 - {datetime.now().year}, n-squared lab, FAU Erlangen-Nürnberg, Germany"
)

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

# Generate README.md for sphinx
# --------------------------------
HERE = pathlib.Path(__file__).parent
with (HERE.parent.parent / "README.md").open() as f:
    out = f.read()

lines = out.split("\n")

# find the line_indices containing "[!"
line_indices = [i for i, line in enumerate(lines) if "[!" in line]
# find for each index the last line connected to it that does not contain ">".
lines_connected = {}
for i, l in enumerate(line_indices):
    for j in range(l, len(lines) - 1):
        if ">" in lines[j] and ">" not in lines[j + 1]:
            lines_connected[l] = j
            break

for start, end in lines_connected.items():
    lines[start] = "```{" + lines[start][4:].strip().replace("]", "").lower() + "}\n"
    for i in range(start + 1, end + 1):
        lines[i] = lines[i].replace("> ", "") + "\n"

    lines[end] += "```\n"

out = "\n".join(lines)


with (HERE / "README.md").open("w+") as f:
    f.write(out)


extensions = [
    "sphinx.ext.autodoc",
    # "sphinx_autodoc_typehints",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx_gallery.gen_gallery",
    "rinoh.frontend.sphinx",
    "enum_tools.autoenum",
    "myst_parser",
    "sphinxcontrib.youtube",
    "sphinxcontrib.pdfembed",
]

# autosummary_generate = True
autoclass_content = "both"
autodoc_typehints = "description"

autodoc_member_order = "groupwise"

autosummary_generate = True
autosummary_generate_overwrite = True

add_function_parentheses = True

napoleon_numpy_docstring = True

templates_path = ["_templates"]
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static"]

html_css_files = ["custom.css"]

# -- Options for intersphinx extension ---------------------------------------
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
    # TODO: Add catboost intersphinx ... probably manually as they do not have a objects.inv file,
}

# -- Options for sphinx_gallery ----------------------------------------------
sphinx_gallery_conf = {
    "examples_dirs": "../../examples",  # path to your example scripts
    "gallery_dirs": "auto_examples",  # path to where to save gallery generated output
    "filename_pattern": r"\.py",
    "remove_config_comments": True,
    "show_memory": True,
    "within_subsection_order": FileNameSortKey,
    "plot_gallery": True,
    "download_all_examples": False,
}

suppress_warnings = ["config.cache"]


class PrettyPrintIterable(Directive):
    """
    Directive to pretty print an iterable object in the documentation

    Note:
    -----
    - The directive is copied from https://stackoverflow.com/a/62253904
    """

    required_arguments = 1

    def run(self):
        def _get_iter_source(src, varname):
            # 1. identifies target iterable by variable name, (cannot be spaced)
            # 2. determines iter source code start & end by tracking brackets
            # 3. returns source code between found start & end
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

        module_path, member_name = self.arguments[0].rsplit(".", 1)
        src = getsource(import_module(module_path)).split("\n")
        code = _get_iter_source(src, member_name)

        literal = nodes.literal_block(code, code)
        literal["language"] = "python"

        return [
            addnodes.desc_name(text=member_name),
            addnodes.desc_content("", literal),
        ]


def setup(app):
    app.add_directive("pprint", PrettyPrintIterable)
