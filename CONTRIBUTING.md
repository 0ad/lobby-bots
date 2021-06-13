# How to contribute

This page contains information relevant for contributing to this repository. Before submitting any
changes as pull requests, please read it carefully.

## pre-commit

We use the [`pre-commit`](https://pre-commit.com/) framework for checking the quality of the code
and to detect various other problems. What to check is configured in `.pre-commit-config.yaml` and
includes checks for formatting of source files, best practices for Python, but also checks for
common typos and much more.

The configured `pre-commit` hooks run for every submitted pull request and their result is shown in
the messages section at the bottom of each pull request page on Github.

Pull requests should pass the checks, before they're being merged to ensure a certain level of
code quality.

You can (and are encouraged to) run the `pre-commit` hooks locally, either as part of every commit
or manually, to detect and fix problems before you push your changes.

Doing so is straight forward. Just install `pre-commit`:

```
$ pip3 install pre-commit
```

Once done you can run the checks manually for all files in the repository, by calling the following
command in the repository root:

```
$ pre-commit run -a
```

To enable `pre-commit` to automatically check all changed files for every commit, you can activate
it, by running the following command in the repository root as well:

```
$ pre-commit install
```

For more information about the pre-commit framework, check out their website:
https://pre-commit.com/.

## Unit tests

We use unit tests to test that individual parts of the code work as expected. Any submitted changes
should have associated unit tests, so we can be confident that the code does what it should.
Submissions should also not result in less unit test coverage than we had before.

The unit tests use Python's [`unittest`](https://docs.python.org/3/library/unittest.html)
framework and [`hypothesis`](https://hypothesis.readthedocs.io/) for property-based testing.
They're executed automatically for every submitted pull request and their result is shown in the
messages section at the bottom of the pull request page on Github.

To run the unit tests locally, you can use [`tox`](https://tox.readthedocs.io/), which handles the
creation of an environment with the necessary dependencies installed for you. To install `tox` run:

```
pip3 install tox
```

Afterwards you can run the tests by calling `tox` from the repository root:

```
tox
```

Running `tox` locally uses the Python 3 version available as default Python version on your system.
If you have multiple Python versions installed and want to use a certain one, you can specify which
one to use as command line parameter:

```
tox -e py37
```
