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

import argparse
import asyncio
import logging
import sys
import time

from asyncio import Future

from slixmpp import ClientXMPP
from slixmpp.exceptions import IqError
from slixmpp.jid import JID
from slixmpp.plugins.xep_0004 import Form
from slixmpp.stanza import Iq
from slixmpp.xmlstream.handler import Callback
from slixmpp.xmlstream.matcher import StanzaPath
from slixmpp.xmlstream.stanzabase import register_stanza_plugin

from xpartamupp.stanzas import GameListXmppPlugin
from xpartamupp.utils import LimitedSizeDict


class Games:
    """Class to tracks all games in the lobby."""

    def __init__(self):
        """Initialize with empty games."""
        self.games = LimitedSizeDict(size_limit=2 ** 7)

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
            logging.warning("Received invalid data for add game from 0ad: %s", data)
            return False
        else:
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
            logging.warning("Game for jid %s didn't exist", jid)
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
            logging.warning("Tried to change state for non-existent game %s", jid)
            return False

        try:
            if self.games[jid]['nbp-init'] > data['nbp']:
                logging.debug("change game (%s) state from %s to %s", jid,
                              self.games[jid]['state'], 'waiting')
                self.games[jid]['state'] = 'waiting'
            else:
                logging.debug("change game (%s) state from %s to %s", jid,
                              self.games[jid]['state'], 'running')
                self.games[jid]['state'] = 'running'
            self.games[jid]['nbp'] = data['nbp']
            self.games[jid]['players'] = data['players']
        except (KeyError, ValueError):
            logging.warning("Received invalid data for change game state from 0ad: %s", data)
            return False
        else:
            if 'startTime' not in self.games[jid]:
                self.games[jid]['startTime'] = str(round(time.time()))
            return True


