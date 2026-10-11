# Contributing

Contributions are welcome, and they are greatly appreciated! Every
little bit helps, and credit will always be given.

## Bug reports

When `reporting a bug <https://github.com/Haight3/altira/issues>`\_ please use the `bug` template and include:

-   Your operating system name and version.
-   Any details about your local setup that might be helpful in troubleshooting.
-   Detailed steps to reproduce the bug.

## Documentation improvements

Altira could always use more documentation, whether as part of the
official Altira docs, in docstrings, or even on the web in blog posts,
articles, and such.

## Feature requests and feedback

The best way to send feedback is to file an issue at https://github.com/Haight3/altira/issues.

If you are proposing a feature use the template `request-feature` and :

-   Explain in detail how it would work.
-   eep the scope as narrow as possible, to make it easier to implement.
-   Remember that this is a volunteer-driven project, and that code contributions are welcome :)

## Development

To set up `altira` for local development:

1. Fork `altira <https://github.com/Haight3/altira>`\_
   (look for the "Fork" button).
2. Clone your fork locally::

    git clone git@github.com:YOURGITHUBNAME/altira.git

3. Create a branch for local development::

    git checkout -b name-of-your-bugfix-or-feature

    Now you can make your changes locally.

4. Install the project with the development dependencies::

    python -m pip install -e .[dev]

5. Run the test suite before opening a pull request::

    pytest

6. Run linting and formatting::

    python -m ruff check --fix .
    python -m ruff format .

7. Commit your changes and push your branch to GitHub::

    git add .
    git commit -m "Your detailed description of your changes."
    git push origin name-of-your-bugfix-or-feature

8. Submit a pull request through the GitHub website.

### Pull Request Guidelines

If you need some code review or feedback while you're developing the code just make the pull request.

For merging, you should:

1. Include passing tests (run `pytest`).
2. Update documentation when there's new API, functionality etc.
3. Add a note to `../src/.info/CHANGELOG.md` about the changes.
4. Add yourself to `../src/.info/AUTHORS.md`.

### Tips

To run a subset of tests::

    pytest -k test_myfeature
