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
try:
    import torch._dynamo  # noqa
except ImportError:
    pass  # torch not required for docs build
# Setup paths
base_dir = Path.cwd().parent.parent
sys.path.insert(0, str(base_dir)) # Add project root
# sys.path.insert(0, os.path.abspath('..')) # Remove redundant/potentially problematic paths
# sys.path.insert(0, os.path.abspath('../..')) # Remove redundant/potentially problematic paths
# sys.path.insert(0, os.path.abspath('../../myogestic')) # Remove redundant/potentially problematic paths
# sys.path.insert(0, os.path.abspath('../../../myogestic')) # Remove redundant/potentially problematic paths

# Project Information
poetry_info = toml.load(base_dir / "pyproject.toml")["project"] # Reverted to using [project]
project = poetry_info["name"]
# Parse authors based on PEP 621 standard ([{name = "...", email = "..."}, ...])
authors_list = poetry_info.get("authors", [])
author = ", ".join([f"{a.get('name', '')} ({a.get('email', '')})" for a in authors_list])
release = version = poetry_info["version"]
copyright = (
    f"2023 - {datetime.now().year}, n-squared lab, FAU Erlangen-Nürnberg, Germany"
)

print(os.path.abspath('..'))

# import myogestic # noqa - Keep specific import for now, might need adjustment based on actual project structure
# Use dynamic import based on project name from pyproject.toml
# project_module_name = poetry_info["name"].lower() # Assuming module name is lowercase project name
# __import__(project_module_name)
import myogestic # Revert to explicit import

# Re-add the removed process_readme function and its call as it might be needed
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
    # "sphinx_toolbox.more_autodoc.autotypeddict", # Removed
    "sphinx.ext.doctest",
    "rinoh.frontend.sphinx",
    # "enum_tools.autoenum", # Removed
    "myst_parser", # Re-add myst_parser as it was likely needed
    "sphinxcontrib.youtube", # Removed -> Re-enabled
    # "sphinxcontrib.pdfembed", # Removed
]

# MyST-Parser configuration # Uncommented MyST specific config
myst_enable_extensions = [
    "attrs_inline",
    "attrs_block",
    "colon_fence",
    "deflist",
    "dollarmath",
    "fieldlist",
    "html_admonition",
    "html_image",
    "linkify",
    "replacements",
    "smartquotes",
    "substitution",
    "tasklist",
]

# Auto-generate targets for section headers
myst_heading_anchors = 3

# Enable use of MyST-style admonitions in Markdown
myst_admonition_enable = True

# Configure how external links are handled
myst_url_schemes = ["http", "https", "mailto", "ftp"]

# Set MyST to parse all references to section headers as references
myst_ref_domains = ["std"]

numpydoc_class_members_toctree = False
autodoc_default_options = {"members": True, "inherited-members": False}
autodoc_inherit_docstrings = True
autoclass_content = "both"
autodoc_typehints = "description"
autodoc_member_order = "groupwise"
autosummary_generate = True
autosummary_generate_overwrite = True
autosummary_imported_members = False
# autodoc_mock_imports = ["PySide6"] # Add PySide6 to mock imports

templates_path = ["templates"]
exclude_patterns = ["auto_examples/", "Thumbs.db", ".DS_Store"]

html_context = { # Added html_context
    "AUTHOR": author,
    "VERSION": version,
    "DESCRIPTION": poetry_info.get("description", ""), # Use .get for safety - Fetch from [project] table
    "github_user": "NsquaredLab", # Assuming same user/repo for now
    "github_repo": project, # Use dynamic project name
    "github_version": "master",
    "doc_path": "docs",
}

html_theme = "pydata_sphinx_theme"
html_theme_options = { # Added html_theme_options
    "github_url": f"https://github.com/NsquaredLab/{project}", # Use dynamic project name
    "navbar_start": ["navbar-logo", "navbar-version.html", "header-text.html"],
    "show_prev_next": False,
}
html_static_path = ["_static"]
html_logo = "_static/myogestic_logo.png" # Adjusted logo name assumption
html_css_files = ["custom.css"]
html_title = f"{project} {version} Documentation" # Added html_title

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

# Suppress specific warnings
suppress_warnings = [ # Updated suppress_warnings
    "config.cache",
    # "myst.header",  # Removed
    # "myst.xref_missing" # Removed
]


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
