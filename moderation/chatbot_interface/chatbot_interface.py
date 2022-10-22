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

"""Service providing a chatbot interface to the moderation service

The chatbot will join a MUC room and receive commands from moderators
in the chatroom.
"""

import argparse
import asyncio
import difflib
import logging
import re
import slixmpp
import sys

from datetime import datetime, timedelta
from functools import partial
from gettext import gettext
from moderation.stanzas import ModerationXmppPlugin, ModerationCommand
from pprint import pprint, pformat
from ptpython.repl import embed
from slixmpp.stanza import Iq
from slixmpp.xmlstream import ET
from slixmpp.xmlstream.handler import Callback
from slixmpp.xmlstream.matcher import StanzaPath
from slixmpp.xmlstream.stanzabase import register_stanza_plugin
from traceback import format_exc

class CommandProcessor():
    """ Configure a parser to handle commands.
    """
    def __init__(self):
        """ Chatbot commands are added as subparsers.
        The available commands (help, mutelist, mute, unmute) are defined here.
        """

        self.parser = ChatbotArgumentParser(prog="", description='Moderation Bot', add_help=False)
        self.parser._positionals.title = "Available commands"
        subparser = self.parser.add_subparsers(help="Use help [command] for more information", dest="command")
        self.subparsers = {}
       
        # Help
        self.subparsers['help'] = subparser.add_parser('help', description='Get help', add_help=False)
        self.subparsers['help'].add_argument('helpcmd', action='store', help='Get help on a specific command', nargs='?', metavar='help-command', )

        # Ban (TODO)
        #self.subparsers['ban'] = subparser.add_parser('ban', description='Add a player to the ban list (not implemented yet)', add_help=False)
        #self.subparsers['ban'].add_argument('jid', action='store', help='Specify jid', )

        # Unban (TODO)
        #self.subparsers['unban'] = subparser.add_parser('unban', description='Unban a previously banned player (not implemented yet)', add_help=False)
        #self.subparsers['unban'].add_argument('jid', action='store', help='Specify jid', )

        # Mutelist
        self.subparsers['mutelist'] = subparser.add_parser('mutelist', description='Get mute list', add_help=False)

        # Mute
        self.subparsers['mute'] = subparser.add_parser('mute', description='Add a player to the mute list', add_help=False, formatter_class=CondensingFormatter)
        match_by = self.subparsers['mute'].add_mutually_exclusive_group()
        match_by.add_argument('--nick', dest="match_by", action='store_const', const='nick', help='Match by nick', )
        match_by.add_argument('--regex', dest="match_by", action='store_const', const='regex', help='Match by regex (not implemented yet)', )
        match_by.add_argument('-j', '--jid', dest="match_by", action='store_const', const='jid', help='Match by JID', )
        match_by.set_defaults(match_by='nick')
        self.subparsers['mute'].add_argument('user', action='store', help='User to mute', )
        self.subparsers['mute'].add_argument('duration', action=join_with_spaces, help='For a timed mute, specify duration', default='15 minutes'.split(" "), nargs='*', )
        self.subparsers['mute'].add_argument('-r', '--reason', action=join_with_spaces, help='Add a reason', nargs='+', )

        # Unmute
        self.subparsers['unmute'] = subparser.add_parser('unmute', description='Remove a player from the mute list', add_help=False)
        match_by = self.subparsers['unmute'].add_mutually_exclusive_group()
        match_by.add_argument('--nick', dest="match_by", action='store_const', const='nick', help='Match by nick', )
        match_by.add_argument('--regex', dest="match_by", action='store_const', const='regex', help='Match by regex (not implemented yet)', )
        match_by.add_argument('-j', '--jid', dest="match_by", action='store_const', const='jid', help='Match by JID', )
        match_by.set_defaults(match_by='nick')
        self.subparsers['unmute'].add_argument('user', action='store', help='User to unmute', )
        self.subparsers['unmute'].add_argument('-r', '--reason', action=join_with_spaces, help='Add a reason', nargs='+',)

    async def process_commands(self, moderator, text):
        def get_response():
            return "\n".join(self.parser.response)
        try: parsed = self.parser.parse_args(text)
        except (argparse.ArgumentError) as e: 
            print(e.message)
            print("yup", get_response())
            return get_response()
        parsed = vars(parsed)
        command = parsed['command']
        if command and command in self.subparsers:
            command_method = getattr(self, "command_"+command)
            try:
                task=asyncio.create_task(command_method(moderator, **parsed))
                await task
                if task.exception(): logging.exception(format_exc)
                return task.result()
            except: logging.exception(format_exc())
        return get_response()


