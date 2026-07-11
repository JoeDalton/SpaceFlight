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
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_book_theme'
html_static_path = ['_static']

# -- Options for MyST ---------------------------------------------------------

myst_enable_extensions = [
    'colon_fence',
    'fieldlist',
]

# -- Options for autodoc2 -----------------------------------------------------

autodoc2_render_plugin = "myst"
autodoc2_packages = [
    "../../src/space_flight",
]
