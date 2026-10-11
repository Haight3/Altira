========
Overview
========
Altira v-2026.10.3[v-2026.10.0]


.. start-badges

.. list-table::
    :stub-columns: 1

    * - docs
      - |docs|
    * - tests

.. |docs| image:: https://readthedocs.org/projects/altira/badge/?style=flat
    :target: https://altira.readthedocs.io/
    :alt: Documentation Status
.. |commits-since| image:: https://img.shields.io/github/commits-since/Haight3/altira/v2026.10.0.svg
    :alt: Commits since latest release
    :target: https://github.com/Haight3/altira/compare/v2026.10.0...main


.. end-badges

An example package. Generated with cookiecutter-pylibrary.

Installation
============

::

    pip install altira

You can also install the in-development version with::

    pip install https://github.com/Haight3/altira/archive/main.zip


Documentation
=============

https://altira.readthedocs.io/

Development
===========

Install the project in editable mode with the development dependencies::

    pip install -e .[dev]

Run the test suite directly with::

    pytest

Run linting and formatting with::

    python -m ruff check --fix .
    python -m ruff format .

To include coverage use::

    pytest --cov --cov-report=term-missing
