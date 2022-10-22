#!/usr/bin/env python3

# Copyright (C) 2022 Wildfire Games.
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

"""Service providing a chatroom language monitor for MUC rooms"""

import argparse
import asyncio
import difflib
import logging
import re
import slixmpp
import sys

from chat_monitor.models import Blacklist, Whitelist, ProfanityIncident
from code import interact
from collections import deque
from datetime import datetime, timedelta
from functools import partial
from moderation.data.database import db_session
from moderation.stanzas import ModerationXmppPlugin, ModerationCommand
from pprint import pprint, pformat
from ptpython.repl import embed
from slixmpp.stanza import Iq
from slixmpp.xmlstream import ET
from slixmpp.xmlstream.handler import Callback
from slixmpp.xmlstream.matcher import StanzaPath
from slixmpp.xmlstream.stanzabase import register_stanza_plugin
from sqlalchemy import func, or_, not_, select
from sqlalchemy.sql import operators
from traceback import format_exc

class ChatMonitor(slixmpp.ClientXMPP):
    """Main class which monitors chats, issues warnings and mutes if necessary."""

    def __init__(self, sjid, password, rooms, nick, domain):
        """Initialize the chat monitor."""
        slixmpp.ClientXMPP.__init__(self, slixmpp.jid.JID(sjid), password)
        self.whitespace_keepalive = False

        self.sjid = slixmpp.jid.JID(sjid)
        self.rooms = [slixmpp.jid.JID(room + '@conference.' + domain) for room in rooms]
        self.nick = nick
        self.background_tasks=[]

        register_stanza_plugin(Iq, ModerationXmppPlugin)
        register_stanza_plugin(ModerationXmppPlugin, ModerationCommand)

        self.add_event_handler('session_start', self._got_session_start)
        for room in rooms:
            self.add_event_handler('muc::%s::got_online' % room, self._got_muc_online)
        self.add_event_handler('groupchat_message', self._got_muc_message)

    async def _got_session_start(self, event):  # pylint: disable=unused-argument
        """Join MUC channel and announce presence.

        Arguments:
            event (dict): empty dummy dict

        """
        for room in self.rooms: await self.plugin['xep_0045'].join_muc_wait(room, self.nick)
        self.send_presence()
        self.get_roster()
        logging.info("ChatMonitor started")

    def _got_muc_presence(self, presence):
        """Called for every MUC presence event
        (Currently Unused)

        Arguments:
            presence (slixmpp.stanza.presence.Presence): Received
                presence stanza.
        """
        nick = str(presence['muc']['nick'])
        jid = slixmpp.jid.JID(presence['muc']['jid'])
        
        logging.debug("Client '%s' connected with a nick of '%s'.", jid, nick)

    def _got_muc_online(self, presence):
        """Called when the first resource for a user has connected to a MUC
        (Currently Unused)

        Arguments:
            presence (slixmpp.stanza.presence.Presence): Received
                presence stanza.
        """
        nick = str(presence['muc']['nick'])
        jid = slixmpp.jid.JID(presence['muc']['jid'])

    def _got_muc_offline(self, presence):
        """Called when all resources of a user have disconnected from a muc
        (Currently Unused)

        Arguments:
            presence (slixmpp.stanza.presence.Presence): Received
                presence stanza.

        """
        nick = str(presence['muc']['nick'])
        jid = slixmpp.jid.JID(presence['muc']['jid'])

        logging.debug("Client '%s' with nick '%s' disconnected", jid, nick)

    def _got_muc_message(self, msg):
        """Process messages in the MUC rooms.

        Arguments:
            msg (slixmpp.stanza.message.Message): Received MUC
                message
        """
        if 'stamp' in msg['delay'].xml.attrib: return   # Don't process this message if it is a historical message.
        with db_session() as db:
            logging.debug("Received chatroom message")
            nick = msg['muc']['nick']
            room = msg['muc']['room']
            jid = self._get_jid(nick.lower(), room=room)

            if nick == self.nick:
                return
            lowercase_message = msg['body'].lower()

            with db.begin():
                whitelist = db.scalars(select(Whitelist.word)).all()
                blacklist = db.scalars(select(Blacklist.word)).all()

            # Filter out any words on the whitelist.
            filtered_message = lowercase_message
            if whitelist:
                filtered_message = re.sub("|".join(whitelist), "", lowercase_message)

            # If there's a word from the blacklist then add a ProfanityIncident to the database.
            if blacklist and re.search("|".join(blacklist), filtered_message):
                logging.info("(%s Profanity incident) %s: %s", msg['room'],msg['muc']['nick'], msg['body'])
                incident = ProfanityIncident(timestamp=datetime.now(), player=jid.bare, offending_content=lowercase_message)
                db.add(incident)
                db.commit()

                # If there are more than 2 warnings then mute the player.
                number_of_incidents = db.scalar(select(func.count(ProfanityIncident.id)).filter(ProfanityIncident.player==jid.bare, operators.isnot(ProfanityIncident.deleted,True)))
                if number_of_incidents > 2:
                    logging.info("Player has more than 2 incidents. Muting player.")

                    # Mute duration starts at 15 minutes and doubles with each additional mute.
                    duration = timedelta(minutes=15 * 2 ** max(0, db.query(ProfanityIncident).filter(ProfanityIncident.player==jid.bare, operators.isnot(ProfanityIncident.deleted,True)).count()-3))
                    logging.info("Mute duration: " + str(duration))

                    iq = self.make_iq_set(ito="user1@lobby.wildfiregames.com/moderation")
                    iq.enable('moderation')
                    iq['moderation']['moderation_command']['command_name'] = "mute"
                    iq['moderation']['moderation_command']['params'] = {"jid": jid.bare,
                                                                        "duration": str(duration), "reason": "Profanity",
                                                                        "moderator": "userbot@lobby.wildfiregames.com"}
                    try:
                        iq.send()
                    except: logging.exception(traceback.format_exc())
                    
                else: 
                    logging.info("Kicking player from the room with a warning.")
                    to = slixmpp.jid.JID(self.sjid)
                    to.resource="moderation"
                    iq = self.make_iq_set()
                    iq['to']=to
                    iq.enable('moderation')
                    iq['moderation']['moderation_command']['command_name'] = "kick"
                    iq['moderation']['moderation_command']['params'] = {"jid": jid.bare, "reason": "Don't use profanity in the main lobby.",
                                                                        "moderator": "userbot@lobby.wildfiregames.com"}
                    try:
                        iq.send()
                    except: logging.exception(format_exc())

    def _get_jid(self, nick, room=None):
        """Return JID for the nick in a MUC room or all rooms.
            
        Arguments:
            room (slixmpp.jid.JID): (optional) MUC room
            
        """ 
        rooms = [ room ] if room else self.rooms
        for room in rooms:
            roster = self.plugin['xep_0045'].get_roster(room)
            if nick in roster: return slixmpp.jid.JID(self.plugin['xep_0045'].get_jid_property(room, nick, "jid"))
        return False
        
    def _get_roster_jids(self, room):
        """Return roster for the MUC room as a dict of JIDs keyed by
        nickname
        
        Arguments:
            room (slixmpp.jid.JID): MUC room
            
        """ 
        roster = self.plugin['xep_0045'].get_roster(room)
        result = {}
        for nick in roster:
            result[nick]=slixmpp.jid.JID(self.plugin['xep_0045'].get_jid_property(room, nick, "jid"))
        return result
 

