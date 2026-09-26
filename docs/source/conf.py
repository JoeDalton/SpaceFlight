# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'SpaceFlight'
copyright = '2026, Guilhem Lavabre'
author = 'Guilhem Lavabre'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'autodoc2',
    'sphinx_book_theme',
    'myst_parser',
    'sphinx_copybutton',
]

templates_path = ['_templates']
# Summary.md is the MkDocs literate-nav file; the Sphinx toctree is in index.md.
exclude_patterns = ['Summary.md']


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_book_theme'
html_static_path = []

# -- Options for MyST ---------------------------------------------------------

myst_enable_extensions = [
    'colon_fence',
    'fieldlist',
]
# GitHub-style heading slugs, so in-page links like (#where-things-live)
# resolve the same way in Sphinx as when browsing the repository.
myst_heading_anchors = 3

# -- Options for autodoc2 -----------------------------------------------------

autodoc2_render_plugin = "myst"
autodoc2_packages = [
    "../../src/space_flight",
]
