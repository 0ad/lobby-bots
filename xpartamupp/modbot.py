#!/usr/bin/env python3
# Copyright (C) 2024 Wildfire Games.
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

"""0ad XMPP-bot for moderation related topics."""

import asyncio
import logging
import re
import shlex
import ssl

from argparse import (ONE_OR_MORE, PARSER, SUPPRESS, Action, ArgumentDefaultsHelpFormatter,
                      ArgumentError, ArgumentParser, HelpFormatter, Namespace,
                      _MutuallyExclusiveGroup)
from asyncio import Future, Task
from datetime import datetime, timezone
from typing import Iterable, Optional, Tuple

import dateparser

from slixmpp import ClientXMPP, Message
from slixmpp.exceptions import IqError
from slixmpp.jid import JID
from slixmpp.plugins.xep_0045 import MUCPresence
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.sqlite.base import SQLiteDialect
from sqlalchemy.orm import scoped_session, sessionmaker

from xpartamupp.lobby_moderation_db import (JIDNickWhitelist, KickEvent, Moderator, MuteEvent,
                                            UnmuteEvent)


class ModCmdParser(ArgumentParser):
    """Custom argument parser for commands via XMPP."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the argument parser.

        Sets custom options used for ensuring desired behavior when
        used for commands via XMPP.
        """
        kwargs["add_help"] = False
        kwargs["exit_on_error"] = False
        kwargs["prefix_chars"] = [None]
        super().__init__(*args, **kwargs)
        self._positionals = self.add_argument_group("arguments")

    def _check_value(self, action: Action, value: str) -> None:
        """Check that a value is a valid choice.

        In contrast to the parent implementation this modifies the
        exception message to better fit our needs.
        """
        if action.choices is not None and value not in action.choices:
            raise ArgumentError(None, f"invalid command: !{value}")

    def parse_known_args(self, args=None,  # pylint: disable=inconsistent-return-statements
                         namespace=None) -> Tuple[Namespace, list[str]]:
        """Parse known arguments.

        Adds a help command for printing usage information and
        otherwise calls the parent implementation.
        """
        if args and args[0] == "help":
            if len(args) == 2:
                self.parse_known_args([args[1], args[0]])
            self.error("")
        try:
            return super().parse_known_args(args, namespace)
        except ArgumentError as exc:
            self.error(exc.message)

    def error(self, message: str) -> None:
        """Handle invalid data.

        Instead of printing to stderr and exiting the program, like the
        implementation in ArgumentParser does, raise an exception, so
        we can handle it in the usual control flow.
        """
        if message:
            raise ValueError(message + "\n\n" + self.format_help())
        raise ValueError(self.format_help())


class ModBotArgumentsFormatter(HelpFormatter):
    """Custom arguments formatter for commands via XMPP."""

    def _format_action_invocation(self, action: Action) -> str:
        """Format actions as desired."""
        if not action.option_strings and action.choices is not None:
            return self._format_choices(action)
        return super()._format_action_invocation(action)

    def _format_args(self, action: Action, default_metavar: str) -> str:
        """Format arguments as desired."""
        if action.nargs == PARSER and action.choices is not None:
            return self._format_choices(action)
        return super()._format_args(action, default_metavar)

    def _format_choices(self, action: Action) -> str:
        """Format choice values."""
        choice_strs = ["!" + str(choice) for choice in action.choices]
        return "%s" % ", ".join(choice_strs)

    def add_usage(self, usage: Optional[str], actions: list[Action],
                  groups: Iterable[_MutuallyExclusiveGroup], prefix=None) -> None:
        """Suppress adding usage, as we only use help."""
        super().add_usage(SUPPRESS, actions, groups, prefix)


class ModBotSubparserArgumentFormatter(HelpFormatter):
    """Custom arguments formatter for subparsers."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the argument formatter for subcommands."""
        super().__init__(*args, **kwargs)
        self._prog = "!" + self._prog[1:]

    def _format_args(self, action: Action, default_metavar: str) -> str:
        """Format arguments as desired."""
        if action.nargs == ONE_OR_MORE:
            return "%s" % default_metavar
        return super()._format_args(action, default_metavar)


