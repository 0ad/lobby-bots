# Copyright (C) 2021 Wildfire Games.
# This file is part of 0 A.D.
#
# 0 A.D. is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# 0 A.D. is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with 0 A.D.  If not, see <http://www.gnu.org/licenses/>.

"""Tests for utility functions."""

from contextlib import redirect_stderr
from io import BytesIO, StringIO
from unittest import TestCase
from unittest.mock import patch

from xpartamupp.utils import ArgumentParserWithConfigFile


class TestArgumentParserWithConfigFile(TestCase):
    """Test ArgumentParser with support for config files."""

    def test_missing_config_file(self):
        """Test specified, but not existing config file."""
        config_file_name = "config.toml"
        args = ["--config-file", config_file_name]

        with patch("xpartamupp.utils.open") as file_open_mock:
            file_open_mock.side_effect = FileNotFoundError()

            parser = ArgumentParserWithConfigFile()
            parser.add_argument("-v", action="count", dest="verbosity", default=0)

            stderr = StringIO()
            with self.assertRaises(SystemExit), redirect_stderr(stderr):
                parser.parse_args(args=args)
            self.assertIn(
                f'The given configuration file "{config_file_name}" ' "doesn't exist.",
                stderr.getvalue(),
            )

        file_open_mock.assert_called_once_with(config_file_name, "rb")

    def test_config_file(self):
        """Test successful reading options from a config file."""
        config_file_name = "config.toml"
        args = ["--config-file", config_file_name]

        with patch("xpartamupp.utils.open") as file_open_mock:
            file_open_mock.return_value = BytesIO(b"verbosity = 2\n")

            parser = ArgumentParserWithConfigFile()
            parser.add_argument("-v", action="count", dest="verbosity", default=0)
            parsed_args = parser.parse_args(args=args)

        file_open_mock.assert_called_once_with(config_file_name, "rb")
        self.assertEqual(2, parsed_args.verbosity)

    def test_config_file_invalid_option(self):
        """Test invalid options in the config file."""
        config_file_name = "config.toml"
        args = ["--config-file", config_file_name]

        with patch("xpartamupp.utils.open") as file_open_mock:
            file_open_mock.return_value = BytesIO(b'foo = "bar"\n')

            parser = ArgumentParserWithConfigFile()
            parser.add_argument("-v", action="count", dest="verbosity", default=0)

            stderr = StringIO()
            with self.assertRaises(SystemExit), redirect_stderr(stderr):
                parser.parse_args(args=args)
            self.assertIn(
                "The configuration file contains an unrecognized option: foo", stderr.getvalue()
            )

    def test_config_file_with_cmdl_option(self):
        """Test overwriting an option in config."""
        config_file_name = "config.toml"
        args = ["--config-file", config_file_name, "-v"]

        with patch("xpartamupp.utils.open") as file_open_mock:
            file_open_mock.return_value = BytesIO(b"verbosity = 2\n")

            parser = ArgumentParserWithConfigFile()
            parser.add_argument("-v", action="count", dest="verbosity", default=0)
            parsed_args = parser.parse_args(args=args)

        file_open_mock.assert_called_once_with(config_file_name, "rb")
        self.assertEqual(1, parsed_args.verbosity)

    def test_namespace(self):
        """Test functionality of the namespace parameter."""

        class Namespace:
            verbosity = 3

        args = ["-v"]
        namespace = Namespace()

        with patch("xpartamupp.utils.open") as file_open_mock:
            parser = ArgumentParserWithConfigFile()
            parser.add_argument("-v", action="count", dest="verbosity", default=0)
            parsed_args = parser.parse_args(args=args, namespace=namespace)

        file_open_mock.load.assert_not_called()
        self.assertIs(namespace, parsed_args)
        self.assertEqual(4, parsed_args.verbosity)

    def test_config_file_and_namespace(self):
        """Test combination of config file and namespace parameter."""

        class Namespace:
            verbosity = 3

        config_file_name = "config.toml"
        args = ["--config-file", config_file_name]
        namespace = Namespace()

        with patch("xpartamupp.utils.open") as file_open_mock:
            file_open_mock.return_value = BytesIO(b"verbosity = 2\n")

            parser = ArgumentParserWithConfigFile()
            parser.add_argument("-v", action="count", dest="verbosity", default=0)
            parsed_args = parser.parse_args(args=args, namespace=namespace)

        file_open_mock.assert_called_once_with(config_file_name, "rb")
        self.assertIs(namespace, parsed_args)
        self.assertEqual(2, parsed_args.verbosity)