def parse_args(args):
    """Parse command line arguments.

    Arguments:
        args (dict): Raw command line arguments given to the script

    Returns:
         Parsed command line arguments

    """
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter,
                                     description="XMPP interface for the lobby moderation service")

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
    parser.add_argument('-l', '--login', help="username for login", default='moderation')
    parser.add_argument('-p', '--password', help="password for login", default='password')
    parser.add_argument('-n', '--nickname', help="nickname shown to players", default='ModerationBot')
    parser.add_argument('-r', '--rooms', help="MUC rooms to join", nargs="+", default=['arena27'])
    parser.add_argument('--database-url', help="URL for the moderation database",
                        default='sqlite:///moderation.sqlite3')
    parser.add_argument('-s', '--server', help='address of the XMPP server',
                        action='store', dest='xserver', default=None)
    parser.add_argument('-t', '--disable-tls',
                        help='Pass this argument to connect without TLS encryption',
                        action='store_true', dest='xdisabletls', default=False)

    return parser.parse_args(args)


async def async_main():
    """Entry point a console script."""
    args = parse_args(sys.argv[1:])

    logging.basicConfig(level=args.log_level,
                        format='%(asctime)s %(levelname)-8s %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')

    xmpp = ChatMonitor('%s@%s/%s' % (args.login, args.domain, 'chat_monitor'), args.password,
                   args.rooms, args.nickname, args.domain)
    xmpp.register_plugin('xep_0030')  # Service Discovery
    xmpp.register_plugin('xep_0004')  # Data Forms
    xmpp.register_plugin('xep_0045')  # Multi-User Chat
    xmpp.register_plugin('xep_0060')  # Publish-Subscribe
    xmpp.register_plugin('xep_0199', {'keepalive': True})  # XMPP Ping

    xmpp.connect((args.xserver, 5222) if args.xserver else None, False, not args.xdisabletls)
    
    # Start a debug console
    console = asyncio.get_event_loop().create_task(partial(embed,globals=globals(), locals=locals(), return_asyncio_coroutine=True, patch_stdout=True)())
    try: await console
    except: logging.exception(format_exc())

    await xmpp.disconnect()

def main():
    asyncio.run(async_main())
    
if __name__ == '__main__':
    main()