def get_cmd_parser() -> ArgumentParser:
    """Return an instance of the moderation command parser.

    This parser is used to parse commands submitted via XMPP.
    """
    cmd_parser = ModCmdParser(add_help=False, allow_abbrev=False,
                              formatter_class=ModBotArgumentsFormatter, prog="")

    cmd_subparsers = cmd_parser.add_subparsers(required=True, dest="command", title="commands")

    mute_parser = cmd_subparsers.add_parser("mute",
                                            formatter_class=ModBotSubparserArgumentFormatter)
    mute_parser.add_argument("user", help="nick of the user to mute")
    mute_parser.add_argument("duration",
                             help='a duration like 5m, 10h. Multi-word terms work as well, but '
                                  'need to be put in quotes like "2 months"')
    mute_parser.add_argument("reason", nargs="+", help="violation of the terms, which is the "
                                                       "reason for the mute. It'll also be shown "
                                                       "to the user.")
    cmd_subparsers.add_parser("mutelist", formatter_class=ModBotSubparserArgumentFormatter)
    unmute_parser = cmd_subparsers.add_parser("unmute",
                                              formatter_class=ModBotSubparserArgumentFormatter)
    unmute_parser.add_argument("user", help="nick of the user to unmute")
    unmute_parser.add_argument("reason", nargs="+", help="reason for unmuting the user. It won't"
                                                         "be shown to the user.")
    kick_parser = cmd_subparsers.add_parser("kick",
                                            formatter_class=ModBotSubparserArgumentFormatter)
    kick_parser.add_argument("user", help="nick of the user to kick")
    kick_parser.add_argument("reason", nargs="+", help="violation of the terms, which is the "
                                                       "reason for the kick. It'll also be shown "
                                                       "to the user.")
    return cmd_parser


def coroutine_exception_handler(task: Task) -> None:
    """Log asyncio task exceptions."""
    if task.exception():
        logging.error("asyncio task failed", exc_info=task.exception())


def create_task(*args, **kwargs) -> Task:
    """Create asyncio task with logging of exceptions."""
    task = asyncio.create_task(*args, **kwargs)
    task.add_done_callback(coroutine_exception_handler)
    return task


