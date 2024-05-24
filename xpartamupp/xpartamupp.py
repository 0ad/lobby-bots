#!/usr/bin/env python3
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

"""0ad XMPP-bot responsible for managing game listings."""

import asyncio
import logging
import ssl
import time

from argparse import ArgumentDefaultsHelpFormatter
from asyncio import Future
from datetime import datetime, timedelta, timezone

from cachetools import FIFOCache
from slixmpp import ClientXMPP
from slixmpp.jid import JID
from slixmpp.stanza import Iq
from slixmpp.xmlstream.handler import Callback
from slixmpp.xmlstream.matcher import StanzaPath
from slixmpp.xmlstream.stanzabase import register_stanza_plugin

from xpartamupp.stanzas import GameListXmppPlugin
from xpartamupp.utils import ArgumentParserWithConfigFile

# Number of seconds to not respond to mentions after having responded
# to a mention.
INFO_MSG_COOLDOWN_SECONDS = 120

logger = logging.getLogger(__name__)


class Games:
    """Class to tracks all games in the lobby."""

    def __init__(self):
        """Initialize with empty games."""
        self.games = FIFOCache(maxsize=2 ** 7)

    def add_game(self, jid, data):
        """Add a game.

        Arguments:
            jid (JID): JID of the player who started the game
            data (dict): information about the game

        Returns:
            True if adding the game succeeded, False if not

        """
        try:
            data['players-init'] = data['players']
            data['nbp-init'] = data['nbp']
            data['state'] = 'init'
        except (KeyError, TypeError, ValueError):
            logger.warning("Received invalid data for add game from %s: %s", jid, data)
            return False
        else:
            if jid not in self.games:
                logger.info('%s registered a game with the name "%s"', jid, data.get("name"))
            else:
                immutable_keys = ["IP", "name", "hostJID", "hostUsername", "mods"]
                for key, value in data.items():
                    if key in immutable_keys and self.games[jid].get(key) != value:
                        logger.warning(
                            "Game hosted by %s changed immutable property \"%s\": "
                            "\"%s\" -> \"%s\"", jid, key, self.games[jid].get(key), value)

            self.games[jid] = data
            return True

    def remove_game(self, jid):
        """Remove a game attached to a JID.

        Arguments:
            jid (JID): JID of the player whose game to remove.

        Returns:
            True if removing the game succeeded, False if not

        """
        try:
            del self.games[jid]
        except KeyError:
            logger.warning("Game for jid %s didn't exist", jid)
            return False
        else:
            return True

    def get_all_games(self):
        """Return all games.

        Returns:
            dict containing all games with the JID of the player who
            started the game as key.

        """
        return self.games

    def change_game_state(self, jid, data):
        """Switch game state between running and waiting.

        Arguments:
            jid (JID): JID of the player whose game to change
            data (dict): information about the game

        Returns:
            True if changing the game state succeeded, False if not

        """
        if jid not in self.games:
            logger.warning("Tried to change state for non-existent game %s", jid)
            return False

        try:
            if self.games[jid]['nbp-init'] > data['nbp']:
                logger.debug("change game (%s) state from %s to %s", jid,
                             self.games[jid]['state'], 'waiting')
                self.games[jid]['state'] = 'waiting'
            else:
                logger.debug("change game (%s) state from %s to %s", jid,
                             self.games[jid]['state'], 'running')
                self.games[jid]['state'] = 'running'
            self.games[jid]['nbp'] = data['nbp']
            self.games[jid]['players'] = data['players']
        except (KeyError, ValueError):
            logger.warning("Received invalid data for change game state from %s: %s", jid, data)
            return False
        else:
            if 'startTime' not in self.games[jid]:
                self.games[jid]['startTime'] = str(round(time.time()))
            return True