class BotCommandProcessor(CommandProcessor):
    def __init__(self, xmpp):
        self.xmpp=xmpp
        super().__init__()

    async def command_help(self, moderator, **kargs):
        logging.debug("command_help: %s", pformat(kargs))
        response=[]
        if kargs['helpcmd']:
            if kargs['helpcmd'] in self.subparsers: response.append(self.subparsers[kargs['helpcmd']].format_help())
            else:
                response.append("Couldn't retrieve help for unrecognized command.")
                response.append(self.parser.format_help())
        else:
            response.append(self.parser.format_help())
        return "\n".join(response)

    async def command_ban(self, moderator, jid, **kargs):
        logging.debug("command_ban: %s", pformat(kargs))
        response=[]
        return "\n".join(response)

    async def command_unban(self, moderator, **kargs):
        logging.debug("command_unban: %s", pformat(kargs))
        response=[]
        return "\n".join(response)

    async def command_mutelist(self, moderator, **kargs):
        logging.debug("command_mutelist: %s", pformat(kargs))
        results = []
        to = slixmpp.jid.JID(self.xmpp.sjid.bare)
        to.resource = "moderation"
        iq = self.xmpp.make_iq_set(ito=slixmpp.jid.JID(self.xmpp.sjid.bare+"/moderation"))
        iq.enable('moderation')
        iq['moderation']['moderation_command']['command_name'] = "mutelist"
        response = await iq.send()
        for result in response['moderation']['moderation_command']['results']:
            pprint(result)
            if "player" in result: results.append(result)
        muted = [slixmpp.jid.JID(result['player']).user for result in results]
        if len(muted) == 0: return "There are no mutes"
        else: return "Users currently muted: %s" % ", ".join(muted)

    async def command_mute(self, moderator, reason="", **kargs):
        logging.debug("command_mute: %s", pformat(kargs))
        results = []
        to = slixmpp.jid.JID(self.xmpp.sjid.bare)
        to.resource = "moderation"
        iq = self.xmpp.make_iq_set(ito=slixmpp.jid.JID(self.xmpp.sjid.bare+"/moderation"))
        iq.enable('moderation')
        iq['moderation']['moderation_command']['command_name'] = "mute"
        params = {}
        params[kargs['match_by']] = kargs['user']
        params['reason']=reason
        params['duration']=kargs['duration']
        params['moderator']=moderator
        iq['moderation']['moderation_command']['params'] = {param:str(value) for param,value in params.items()}
        response = await iq.send()
        print(response['moderation']['moderation_command']['results'])
        command_results = response['moderation']['moderation_command']['results']
        if any(result for result in command_results if "success" in result and result['success']=="True"): results.append("Success")
        else: results.append("Failed")
        return "\n".join(results)
        
    async def command_unmute(self, moderator, reason="", **kargs):
        logging.debug("command_unmute: %s", pformat(kargs))
        results = []
        to = slixmpp.jid.JID(self.xmpp.sjid.bare)
        to.resource = "moderation"
        iq = self.xmpp.make_iq_set(ito=to)
        iq.enable('moderation')
        iq['moderation']['moderation_command']['command_name'] = "unmute"
        params = {}
        params[kargs['match_by']] = kargs['user']
        params['reason'] = reason
        params['moderator'] = moderator
        iq['moderation']['moderation_command']['params'] = {param:str(value) for param,value in params.items()}
        await iq.send()
        response = await iq.send()
        print(response['moderation']['moderation_command']['results'])
        command_results = response['moderation']['moderation_command']['results']
        if any(result for result in command_results if "success" in result and result['success']=="True"): results.append("Success")
        else: results.append("Failed")
        return "\n".join(results)