class ModBot(ClientXMPP):
    """Main class which for reacting to moderation requests."""

    def __init__(self, jid: JID, password: str, nick: str, rooms: list[JID], command_room: JID,
                 db_url: str, verify_certificate: bool = True) -> None:
        """Initialize ModBot.

        Arguments:
             jid (JID): JID to use for authentication
             password (str): password to use for authentication
             nick (str): Nick to use in MUC
             rooms (list(JID)): List of XMPP MUC rooms to join
             command_room (JID): XMPP MUC room to join for receiving commands
             db_url (str): URL for the database connection
             verify_certificate (bool): Whether to verify the TLS
                                        certificate provided by the
                                        server

        """
        super().__init__(jid, password)

        engine = create_engine(db_url)

        session_factory = sessionmaker(bind=engine)
        self.db_session = scoped_session(session_factory)

        if isinstance(engine.dialect, SQLiteDialect):
            self.db_session.execute(text("PRAGMA busy_timeout=10000"))

        if not verify_certificate:
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

        self.whitespace_keepalive = False

        self.shutdown = Future()
        self._connect_loop_wait_reconnect = 0

        self.rooms = rooms
        self.command_room = command_room
        self.nick = nick

        self.unmute_tasks: dict[JID, asyncio.Task] = {}
        self.cmd_parser = get_cmd_parser()

        self.add_event_handler("session_start", self._session_start)

        for room in self.rooms:
            self.add_event_handler(f"muc::{room}::presence", self._muc_presence_change)
        self.add_event_handler(f"muc::{self.command_room}::message", self._muc_command_message)

        self.add_event_handler("failed_all_auth", self._shutdown)
        self.add_event_handler("disconnected", self._reconnect)

    async def _session_start(self, _) -> None:
        """Join MUC channels and announce presence.

        Also schedules unmute tasks for all users which are currently
        muted.
        """
        self._connect_loop_wait_reconnect = 0
        for room in self.rooms:
            await self.plugin["xep_0045"].join_muc_wait(room, self.nick)
        await self.plugin["xep_0045"].join_muc_wait(self.command_room, self.nick)
        self.send_presence()
        self.get_roster()

        with self.db_session() as db:
            for mute in db.execute(
                    select(MuteEvent).filter_by(is_active=True).order_by(MuteEvent.mute_end)
            ).scalars():
                task = create_task(self._unmute_after_mute_ended(mute.mute_end, JID(mute.player)))
                self.unmute_tasks[mute.player] = task

        logging.info("ModBot started")

    async def _shutdown(self, _) -> None:
        """Shut down ModBot.

        This is used for aborting connection tries in case the
        configured credentials are wrong, as further connection tries
        won't succeed in this case.
        """
        logging.error("Can't log in. Aborting reconnects.")
        self.abort()
        self.shutdown.set_result(True)

    async def _reconnect(self, _) -> None:
        """Trigger a reconnection attempt.

        This triggers a reconnection attempt and implements the same
        back-off behavior as the ClientXMPP.connect() method does to
        avoid too frequent reconnection tries.

        To avoid trying to unmute users while not being connected, this
        also cancels all running unmute tasks. These tasks are being
        rescheduled once a new connection got established.
        """
        for key in self.unmute_tasks:
            try:
                task = self.unmute_tasks.pop(key)
            except KeyError:
                pass
            else:
                task.cancel()

        if self._connect_loop_wait_reconnect > 0:
            self.event("reconnect_delay", self._connect_loop_wait_reconnect)
            await asyncio.sleep(self._connect_loop_wait_reconnect)

        self._connect_loop_wait_reconnect = self._connect_loop_wait_reconnect * 2 + 1

        self.connect()

    async def _muc_presence_change(self, presence: MUCPresence) -> None:
        """Set mute state for joining players.

        Arguments:
            presence (slixmpp.stanza.presence.Presence): Received
                presence stanza.

        """
        if presence["type"] == "unavailable":
            return

        nick = str(presence["muc"]["nick"])
        jid = JID(presence["muc"]["jid"])
        role = presence["muc"]["role"]
        room = presence["muc"]["room"]
        logging.debug("User \"%s\" connected with a nick \"%s\".", jid, nick)

        if not await self._check_matching_nick(jid, nick, JID(presence["muc"]["room"])):
            return

        with self.db_session() as db:
            mute_event = db.execute(
                select(MuteEvent)
                .filter_by(is_active=True)
                .filter_by(player=str(jid.bare).lower())
                .order_by(MuteEvent.mute_end.desc())
            ).scalars().first()

        if mute_event and role == "participant":
            try:
                await self.plugin["xep_0045"].set_role(room, nick, "visitor",
                                                       reason=mute_event.reason)
            except IqError:
                logging.exception("Muting %s (%s) on join failed.", nick, jid)
        elif not mute_event and role == "visitor":
            try:
                await self.plugin["xep_0045"].set_role(room, nick, "participant")
            except IqError:
                logging.exception("Unmuting %s (%s) on join failed.", nick, jid)

    async def _muc_command_message(self, msg: Message) -> None:
        """Process messages in the command MUC room.

        Detect commands posted in the command MUC room and act on them.

        Arguments:
            msg (Message): Received MUC message
        """
        msg_body = msg["body"]

        if msg["delay"]["stamp"]:
            return

        moderator = JID(self.plugin["xep_0045"].get_jid_property(msg["from"].bare, msg["mucnick"],
                                                                 "jid")).bare

        try:
            command = re.match(rf"({self.nick.lower()}:?\s*!?|!)(.+)", msg_body, re.IGNORECASE)[2]
        except TypeError:
            return

        with self.db_session() as db:
            if not db.get(Moderator, moderator):
                logging.warning("User %s, who is not a moderator, tried to execute a command",
                                msg["from"])
                return

        try:
            args = self.cmd_parser.parse_args(shlex.split(command))
        except ValueError as exc:
            self.send_message(mto=msg["from"].bare, mbody=str(exc), mtype="groupchat")
            return

        if args.command == "mutelist":
            await self.send_mutelist()
            return

        user = JID(args.user + "@" + self.boundjid.domain)
        moderator = JID(moderator)
        reason = " ".join(args.reason)

        if args.command == "mute":
            await self.mute_user(user, args.duration, moderator, reason)
        elif args.command == "unmute":
            await self.unmute_user(user, moderator, reason)
        elif args.command == "kick":
            await self.kick_user(user, moderator, reason)

    async def mute_user(self, user: JID, duration: str, moderator: JID, reason: str) -> None:
        """Mute a user.

        Arguments:
            user (JID): JID of the user to mute
            duration (str): human-readable duration how long to mute
                            the user
            moderator (JID): JID of the moderator who issued the mute
                             event
            reason (str): reason for muting the user
        """
        dateparser_settings = {"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True,
                               "PREFER_DATES_FROM": "future"}
        # Workaround for https://github.com/scrapinghub/dateparser/issues/1012
        duration = re.sub(r"(\d)([dhms])(\d)", r"\1\2 \3", duration)
        mute_end: datetime = dateparser.parse(duration, settings=dateparser_settings)
        if not mute_end or (not datetime.now(tz=timezone.utc) < mute_end <= dateparser.parse(
                "5 years", settings=dateparser_settings)):
            self.send_message(mto=self.command_room,
                              mbody="The mute duration must be between 0 seconds and 5 years",
                              mtype="groupchat")
            return

        with self.db_session() as db:
            active_mute = db.execute(
                select(MuteEvent)
                .filter_by(is_active=True)
                .filter_by(player=str(user))
                .order_by(MuteEvent.mute_end.desc())
            ).scalars().first()
            if active_mute:
                self.send_message(mto=self.command_room,
                                  mbody=f"\"{user.node}\" is already muted until "
                                        f"{active_mute.mute_end.strftime('%Y-%m-%d %H:%M:%S %Z')} "
                                        f"for the following reason:\n"
                                        f"> {active_mute.reason}",
                                  mtype="groupchat")
                return

            mute_event = MuteEvent(player=str(user), moderator=str(moderator), mute_end=mute_end,
                                   reason=reason)
            db.add(mute_event)
            db.commit()

        for room in self.rooms:
            nick = self._get_nick_with_proper_case(user.node, room)
            if not nick:
                continue
            try:
                await self.plugin["xep_0045"].set_role(room, nick, "visitor", reason=reason)
            except IqError:
                msg = f"Muting \"{nick}\" failed."
                logging.exception(msg)
                self.send_message(mto=self.command_room, mbody=msg, mtype="groupchat")

        task = create_task(self._unmute_after_mute_ended(mute_end, user))
        try:
            old_task = self.unmute_tasks.pop(user)
        except KeyError:
            pass
        else:
            old_task.cancel()
        self.unmute_tasks[user] = task

        self.send_message(mto=self.command_room,
                          mbody=f"\"{user.node}\" is now muted until "
                                f"{mute_end.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                          mtype="groupchat")

    async def send_mutelist(self) -> None:
        """Send a list of muted users to the command MUC room."""
        muted_users = {}
        max_nick_length = 0
        message_content = []

        with self.db_session() as db:
            for mute in db.execute(
                    select(MuteEvent).filter_by(is_active=True).order_by(MuteEvent.player)
            ).scalars():
                nick = JID(mute.player).node
                muted_users[nick] = mute
                max_nick_length = max(max_nick_length, len(nick))

            for nick, mute in muted_users.items():
                message_content.append(
                    f"{nick.ljust(max_nick_length)}\t"
                    f"{mute.mute_end.strftime('%Y-%m-%d %H:%M:%S %Z')}\t{mute.reason}")

        if muted_users:
            header = "*nick*".ljust(max_nick_length) + "\t*muted until*".ljust(
                23) + "\t*reason*\n"
            self.send_message(mto=self.command_room, mbody=header + "\n".join(message_content),
                              mtype="groupchat")
            return

        self.send_message(mto=self.command_room, mbody="No users muted right now.",
                          mtype="groupchat")

    async def unmute_user(self, user: JID, moderator: JID, reason: str) -> None:
        """Unmute a user.

        Arguments:
            user (JID): JID of the user to unmute
            moderator (JID): JID of the moderator who issued the unmute
                             event
            reason (str): reason for unmuting the user
        """
        with self.db_session() as db:
            unmute_event = UnmuteEvent(player=str(user), moderator=str(moderator), reason=reason)
            db.add(unmute_event)
            db.commit()

        for room in self.rooms:
            nick = self._get_nick_with_proper_case(user.node, room)
            if not nick:
                continue
            try:
                await self.plugin["xep_0045"].set_role(room, nick, "participant", reason=reason)
            except IqError:
                msg = f"Unmuting \"{nick}\" failed."
                logging.exception(msg)
                self.send_message(mto=self.command_room, mbody=msg, mtype="groupchat")

        try:
            task = self.unmute_tasks.pop(user)
        except KeyError:
            pass
        else:
            task.cancel()

        self.send_message(mto=self.command_room, mbody=f"\"{user.node}\" is now unmuted again.",
                          mtype="groupchat")

    async def kick_user(self, user: JID, moderator: JID, reason: str) -> None:
        """Kick a user.

        Arguments:
            user (JID): JID of the user to kick
            moderator (JID): JID of the moderator who issued the kick
                             event
            reason (str): reason for kicking the user
        """
        with self.db_session() as db:
            kick_event = KickEvent(player=str(user), moderator=str(moderator), reason=reason)
            db.add(kick_event)
            db.commit()

        rooms_kicked_from = []
        rooms_kick_failed = []
        for room in self.rooms:
            nick = self._get_nick_with_proper_case(user.node, room)
            if not nick:
                continue
            try:
                await self.plugin["xep_0045"].set_role(room, nick, "none", reason=reason)
            except IqError:
                logging.exception("Kicking user %s failed", user)
                rooms_kick_failed.append(room)
                continue

            rooms_kicked_from.append(room)

        if not rooms_kicked_from:
            self.send_message(mto=self.command_room,
                              mbody=f"Kicking \"{user.node}\" failed. Nobody with this nick is "
                                    "online right now.",
                              mtype="groupchat")
            return

        rooms_kicked_from_str = {", ".join([str(room.local) for room in rooms_kicked_from])}
        self.send_message(mto=self.command_room,
                          mbody=f"Kicked \"{user.node}\" from the following MUC rooms: "
                                f"{rooms_kicked_from_str}",
                          mtype="groupchat")

        if rooms_kick_failed:
            rooms_kick_failed_str = {", ".join([str(room.local) for room in rooms_kick_failed])}
            self.send_message(mto=self.command_room,
                              mbody=f"Kicking \"{user.node}\" failed for the following MUC "
                                    f"rooms: {rooms_kick_failed_str}",
                              mtype="groupchat")
            return

    async def _check_matching_nick(self, jid: JID, nick: str, room: JID) -> bool:
        """Kick users whose local JID part doesn't match their nick.

        Arguments:
            jid (JID): JID of the connected user
            nick (str): Nick the user uses in the MUC room
            room (JID): The MUC room to check

        Returns:
            True if local JID part and nick match or if the user is
            allowed to use a different nick than his JID, False
            otherwise.
        """
        if jid.node.lower() == nick.lower():
            return True

        if jid.bare == self.boundjid.bare:
            return True

        with self.db_session() as db:
            whitelist = db.scalars(select(JIDNickWhitelist.jid)).all()
            if jid.bare in whitelist:
                return True

            reason = f"User {jid} connected with a nick different to their JID: {nick}"
            logging.info(reason)

        try:
            await self.plugin["xep_0045"].set_role(room, nick, "none",
                                                   reason="Don't try to impersonate other users")
        except IqError:
            logging.warning("Something failed when trying to kick a user for JID nick mismatch.")

        return False

    def _get_nick_with_proper_case(self, nick: str, room: JID) -> Optional[str]:
        """Get the case-sensitive version of a case-insensitive nick.

        Arguments:
            nick (str): Case-insensitive nick to get the case-sensitive
                        version for
            room (JID): MUC room to look in for the user to get the
                        nick for

        Returns:
            str with the case-sensitive nick of the user if found or
            None otherwise.
        """
        roster = self.plugin["xep_0045"].get_roster(room)
        for roster_nick in roster:
            if roster_nick.lower() == nick.lower():
                return roster_nick
        return None

    async def _unmute_after_mute_ended(self, unmute_dt: datetime, user: JID) -> None:
        """Unmute a user after a given time.

        Arguments:
            unmute_dt (datetime): datetime until user should stay
                                  muted
            user (JID): JID of the user to unmute
        """
        delay = unmute_dt - datetime.now(tz=timezone.utc)
        await asyncio.sleep(delay.total_seconds())

        for room in self.rooms:
            nick = self._get_nick_with_proper_case(user.node, room)
            if not nick:
                continue
            try:
                await self.plugin["xep_0045"].set_role(room, nick, "participant")
            except IqError:
                logging.exception("Automatically unmuting %s in %s failed.", nick, room)

        try:
            del self.unmute_tasks[user]
        except KeyError:
            pass


def parse_args():
    """Parse command line arguments.

    Returns:
         Parsed command line arguments

    """
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter,
                            description="ModBot - XMPP Moderation Bot")

    log_settings = parser.add_mutually_exclusive_group()
    log_settings.add_argument("-q", "--quiet", help="only log errors", action="store_const",
                              dest="log_level", const=logging.ERROR)
    log_settings.add_argument("-d", "--debug", help="log debug messages", action="store_const",
                              dest="log_level", const=logging.DEBUG)
    log_settings.add_argument("-v", "--verbose", help="log more informative messages",
                              action="store_const", dest="log_level", const=logging.INFO)
    log_settings.set_defaults(log_level=logging.WARNING)

    parser.add_argument("-m", "--domain", help="XMPP server to connect to",
                        default="lobby.wildfiregames.com")
    parser.add_argument("-l", "--login", help="username for login", default="modbot")
    parser.add_argument("-p", "--password", help="password for login", default="XXXXXX")
    parser.add_argument("-n", "--nickname", help="nickname to use in MUC rooms", default="ModBot")
    parser.add_argument("-r", "--rooms", help="XMPP MUC rooms to monitor", default="arena",
                        nargs="+")
    parser.add_argument("--command-room", help="XMPP MUC room used by moderators",
                        default="moderation")
    parser.add_argument("--database-url", help="URL for the leaderboard database",
                        default="sqlite:///lobby_moderation.sqlite3")
    parser.add_argument("-s", "--server", help="address of the ejabberd server",
                        action="store", dest="xserver", default=None)
    parser.add_argument("--no-verify",
                        help="Don't verify the TLS server certificate when connecting",
                        action="store_true")

    return parser.parse_args()


def main():
    """Entry point a console script."""
    args = parse_args()

    logging.basicConfig(level=args.log_level,
                        format="%(asctime)s %(levelname)-8s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    xmpp = ModBot(JID("%s@%s/%s" % (args.login, args.domain, "CC")), args.password, args.nickname,
                  [JID(room + "@conference." + args.domain) for room in args.rooms],
                  JID(args.command_room + "@conference." + args.domain), args.database_url,
                  verify_certificate=not args.no_verify)
    xmpp.register_plugin("xep_0045")  # Multi-User Chat
    xmpp.register_plugin("xep_0199", {"keepalive": True})  # XMPP Ping

    if args.xserver:
        xmpp.connect((args.xserver, 5222))
    else:
        xmpp.connect(None)

    asyncio.get_event_loop().run_until_complete(xmpp.shutdown)


if __name__ == "__main__":
    main()
