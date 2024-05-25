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

"""Collection of utility functions used by the XMPP-bots."""

import tomllib
from argparse import ArgumentParser, Namespace
from collections.abc import Sequence


class ArgumentParserWithConfigFile(ArgumentParser):
    """ArgumentParser with support for values in TOML files.

    This extends the ArgumentParser class by a pre-defined
    `--config-file` parameter, which allows storing config options in
    TOML files, instead of providing them as command line options.
    The options in the configuration file have to be named like the
    destination variables of the parser arguments.
    If an option is present in the configuration file and in the
    command line options, the value from the command line options takes
    precedence.
    """

    def __init__(self, *args, **kwargs):
        """Create a parser with an option for a config file."""
        super().__init__(*args, **kwargs)
        self.add_argument(
            "--config-file",
            help="Path to a TOML configuration file. Options in the configuration "
            "will be used as defaults for command line options and will be "
            "overwritten if the command line option is provided with a "
            "non-default value.",
        )

    def parse_args(
        self, args: Sequence[str] | None = None, namespace: Namespace | None = None
    ) -> Namespace:
        """Parse arguments and use values from TOML as default."""
        parsed_args = super().parse_args(args, namespace)

        if not parsed_args.config_file:
            delattr(parsed_args, "config_file")
            return parsed_args

        try:
            with open(parsed_args.config_file, "rb") as r:
                toml_data = tomllib.load(r)
        except FileNotFoundError:
            self.error(f'The given configuration file "{parsed_args.config_file}" doesn\'t exist.')

        delattr(parsed_args, "config_file")

        default_args = vars(super().parse_args([]))
        changed_args = []

        for key, value in vars(parsed_args).items():
            if key in default_args and value == default_args[key]:
                continue

            changed_args.append(key)

        for key, value in toml_data.items():
            if key not in default_args:
                self.error(f"The configuration file contains an unrecognized option: {key}")
            if key in changed_args:
                continue
            setattr(parsed_args, key, value)

        return parsed_args
