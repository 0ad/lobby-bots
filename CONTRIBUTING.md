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

## Set up a custom lobby and run the bots locally

Before submitting pull requests, please test changes you made. If you need a custom lobby
environment for that, you can use the code and instructions from
https://github.com/0ad/lobby-infrastructure to set up a virtual machine running the lobby and
instances of the bots.

Once started there is an ejabberd server running in a virtual machine, exposing the ports
necessary to connect to it on localhost. This ejabberd server has the proper configuration set to
be used as lobby for pyrogenesis, including a MUC room called `arena` and has accounts registered
for `xpartamupp`, `echelon` and `modbot`. Additional accounts can be created through `ejabberdctl`,
after connecting to the virtual machine using SSH. An instance of each bot is running in the
virtual machine as well.

To test your own code you can either update the lobby bots in the virtual machine to use your
modified code or stop their instances and run them locally and connect them to the ejabberd
instance in the virtual machine.

Once done, all which is left to do now is to tell pyrogenesis to use the lobby running in the
virtual machine. You can do that by starting it with the following command line options. Ensure
to back up your original configuration before, as starting pyrogenesis like that will overwrite the
existing config:

```
pyrogenesis \
  -conf=lobby.room:arena \
  -conf=lobby.server:localhost \
  -conf=lobby.stun.enabled:true \
  -conf=lobby.stun.server:localhost \
  -conf=lobby.xpartamupp:xpartamupp \
  -conf=lobby.echelon:echelon \
  -conf=lobby.login:player1 \
  -conf=lobby.password:player1 \
  -conf=lobby.tls:false
```

Do note that it currently isn't possible to successful log in into the lobby when typing the
password interactively in pyrogenesis, unless the user was created via pyrogenesis as well, as
pyrogenesis applies client-side hashing of the password and uses the hashed password as actual
password. So you have to provide the password as a command line parameter as shown above.
