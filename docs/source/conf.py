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
# Setup paths
base_dir = Path.cwd().parent.parent
sys.path.insert(0, str(base_dir))
sys.path.insert(0, os.path.abspath('..'))
sys.path.insert(0, os.path.abspath('../..'))
sys.path.insert(0, os.path.abspath('../../myogestic'))
sys.path.insert(0, os.path.abspath('../../../myogestic'))

print(os.path.abspath('..'))

import myogestic # noqa

# Project Information
poetry_info = toml.load(base_dir / "pyproject.toml")["project"]
project = "MyoGestic"
author = ", ".join([x["name"] + f" ({x['email']})" for x in poetry_info["authors"]])
release = poetry_info["version"]
copyright = (
    f"2023 - {datetime.now().year}, n-squared lab, FAU Erlangen-Nürnberg, Germany"
)

def process_readme(readme_path: Path, output_path: Path) -> None:
    """Processes the README.md file and generates a modified version for Sphinx.
    
    Args:
        readme_path: Path to the original README.md
        output_path: Path where the processed file should be saved
    """
    print(f"Processing README from {readme_path} to {output_path}")

    with readme_path.open(encoding='utf-8') as f:
        lines = f.read().split("\n")

    # Find blockquote admonitions with emojis
    admonition_starts = []
    for i, line in enumerate(lines):
        if line.startswith("> 💡 **Tip**:"):
            admonition_starts.append((i, "tip"))
        elif line.startswith("> ⚠️ **Important**:"):
            admonition_starts.append((i, "important"))
        elif line.startswith("> 📝 **Note**:"):
            admonition_starts.append((i, "note"))

    # Find the end of each admonition (the next line that doesn't start with ">")
    admonition_ranges = {}
    for start, admonition_type in admonition_starts:
        for j in range(start + 1, len(lines)):
            if j >= len(lines) or not lines[j].startswith(">"):
                admonition_ranges[start] = (j - 1, admonition_type)
                break
            if j == len(lines) - 1:  # If we reach the end of the file
                admonition_ranges[start] = (j, admonition_type)

    # Convert blockquote admonitions to Sphinx admonitions
    # Process in reverse order to avoid changing indices
    for start, (end, admonition_type) in sorted(admonition_ranges.items(), reverse=True):
        # Replace the first line with the admonition directive
        content = lines[start].replace("> 💡 **Tip**:", "").replace("> ⚠️ **Important**:", "").replace("> 📝 **Note**:", "").strip()
        lines[start] = f"```{{{admonition_type}}}\n{content}"
        
        # Process content lines, removing the blockquote marker
        for i in range(start + 1, end + 1):
            lines[i] = lines[i].replace("> ", "") + "\n"
            
        # Close the admonition
        lines[end] += "\n```\n"
    
    # Find all headers and create a map of GitHub-style anchors to Sphinx references
    headers = {}
    for i, line in enumerate(lines):
        if line.startswith('## '):
            # Extract the header text and create a GitHub-style anchor
            header_text = line[3:].strip()
            # GitHub style: lowercase, spaces to hyphens, remove non-alphanumerics except hyphens
            github_anchor = header_text.lower().replace(' ', '-')
            github_anchor = ''.join(c for c in github_anchor if c.isalnum() or c == '-')
            headers[github_anchor] = header_text
    
    # Fix Table of Contents links - convert GitHub style to Sphinx references
    toc_start = None
    toc_end = None
    
    # Find the Table of Contents section
    for i, line in enumerate(lines):
        if line.strip() == "## Table of Contents":
            toc_start = i
            break
    
    # Find the end of the Table of Contents section
    if toc_start is not None:
        for i in range(toc_start + 1, len(lines)):
            if i < len(lines) and (lines[i].startswith('## ') or lines[i].startswith('# ')):
                toc_end = i - 1
                break
        if toc_end is None:  # If we reach the end of the file
            toc_end = len(lines) - 1
    
    # Process the table of contents links
    if toc_start is not None and toc_end is not None:
        for i in range(toc_start + 1, toc_end + 1):
            line = lines[i]
            # Look for markdown-style links: [text](#anchor)
            if "[" in line and "](#" in line and ")" in line:
                link_start = line.find("[")
                link_mid = line.find("](#", link_start)
                link_end = line.find(")", link_mid)
                
                if link_start != -1 and link_mid != -1 and link_end != -1:
                    link_text = line[link_start + 1:link_mid]
                    anchor = line[link_mid + 3:link_end]
                    
                    # Create a Sphinx-compatible reference
                    lines[i] = line[:link_start] + f"{{ref}}`{link_text}`" + line[link_end + 1:]
    
    # Add reference labels before each section header
    for i, line in reversed(list(enumerate(lines))):
        if line.startswith('## '):
            header_text = line[3:].strip()
            label_line = f"(label-{header_text.lower().replace(' ', '-')})=\n"
            lines.insert(i, label_line)
    
    # Write the processed content to the output file
    with output_path.open("w+", encoding='utf-8') as outfile:
        outfile.write("\n".join(lines))


# Get paths for README and the output file
readme_source = base_dir / "README.md"
index_target = Path.cwd() / "README.md"

# Process README and save as index.md for Sphinx documentation
process_readme(readme_source, index_target)

# No symlinks or copies of the original README needed

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

# MyST-Parser configuration
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

# Suppress specific warnings
suppress_warnings = [
    "config.cache",
    "myst.header",  # Suppress warnings about duplicate headers
    "myst.xref_missing"  # Suppress warnings about missing references initially
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