class ChatbotInterface(slixmpp.ClientXMPP):
    """Handles messages and invokes the lobby moderation service."""

    def __init__(self, sjid, password, command_room, command_password, nick, domain):
        """Initialize the chat monitor."""
        slixmpp.ClientXMPP.__init__(self, slixmpp.jid.JID(sjid), password)
        self.whitespace_keepalive = False

        self.sjid = slixmpp.jid.JID(sjid)
        self.command_room = slixmpp.jid.JID(command_room + '@conference.' + domain)
        self.command_password = command_password
        self.nick = nick
        self.background_tasks=[]

        register_stanza_plugin(Iq, ModerationXmppPlugin)
        register_stanza_plugin(ModerationXmppPlugin, ModerationCommand)

        self.add_event_handler('session_start', self._got_session_start)
        self.add_event_handler('groupchat_message', self._got_muc_message)

        self.bcp = BotCommandProcessor(self)
        
    async def _got_session_start(self, event):  # pylint: disable=unused-argument
        """Join MUC channel and announce presence.

        Arguments:
            event (dict): empty dummy dict
        """
        await self.plugin['xep_0045'].join_muc_wait(self.command_room, self.nick)
        self.send_presence()
        self.get_roster()
        logging.info("Chatbot interface started")

    def _got_muc_message(self, msg):
        """Process messages in the MUC room.

        Arguments:
            msg (slixmpp.stanza.message.Message): Received MUC
                message
        """
        logging.info("Got groupchat message")
        if 'stamp' in msg['delay'].xml.attrib: return   # Don't process this message if it is a historical message.

        lower_msg=msg['body'].lower()
        if lower_msg[0]=='!':
            task = asyncio.create_task(self.bcp.process_commands(self._get_jid(msg['muc']['nick']).bare, lower_msg[1:].split()))
            def send_reply(something):
                self.send_message(mto=msg['from'], mtype='chat',
                              mbody=something.result())
            task.add_done_callback(send_reply)
                              
    def _get_jid(self, nick):
        """Return JID for a nick
            
        Arguments:
            nick (slixmpp.jid.JID): Retrieve JID for this nick            
        """ 
        roster=self.plugin['xep_0045'].get_roster(self.command_room)
        if nick in roster: return slixmpp.jid.JID(self.plugin['xep_0045'].get_jid_property(self.command_room, nick, "jid"))
        return False
        

class CondensingFormatter(argparse.HelpFormatter):
    """ Change formatting of usage message for nargs=* and nargs=+ arguments
    """
    def _format_args(self, action, default_metavar):
        get_metavar = self._metavar_formatter(action, default_metavar)
        if action.nargs in [argparse.ONE_OR_MORE, argparse.ZERO_OR_MORE]:
            return '%s' % get_metavar(1)
        else:
            return super(CondensingFormatter, self)._format_args(action, default_metavar)

class ChatbotArgumentParser(argparse.ArgumentParser):
    """Override ArgumentParser methods to cause output to go to an accumlated 
        response which will be retrieved later. Also prevent exit from invoking sys.exit() 
        and terminating the process.
    """

    def __init__(self, *args, **kwargs):
        self.response=[]
        return super().__init__(*args, **kwargs)
    
    def parse_args(self, *args, **kwargs):
        self.response=[]
        return super().parse_args(*args, **kwargs)

    def _print_message(self, message, file=None):
        self.response.append(message)

    def error(self, message):
        self.print_help()
        logging.exception(format_exc())
        args = {'prog': self.prog, 'message': message}
        self.exit(2, gettext('%(prog)s: error: %(message)s\n') % args)

    def exit(self, status=0, message=None):
        if message:
            self._print_message(message)
        raise argparse.ArgumentError(argument=None, message=message) # Cancel parsing
    

class join_with_spaces(argparse.Action):
    """Used to combine an arbitrary number of arg values into a string
    """
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, ' '.join(values))


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
    parser.add_argument('-p', '--password', help="password for login", default='')
    parser.add_argument('-n', '--nickname', help="nickname shown to players",
                        default='ModerationBot')
    parser.add_argument('-c', '--command-room',
                        help="MUC room to join to receive moderation commands",
                        default='helpers')
    parser.add_argument('--command-password', help="Password for the command room",
                        default='')
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

    xmpp = ChatbotInterface(slixmpp.jid.JID('%s@%s/%s' % (args.login, args.domain, 'CC')), args.password,
                   args.command_room, args.command_password, args.nickname, args.domain)
    xmpp.register_plugin('xep_0030')  # Service Discovery
    xmpp.register_plugin('xep_0004')  # Data Forms
    xmpp.register_plugin('xep_0045')  # Multi-User Chat
    xmpp.register_plugin('xep_0060')  # Publish-Subscribe
    xmpp.register_plugin('xep_0199', {'keepalive': True})  # XMPP Ping

    xmpp.connect((args.xserver, 5222) if args.xserver else None, False, not args.xdisabletls)
    
    # Start a debug console
    console = asyncio.get_event_loop().create_task(partial(embed, globals=globals(), locals=locals(), return_asyncio_coroutine=True, patch_stdout=True)())
    try: await console
    except: logging.exception(format_exc())

    await xmpp.disconnect()

def main():
    asyncio.run(async_main())
    
if __name__ == '__main__':
    main()
