# -*- coding: utf-8 -*-
import os
from importlib.metadata import PackageNotFoundError, version as get_version
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.coverage',
    'sphinx.ext.doctest',
    'sphinx.ext.extlinks',
    'sphinx.ext.ifconfig',
    'sphinx.ext.napoleon',
    'sphinx.ext.todo',
    'sphinx.ext.viewcode'
]

source_suffix = ['.rst']

master_doc = 'index'
project = 'Altira'
year = '2026'
author = 'Ismail Baris'
copyright = '{0}, {1}'.format(year, author)
try:
    version = release = get_version('altira')
except PackageNotFoundError:
    version = release = "2026.10.2"

pygments_style = 'trac'
templates_path = ['.']
extlinks = {
    'issue': ('https://github.com/Haight3/altira/issues/%s', '#'),
    'pr': ('https://github.com/Haight3/altira/pull/%s', 'PR #'),
}
# on_rtd is whether we are on readthedocs.org
on_rtd = os.environ.get('READTHEDOCS', None) == 'True'

if not on_rtd:  # only set the theme if we're building docs locally
    html_theme = 'sphinx_rtd_theme'

html_use_smartypants = True
html_last_updated_fmt = '%b %d, %Y'
html_split_index = False
html_sidebars = {
    '**': ['searchbox.html', 'globaltoc.html', 'sourcelink.html'],
}
html_short_title = '%s-%s' % (project, version)

napoleon_use_ivar = True
napoleon_use_rtype = False
napoleon_use_param = False
