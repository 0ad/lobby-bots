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

## Docker

To offer an easy way to run the bots locally for testing, this repository contains a Docker
Compose configuration to run Docker containers for ejabberd, XpartaMuPP and EcheLOn.

To run the docker containers you need to have [Docker](https://www.docker.com/) and
[Docker Compose](https://docs.docker.com/compose/install/) installed.

After installing them, you can start the Docker containers like that:

```
DOCKER_BUILDKIT=1 docker-compose up
```

Once started there is an ejabberd server running in a Docker container, exposing the ports
necessary to connect to it on localhost. This ejabberd server has the proper configuration set to
be used as lobby for pyrogenesis, including a MUC room called `arena` and has accounts registered
for `xpartamupp`, `echelon`. There also exist three additional accounts (`player1`, `player2`,
`player3`) for testing purposes. The password for all of these accounts is identical to the
username. If necessary additional accounts can be created through `ejabberdctl`.

To be able to connect with pyrogenesis to the started ejabberd instance, you'll now need to add an
entry to your `hosts`-file to resolve `ejabberd` to `127.0.0.1`. If you're running Linux that means
that you'll need to add the following line to `/etc/hosts`. If you're running another operating
system the [location of the `hosts`-file](https://en.wikipedia.org/wiki/Hosts_(file)#Location_in_the_file_system)
might be different.

```
127.0.0.1   ejabberd
```

Once done, all which is left to do now is to tell pyrogenesis to use the lobby running in the
Docker containers. You can do that by starting it with the following command line options. Ensure
to back up your original configuration before, as starting pyrogenesis like that will overwrite the
existing config:

```
pyrogenesis \
  -conf=lobby.room:arena \
  -conf=lobby.server:ejabberd \
  -conf=lobby.stun.enabled:true \
  -conf=lobby.stun.server:ejabberd \
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

### mod_ipstamp

The instructions above don't install `mod_ipstamp`, as `mod_ipstamp` is usually not necessary for
testing the bots and installing it requires some additional steps after the ejabberd container is
up. In case you want to in `mod_ipstamp`, here are the commands you need to run to do so:

```
docker-compose exec ejabberd bin/ejabberdctl module_install mod_ipstamp
docker-compose exec ejabberd \
  sed -i 's#^modules:$#modules:\n  mod_ipstamp: {}#g' /opt/ejabberd/conf/ejabberd.yml
docker-compose exec ejabberd bin/ejabberdctl reload_config
```

### Persistent ratings database

With the instructions to run the Docker containers above EcheLOn's ratings database is ephemeral
and will get recreated when rebuilding the Docker images. If you want to have a persistent ratings
database you can also use outside the Docker Container, a few additional steps are necessary.

First of all you'll need to install the bots itself on your host machine, as they contain a
command to create database files. You can do that like this:

```
pip install -e .
```

As a next step you can create the ratings SQLite database file:

```
echelon-db create
```

Depending on your operating system you'll also need to change the file permissions on the newly
created file to allow the Docker container to access it for reading and writing later on. On Linux
you can do that with the following command:

```
setfacl -m u:999:rw lobby_rankings.sqlite3
```

Finally, you now have to start the Docker container slightly different to mount the created database
file as volume into EcheLOn's container:

```
docker-compose -f docker-compose.yml -f docker-compose.persistent-db.yml up
```
