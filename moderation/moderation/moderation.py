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

""" The Moderation service manages moderation tasks in the MUC rooms
    for moderators, admins, lobby helpers, etc.

    Enables making reports which can come from moderators/lobby helpers
    or other users including normal users.

    Handles timed mutes and bans.
    
    Handles warnings and kicks and enables keeping track of previous
    warnings issued to users.
    
"""

import argparse
import asyncio
import difflib
import logging
import slixmpp
import sys

from aioscheduler import TimedScheduler         
from chat_monitor.models import Blacklist, Whitelist, ProfanityIncident
from copy import deepcopy
from collections import deque
from datetime import datetime, timedelta
from functools import partial
from moderation.data.database import db_session, row2dict
from moderation.data.models import Mute, Moderator
from moderation.stanzas import ModerationXmppPlugin, ModerationCommand
from pprint import pprint, pformat
from ptpython.repl import embed
from pytimeparse import parse as parse_time
from slixmpp.stanza import Iq
from slixmpp.xmlstream import ET
from slixmpp.xmlstream.handler import Callback
from slixmpp.xmlstream.matcher import StanzaPath
from slixmpp.xmlstream.stanzabase import register_stanza_plugin
from sqlalchemy import select
from traceback import format_exc

class Moderation(slixmpp.ClientXMPP):
    """An XMPP client that handles IQs and performs/processes commands.
    """

    def __init__(self, sjid, password, rooms, nick, domain):
        """Initialize and register handlers."""

        slixmpp.ClientXMPP.__init__(self, slixmpp.jid.JID(sjid), password)
        self.whitespace_keepalive = False

        self.sjid = slixmpp.jid.JID(sjid)
        self.rooms = [slixmpp.jid.JID(room + '@conference.' + domain) for room in rooms]
        self.nick = nick

        self.scheduler = TimedScheduler(prefer_utc=False)
        asyncio.ensure_future(self.start_scheduler())

        register_stanza_plugin(Iq, ModerationXmppPlugin)
        register_stanza_plugin(ModerationXmppPlugin, ModerationCommand)

        self.register_handler(Callback('Iq Moderation Command', StanzaPath('iq/moderation/moderation_command'),
                                       self._iq_moderation_command_handler))

        self.add_event_handler('session_start', self._got_session_start)
        for room in self.rooms:
            self.add_event_handler('muc::%s::got_online' % room, self._got_muc_online)
        self.add_event_handler('groupchat_message', self._got_muc_message)

        # Initialize mutes and bans
        self.muted = set()
        with db_session() as db:
            mutes = db.execute(select(Mute).filter_by(active=True, deleted=None)).scalars().all()
            for mute in mutes:
                if mute.end and datetime.now()>=mute.end:
                    logging.info("Deactivating expired mute for %s", mute.player)
                    mute.active=False
                    db.commit()
                else:
                    logging.info("Active mute for %s ends at %s", mute.player, mute.end or "(No end)")
                    self.muted.add(mute.player)
                    if type(mute.end) is datetime: self.scheduler.schedule(self._scheduled_mute_ends(mute.player, mute.id), mute.end)
            
        self.banned = set()     #TODO: UNIMPLEMENTED
        
    async def start_scheduler(self):
        self.scheduler.start()

    async def _got_session_start(self, event):  # pylint: disable=unused-argument
        """Join MUC channel and announce presence.

        Arguments:
            event (dict): empty dummy dict

        """

        for room in self.rooms: await self.plugin['xep_0045'].join_muc_wait(room, self.nick)
        self.send_presence()
        self.get_roster()

        logging.info("Moderation started")
        
    def _got_muc_presence(self, presence):
        """Called for every MUC presence event
        (Currently Unused)

        Arguments:
            presence (slixmpp.stanza.presence.Presence): Received
                presence stanza.

        """
        nick = str(presence['muc']['nick'])
        jid = slixmpp.jid.JID(presence['muc']['jid'])

    def _got_muc_online(self, presence):
        """Called when the first resource for a user has connected to a MUC

        Arguments:
            presence (slixmpp.stanza.presence.Presence): Received
                presence stanza.

        """
        nick = str(presence['muc']['nick'])
        jid = slixmpp.jid.JID(presence['muc']['jid'])

        if jid.bare in self.muted:
            asyncio.ensure_future(self._muc_mute(nick, room=presence['muc']['room']))            
        
        logging.debug("Client '%s' connected with a nick of '%s'.", jid, nick)

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
        """Process messages in the MUC room.

        Arguments:
            msg (slixmpp.stanza.message.Message): Received MUC
                message
        """
        if self.nick.lower() in msg['body'].lower():
            ...

    async def _muc_mute(self, nick, room=None, reason=''):
        """Perform mute on a nick in a MUC room or all rooms
        """

        logging.info("Muting MUC nick: %s", nick)
        rooms = [ room ] if room else self.rooms
        for room in rooms:
            try: await self.plugin['xep_0045'].set_role(room, nick, 'visitor', reason=reason)
            except: ... # Nick is not in the MUC room

    async def _muc_unmute(self, nick, room=None, reason=''):
        """Unmute nick in a MUC room or all MUC rooms
        """

        logging.info("Unmuting MUC nick: %s", nick)
        rooms = [ room ] if room else self.rooms
        for room in rooms:
            try: await self.plugin['xep_0045'].set_role(room, nick, 'participant', reason=reason)
            except: ... # Nick is not in the MUC room

    async def _muc_kick(self, nick, room=None, reason=''):
        """Perform kick on a nick in a MUC room or all rooms

            Arguments:
                room (str) :     (Optional) Specify MUC room.
                reason (str) :   (Optional) Specify reason to display publicly.
        """ 
        logging.info("Kicking MUC nick: %s", nick)
        rooms = [ room ] if room else self.rooms
        for room in rooms:
            try: await self.plugin['xep_0045'].set_role(room, nick, 'none', reason=reason)
            except: ... # Nick is not in the MUC room

    async def _muc_ban(self, jid, room=None, reason=''):
        """Perform ban on a JID in a MUC room or all rooms
            UNIMPLEMENTED
        """
        raise NotImplemented

    async def _muc_unban(self, jid, room=None, reason=''):
        """Unban a JID in a MUC room or all rooms
            UNIMPLEMENTED
        """
        raise NotImplemented

    def _iq_moderation_command_handler(self, iq):
        """Handle incoming moderation commands.
        
        Arguments:
            iq (slixmpp.stanza.iq.IQ): Received IQ stanza
        
        """
        if iq["from"].bare != self.sjid.bare: 
            logging.warning("Ignoring moderation command IQ from unexpected source")
            return
        else:
            logging.info("Received moderation command IQ from %s", iq['from'].bare)

        logging.debug(iq)
        
        if iq["type"]=="set":
            command = iq['moderation']['moderation_command']['command_name']
            params = iq['moderation']['moderation_command']['params']
            if 'moderator' in params:
                moderator = params['moderator']
            else:
                moderator = "userbot@lobby.wildfiregames.com"

            params['moderator'] = moderator
            reply=iq.reply(clear=False)
            try:
                if command == 'mutelist':
                    results = self.command_mutelist(**params)
                    reply['type']="result"
                    for result in results:
                        reply['moderation']['moderation_command'].add_result(result)

                if command == 'mute':
                    reply['type']="result"
                    result = self.command_mute(**params)
                    reply['moderation']['moderation_command'].add_result({"success": result})

                if command == 'unmute':
                    reply['type']="result"
                    result = self.command_unmute(**params)
                    reply['moderation']['moderation_command'].add_result({"success": result})

                if command == 'kick':
                    reply['type']="result"
                    result = self.command_kick(**params)
                    reply['moderation']['moderation_command'].add_result({"success": result})

                if command == 'warn':