class XpartaMuPP(ClientXMPP):
    """Main class which handles IQ data and sends new data."""

    def __init__(self, sjid, password, room, nick, disable_legacy_lists):
        """Initialize XpartaMuPP.

        Arguments:
             sjid (JID): JID to use for authentication
             password (str): password to use for authentication
             room (JID): XMPP MUC room to join
             nick (str): Nick to use in MUC
             disable_legacy_lists (bool): Whether to use the old way to
                                          send game lists to players in
                                          addition to using PubSub

        """
        super().__init__(sjid, password)
        self.whitespace_keepalive = False

        self.shutdown = Future()
        self._connect_loop_wait_reconnect = 0

        self.room = room
        self.nick = nick

        self.pubsub_jid = JID("pubsub." + self.server)
        self.pubsub_gamelist_node = f"0ad#{self.room.local}#gamelist#v1"
        self.legacy_lists_disabled = disable_legacy_lists

        self.games = Games()

        register_stanza_plugin(Iq, GameListXmppPlugin)

        self.register_handler(Callback('Iq Gamelist', StanzaPath('iq@type=set/gamelist'),
                                       self._iq_game_list_handler))

        self.add_event_handler('session_start', self._session_start)
        self.add_event_handler('disco_items', self._pubsub_node_disco)
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

        await self.plugin['xep_0060'].get_nodes(jid=self.pubsub_jid)
        await self.plugin['xep_0045'].join_muc_wait(self.room, self.nick)
        self.send_presence()
        self.get_roster()
        logging.info("XpartaMuPP started")

    async def _shutdown(self, event):  # pylint: disable=unused-argument
        """Shut down XpartaMuPP.

        This is used for aborting connection tries in case the
        configured credentials are wrong, as further connection tries
        won't succeed in this case.

        Arguments:
            event (dict): empty dummy dict

        """
        logging.error("Can't log in. Aborting reconnects.")
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

        # disable_starttls is set here only as a workaround for a bug
        # in Slixmpp and can be removed once that's fixed. See
        # https://lab.louiz.org/poezio/slixmpp/-/merge_requests/226
        # for details.
        self.connect(disable_starttls=None)

    async def _create_pubsub_node(self, node_name, node_config):
        """Create a new PubSub node.

        This creates a new PubSub node with the given configuration and
        checks whether the node got the expected node name assigned.

        Arguments:
            node_name (str): Desired name of the PubSub node
            node_config (Form): form with options to send when
                                creating the node
        """
        try:
            result = await self.plugin['xep_0060'].create_node(jid=self.pubsub_jid,
                                                               node=node_name,
                                                               config=node_config)
        except IqError as exc:
            logging.error("Creating the PubSub node failed: %s", exc.text)
        else:
            if result["pubsub"]["create"]["node"] != node_name:
                logging.error('Created PubSub node got a different node name ("%s") than '
                              'expected ("%s")', result["pubsub"]["create"]["node"], node_name)

    async def _check_pubsub_node_config(self, node_name, node_config):
        """Check the configuration of a PubSub node.

        This checks if the configuration of an existing PubSub node is
        as expected.

        Arguments:
            node_name (str): Name of the PubSub node to check
            node_config (Form): form with options to check the node
                                configuration against
        """
        current_node_config = await self.plugin['xep_0060'].get_node_config(
            jid=self.pubsub_jid, node=node_name)
        current_node_config_form: Form = current_node_config["pubsub_owner"]["configure"]["form"]

        differences = {}
        current_node_config_dict = current_node_config_form.get_values()
        for key, new_value in node_config.get_values().items():
            if current_node_config_dict.get(key) != new_value:
                differences[key] = (new_value, current_node_config_dict.get(key))

        if differences:
            logging.warning("Existing PubSub node config differs from expected config! This "
                            "will likely cause the lobby not to behave as expected!")
            for key, value in differences.items():
                logging.warning('Current value ("%s") for option "%s" is different than the '
                                'expected one ("%s")', value[1], key, value[0])

    async def _pubsub_node_disco(self, event):
        """Handle discovery and creation of PubSub nodes.

        This handles disco responses from the PubSub service to
        discover the necessary PubSub node for publishing game list
        information. If the node doesn't exist, it'll be created with
        the proper configuration. Creation only needs to happen once
        per node name and can be done manually as well.

        Arguments:
            event (IQ): Disco response event
        """
        if event["from"] != self.pubsub_jid or not event.get("disco_items"):
            return

        nodes = event["disco_items"]["items"]
        node_names = [node[1] for node in nodes]

        default_node_config = await self.plugin['xep_0060'].get_node_config(jid=self.pubsub_jid)
        new_node_config_form: Form = default_node_config["pubsub_owner"]["default"]["form"]
        new_node_config_form.reply()

        answers = {
            "pubsub#access_model": "open",
            "pubsub#deliver_notifications": True,
            "pubsub#deliver_payloads": True,
            "pubsub#itemreply": "none",
            "pubsub#max_payload_size": "250000",  # current maximum for ejabberd
            "pubsub#notification_type": "normal",
            "pubsub#notify_config": False,
            "pubsub#notify_delete": False,
            "pubsub#notify_retract": False,
            "pubsub#persist_items": False,
            "pubsub#presence_based_delivery": True,
            "pubsub#publish_model": "publishers",
            "pubsub#purge_offline": False,
            "pubsub#send_last_published_item": "on_sub_and_presence",
            "pubsub#subscribe": True,
        }
        for field, answer in answers.items():
            new_node_config_form.field[field].set_answer(answer)

        if self.pubsub_gamelist_node not in node_names:
            await self._create_pubsub_node(self.pubsub_gamelist_node, new_node_config_form)
        else:
            await self._check_pubsub_node_config(self.pubsub_gamelist_node, new_node_config_form)

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

        self._publish_game_list()
        if not self.legacy_lists_disabled:
            self._send_game_list(jid)

        logging.debug("Client '%s' connected with a nick '%s'.", jid, nick)

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
            self._publish_game_list()
            if not self.legacy_lists_disabled:
                self._send_game_list()

        logging.debug("Client '%s' with nick '%s' disconnected", jid, nick)

    def _muc_message(self, msg):
        """Process messages in the MUC room.

        Respond to messages highlighting the bots name with an
        informative message.

        Arguments:
            msg (slixmpp.stanza.message.Message): Received MUC
                message
        """
        if msg['mucnick'] != self.nick and self.nick.lower() in msg['body'].lower():
            self.send_message(mto=msg['from'].bare,
                              mbody="I am just a bot and I'm responsible to ensure that your're"
                                    "able to see the list of games in here. Aside from that I'm"
                                    "just chilling.",
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
            logging.info('Received unknown game command: "%s"', command)

        iq = iq.reply(clear=not success)
        if not success:
            iq['error']['condition'] = "undefined-condition"
        iq.send()

        if success:
            try:
                self._publish_game_list()
                if not self.legacy_lists_disabled:
                    self._send_game_list()
            except Exception:
                logging.exception('Failed to send game list after "%s" command', command)

    def _publish_game_list(self):
        """Publish the game list.

        This publishes the game list as an item to the configured
        PubSub node.
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

        self.plugin['xep_0060'].publish(jid=self.pubsub_jid, node=self.pubsub_gamelist_node,
                                        payload=stanza)

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
                    logging.exception("Failed to send game list to %s", jid)
        else:
            iq = self.make_iq_result(ito=to)
            iq.set_payload(stanza)
            try:
                iq.send()
            except Exception:
                logging.exception("Failed to send game list to %s", to)


def parse_args(args):
    """Parse command line arguments.

    Arguments:
        args (dict): Raw command line arguments given to the script

    Returns:
         Parsed command line arguments

    """
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter,
                                     description="XpartaMuPP - XMPP Multiplayer Game Manager")

    log_settings = parser.add_mutually_exclusive_group()
    log_settings.add_argument('-q', '--quiet', help="only log errors", action='store_const',
                              dest='log_level', const=logging.ERROR)
    log_settings.add_argument('-d', '--debug', help="log debug messages", action='store_const',
                              dest='log_level', const=logging.DEBUG)
    log_settings.add_argument('-v', '--verbose', help="log more informative messages",
                              action='store_const', dest='log_level', const=logging.INFO)
    log_settings.set_defaults(log_level=logging.WARNING)

    parser.add_argument('-m', '--domain', help="XMPP server to connect to",
                        default='lobby.wildfiregames.com')
    parser.add_argument('-l', '--login', help="username for login", default='xpartamupp')
    parser.add_argument('-p', '--password', help="password for login", default='XXXXXX')
    parser.add_argument('-n', '--nickname', help="nickname shown to players", default='WFGBot')
    parser.add_argument('-r', '--room', help="XMPP MUC room to join", default='arena')
    parser.add_argument('-s', '--server', help='address of the ejabberd server',
                        action='store', dest='xserver', default=None)
    parser.add_argument('-t', '--disable-tls',
                        help='Pass this argument to connect without TLS encryption',
                        action='store_true', dest='xdisabletls', default=False)
    parser.add_argument('--disable-legacy-lists',
                        help='Disable the deprecated pre-PubSub way of sending lists to players.',
                        action='store_true')

    return parser.parse_args(args)


def main():
    """Entry point a console script."""
    args = parse_args(sys.argv[1:])

    logging.basicConfig(level=args.log_level,
                        format='%(asctime)s %(levelname)-8s %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')

    xmpp = XpartaMuPP(JID('%s@%s/%s' % (args.login, args.domain, 'CC')), args.password,
                      JID(args.room + '@conference.' + args.domain), args.nickname,
                      disable_legacy_lists=args.disable_legacy_lists)
    xmpp.register_plugin('xep_0030')  # Service Discovery
    xmpp.register_plugin('xep_0004')  # Data Forms
    xmpp.register_plugin('xep_0045')  # Multi-User Chat
    xmpp.register_plugin('xep_0060')  # Publish-Subscribe
    xmpp.register_plugin('xep_0199', {'keepalive': True})  # XMPP Ping

    if args.xserver:
        xmpp.connect((args.xserver, 5222), disable_starttls=args.xdisabletls)
    else:
        xmpp.connect(None, disable_starttls=args.xdisabletls)

    asyncio.get_event_loop().run_until_complete(xmpp.shutdown)


if __name__ == '__main__':
    main()