class XpartaMuPP(ClientXMPP):
    """Main class which handles IQ data and sends new data."""

    def __init__(self, sjid, password, room, nick, verify_certificate=True):
        """Initialize XpartaMuPP.

        Arguments:
             sjid (JID): JID to use for authentication
             password (str): password to use for authentication
             room (JID): XMPP MUC room to join
             nick (str): Nick to use in MUC
             verify_certificate (bool): Whether to verify the TLS
                                        certificate provided by the
                                        server

        """
        super().__init__(sjid, password)

        if not verify_certificate:
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

        self.whitespace_keepalive = False

        self.shutdown = Future()
        self._connect_loop_wait_reconnect = 0

        self.room = room
        self.nick = nick

        self.games = Games()

        self.last_info_msg = None

        register_stanza_plugin(Iq, GameListXmppPlugin)

        self.register_handler(Callback('Iq Gamelist', StanzaPath('iq@type=set/gamelist'),
                                       self._iq_game_list_handler))

        self.add_event_handler('session_start', self._session_start)
        self.add_event_handler('muc::%s::got_online' % self.room, self._muc_online)
        self.add_event_handler('muc::%s::got_offline' % self.room, self._muc_offline)
        self.add_event_handler('groupchat_message', self._muc_message)
        self.add_event_handler('failed_all_auth', self._shutdown)
        self.add_event_handler('disconnected', self._reconnect)

    async def _session_start(self, event):  # pylint: disable=unused-argument
        """Join MUC channel and announce presence.

        Arguments:
            event (dict): empty dummy dict

        """
        self._connect_loop_wait_reconnect = 0
        await self.plugin['xep_0045'].join_muc_wait(self.room, self.nick)
        self.send_presence()
        self.get_roster()
        logger.info("XpartaMuPP started")

    async def _shutdown(self, event):  # pylint: disable=unused-argument
        """Shut down XpartaMuPP.

        This is used for aborting connection tries in case the
        configured credentials are wrong, as further connection tries
        won't succeed in this case.

        Arguments:
            event (dict): empty dummy dict

        """
        logger.error("Can't log in. Aborting reconnects.")
        self.abort()
        self.shutdown.set_result(True)

    async def _reconnect(self, event):  # pylint: disable=unused-argument
        """Trigger a reconnection attempt.

        This triggers a reconnection attempt and implements the same
        back-off behavior as the ClientXMPP.connect() method does to
        avoid too frequent reconnection tries.

        Arguments:
            event (dict): empty dummy dict

        """
        if self._connect_loop_wait_reconnect > 0:
            self.event('reconnect_delay', self._connect_loop_wait_reconnect)
            await asyncio.sleep(self._connect_loop_wait_reconnect)

        self._connect_loop_wait_reconnect = self._connect_loop_wait_reconnect * 2 + 1

        self.connect()

    def _muc_online(self, presence):
        """Add joining players to the list of players.

        Also send a list of games to them, so they see which games
        are currently there.

        Arguments:
            presence (slixmpp.stanza.presence.Presence): Received
                presence stanza.

        """
        nick = str(presence['muc']['nick'])
        jid = JID(presence['muc']['jid'])

        if not jid.resource.startswith('0ad'):
            return

        self._send_game_list(jid)

        logger.debug("Client '%s' connected with a nick '%s'.", jid, nick)

    def _muc_offline(self, presence):
        """Remove leaving players from the list of players.

        Also remove the potential game this player was hosting, so we
        don't end up with stale games.

        Arguments:
            presence (slixmpp.stanza.presence.Presence): Received
                presence stanza.

        """
        nick = str(presence['muc']['nick'])
        jid = JID(presence['muc']['jid'])

        if not jid.resource.startswith('0ad'):
            return

        if self.games.remove_game(jid):
            self._send_game_list()

        logger.debug("Client '%s' with nick '%s' disconnected", jid, nick)

    def _muc_message(self, msg):
        """Process messages in the MUC room.

        Respond to messages highlighting the bots name with an
        informative message. After responding once, cool down before
        responding again to avoid spamming info messages when mentioned
        repeatedly.

        Arguments:
            msg (slixmpp.stanza.message.Message): Received MUC
                message
        """
        if msg['mucnick'] == self.nick or self.nick.lower() not in msg['body'].lower():
            return

        if (
            self.last_info_msg and
            self.last_info_msg + timedelta(seconds=INFO_MSG_COOLDOWN_SECONDS) > datetime.now(
                tz=timezone.utc)
        ):
            return

        self.last_info_msg = datetime.now(tz=timezone.utc)
        self.send_message(mto=msg['from'].bare,
                          mbody="I am just a bot and I'm responsible to ensure that you're able "
                                "to see the list of games in here. Aside from that I'm just "
                                "chilling.",
                          mtype='groupchat')

    def _iq_game_list_handler(self, iq):
        """Handle game state change requests.

        Arguments:
            iq (IQ): Received IQ stanza

        """
        if not iq['from'].resource.startswith('0ad'):
            return

        success = False

        command = iq['gamelist']['command']
        if command == 'register':
            success = self.games.add_game(iq['from'], iq['gamelist']['game'])
        elif command == 'unregister':
            success = self.games.remove_game(iq['from'])
        elif command == 'changestate':
            success = self.games.change_game_state(iq['from'], iq['gamelist']['game'])
        else:
            logger.info('Received unknown game command: "%s"', command)

        iq = iq.reply(clear=not success)
        if not success:
            iq['error']['condition'] = "undefined-condition"
        iq.send()

        if success:
            try:
                self._send_game_list()
            except Exception:
                logger.exception('Failed to send game list after "%s" command', command)

    def _send_game_list(self, to=None):
        """Send a massive stanza with the whole game list.

        If no target is passed the gamelist is broadcasted to all
        clients.

        Arguments:
            to (JID): Player to send the game list to.
                If None, the game list will be broadcasted
        """
        games = self.games.get_all_games()

        online_jids = []
        for nick in self.plugin['xep_0045'].get_roster(self.room):
            online_jids.append(JID(self.plugin['xep_0045'].get_jid_property(self.room, nick,
                                                                            'jid')))

        stanza = GameListXmppPlugin()
        for jid in games:
            if jid in online_jids:
                stanza.add_game(games[jid])

        if not to:
            for jid in online_jids:
                if not jid.resource.startswith('0ad'):
                    continue

                iq = self.make_iq_result(ito=jid)
                iq.set_payload(stanza)
                try:
                    iq.send()
                except Exception:
                    logger.exception("Failed to send game list to %s", jid)
        else:
            iq = self.make_iq_result(ito=to)
            iq.set_payload(stanza)
            try:
                iq.send()
            except Exception:
                logger.exception("Failed to send game list to %s", to)