#                    self.command_warn(**params)        #TODO: UNIMPLEMENTED
                    raise NotImplemented

                if command == 'banlist':
#                    self.command_banlist(**params)     #TODO: UNIMPLEMENTED
                    raise NotImplemented
                if command == 'ban':
#                    self.command_ban(**params)         #TODO: UNIMPLEMENTED
                    raise NotImplemented

                if command == 'unban':
#                    self.command_unban(**params)       #TODO: UNIMPLEMENTED
                    raise NotImplemented
            except Exception:
                logging.exception("Failed to process %s command request from %s" %
                                  (command, iq['from'].bare))
            try: reply.send()
            except:
                logging.exception("aw fevbdrasgabega" + format_exc())
                return False

    def _get_jid(self, nick, room=None):
        """Return JID for the nick in a MUC room or all rooms.
            
        Arguments:
            room (slixmpp.jid.JID): (optional) MUC room
            
        """ 
        rooms = [ room ] if room else self.rooms
        for room in rooms:
            roster=self.plugin['xep_0045'].get_roster(room)
            if nick in roster: return self.plugin['xep_0045'].get_jid_property(room, nick, "jid")
        return False
        
    def _get_roster_jids(self, room):
        """Return roster for the MUC room as a dict of jids keyed by
        nickname
        
        Arguments:
            room (slixmpp.jid.JID): MUC room
            
        """ 
        result={}
        roster=self.plugin['xep_0045'].get_roster(room)
        for nick in roster:
            result[nick]=slixmpp.jid.JID(self.plugin['xep_0045'].get_jid_property(room, nick, "jid"))
        return result
        
    def command_mute(self, jid=None, nick=None, duration=None, incident_id=None, reason='', end=None, **kwargs):
        """Add a mute to the database and mute the user in the MUC rooms.
        Specify either jid or nick.

        Arguments:
            jid (str):          JID of player to mute.
            nick (str):         MUC nickname of player to mute.
            duration (str):     Duration specified in natural language.
            incident_id (int):  Specify if there's an incident ID for this
                                mute in the database.
                               
        """        
        logging.info("Command: mute")

        with db_session() as db, db.begin():
            # Make sure the moderator exists.
            if not db.get(Moderator, kwargs['moderator']):
                logging.info("%s is not a moderator.", kwargs['moderator'])
                return False

            # Find JID by nickname
            if not jid:
                for room in self.rooms:
                    for nickname,njid in self._get_roster_jids(room).items():
                        if nickname==nick:
                            jid=njid
                            break

            if not jid:
                logging.warn("Unable to mute user. Couldn't resolve a JID")
                return False
            
            logging.info("Muting user with JID: %s", jid)

            # Set end attribute based on duration
            if 'end' in kwargs: end = kwargs['end']
            else: end = None
            if duration:
                seconds = parse_time(duration)
                if seconds: end = datetime.now() + timedelta(seconds=seconds)
                else: end = None

            mute = Mute(player=slixmpp.jid.JID(jid).bare, moderator=kwargs['moderator'],
                        start=datetime.now(), end=end,incident_id=incident_id)
            db.add(mute)
                
            if type(end) is datetime: self.scheduler.schedule(self._scheduled_mute_ends(mute.player, mute.id), mute.end)

            self.muted.add(mute.player)
            asyncio.ensure_future(self._muc_mute(nick or slixmpp.jid.JID(jid).user, reason=reason))
            return True

    def command_unmute(self, jid=None, nick=None, duration=None, mute_id=None, reason='', **kwargs):
        """Deactivate a mute in the database and unmute the user in the MUC rooms.
        Specify either JID or nick.

        Arguments:
            jid (str):          JID of player to unmute.
            nick (str):         MUC nickname of player to mute.
            mute_id (int):      (Optional) Specify if there's a mute ID for this
                                mute in the database.
            reason (str):       (Optional) Specify reason.
                               
        """        
        logging.info("Command: unmute")
        with db_session() as db, db.begin():
            # Make sure the moderator exists.
            if not db.get(Moderator, kwargs['moderator']):
                logging.info("%s is not a moderator.", kwargs['moderator'])
                return False

            # Find JID by nickname
            if not jid:
                for room in self.rooms:
                    for nickname,njid in self._get_roster_jids(room).items():
                        if nickname==nick:
                            jid=njid
                            break

            if not jid:
                logging.warn("Unable to unmute user. Couldn't resolve a JID")
                return False
            
            logging.info("Unmuting user with JID: %s", jid)

            success=False
            mutes = db.execute(select(Mute).filter_by(active=True, player=slixmpp.jid.JID(jid).bare, deleted=None)).scalars().all()
            for mute in mutes:
                mute.active=False
                mute.end=datetime.now()
                success=True
            
            asyncio.ensure_future(self._muc_unmute(nick or slixmpp.jid.JID(jid).user, reason=reason))
            return success

    def command_mutelist(self, **kwargs):
        """Retrieve the mutelist.

        Arguments: None

        Returns: list

        """        
        logging.info("Command: mutelist")
        result = []
        with db_session() as db, db.begin():
            # Make sure the moderator exists.
            if not db.get(Moderator, kwargs['moderator']):
                logging.info("%s is not a moderator.", kwargs['moderator'])
                return []

            for mute in db.execute(select(Mute).filter_by(active=True, deleted=None).group_by(Mute.player)).scalars().all():
                result.append(row2dict(mute))
            return result

    def command_kick(self, jid=None, nick=None, incident_id=None, reason=None, **kwargs):
        """ Kick a player.
            Specify either JID or nick.

            Arguments:
                jid (str):          JID of player to mute.
                nick (str):         MUC nickname of player to mute.
                incident_id (int):  (Optional) Specify if there's an incident ID for this
                                    mute in the database.
                reason (str):       (Optional) Specify a reason to display publicly
        """
        logging.info("Command: kick")
        with db_session() as db, db.begin():
            # Make sure the moderator exists.
            if not db.get(Moderator, kwargs['moderator']):
                logging.info("%s is not a moderator.", kwargs['moderator'])
                return False

            # Find JID by nickname
            if not jid:
                for room in self.rooms:
                    for nickname,njid in self._get_roster_jids(room).items():
                        if nickname==nick:
                            jid=njid
                            break

            if not jid:
                logging.warn("Unable to kick user. Couldn't resolve a JID")
                return False
            
            logging.info("Kicking user with JID: %s", jid)
            asyncio.ensure_future(self._muc_kick(nick or slixmpp.jid.JID(jid).user, reason=reason))
            return True


    async def _scheduled_mute_ends(self, user, db_mute_id = None):
        """ Scheduled on the scheduler and eventually run when a mute ends
        """
        try:
            if db_mute_id:
                with db_session() as db:
                    mute = db.get(Mute, db_mute_id)
                    mute.active=False
                    db.commit()
            if user in self.muted: self.muted.remove(user)
            asyncio.ensure_future(self._muc_unmute(slixmpp.jid.JID(user).user))
        except: logging.exception(format_exc())

    async def _scheduled_ban_ends(self, db_ban, user):
        """UNIMPLEMENTED
        """
        """ Scheduled on the scheduler and eventually run when a ban ends
        """
        raise NotImplemented
        
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
    parser.add_argument('-p', '--password', help="password for login")
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

    xmpp = Moderation('%s@%s/%s' % (args.login, args.domain, 'moderation'), args.password,
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