def parse_args():
    """Parse command line arguments.

    Returns:
         Parsed command line arguments

    """
    parser = ArgumentParserWithConfigFile(formatter_class=ArgumentDefaultsHelpFormatter,
                                          description="XpartaMuPP - XMPP Multiplayer Game Manager")

    verbosity_parser = parser.add_mutually_exclusive_group()
    verbosity_parser.add_argument("-v", action="count", dest="verbosity", default=0,
                                  help="Increase verbosity of logging. Can be provided up to "
                                       "three times to get full debug logging")
    verbosity_parser.add_argument("--verbosity", type=int,
                                  help="Increase verbosity of logging. Supported values are 0 to 3"
                                  )

    parser.add_argument('-m', '--domain', help="XMPP server to connect to",
                        default='lobby.wildfiregames.com')
    parser.add_argument('-l', '--login', help="username for login", default='xpartamupp')
    parser.add_argument('-p', '--password', help="password for login", default='XXXXXX')
    parser.add_argument('-n', '--nickname', help="nickname shown to players", default='WFGBot')
    parser.add_argument('-r', '--room', help="XMPP MUC room to join", default='arena')
    parser.add_argument('-s', '--server', help='address of the ejabberd server',
                        action='store', dest='xserver', default=None)
    parser.add_argument('--no-verify',
                        help="Don't verify the TLS server certificate when connecting",
                        action='store_true')

    return parser.parse_args()


def main():
    """Entry point a console script."""
    args = parse_args()

    log_level = logging.WARNING
    if args.verbosity == 1:
        log_level = logging.INFO
    elif args.verbosity == 2:
        log_level = logging.DEBUG
    elif args.verbosity >= 3:
        log_level = logging.DEBUG
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)

    logging.basicConfig(format='%(asctime)s %(levelname)-8s %(message)s',
                        datefmt='%Y-%m-%dT%H:%M:%S%z')
    logger.setLevel(log_level)

    xmpp = XpartaMuPP(JID('%s@%s/%s' % (args.login, args.domain, 'CC')), args.password,
                      JID(args.room + '@conference.' + args.domain), args.nickname,
                      verify_certificate=not args.no_verify)
    xmpp.register_plugin('xep_0030')  # Service Discovery
    xmpp.register_plugin('xep_0004')  # Data Forms
    xmpp.register_plugin('xep_0045')  # Multi-User Chat
    xmpp.register_plugin('xep_0060')  # Publish-Subscribe
    xmpp.register_plugin('xep_0199', {'keepalive': True})  # XMPP Ping

    if args.xserver:
        xmpp.connect((args.xserver, 5222))
    else:
        xmpp.connect(None)

    asyncio.get_event_loop().run_until_complete(xmpp.shutdown)


if __name__ == '__main__':
    main()
