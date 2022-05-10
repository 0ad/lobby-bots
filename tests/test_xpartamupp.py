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

# pylint: disable=no-self-use

"""Tests for XPartaMuPP."""

import sys

from argparse import Namespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

from parameterized import parameterized
from sleekxmpp.jid import JID

from xpartamupp.xpartamupp import Games, main, parse_args


class TestGames(TestCase):
    """Test Games class responsible for holding active games."""

    def test_add(self):
        """Test successfully adding a game."""
        games = Games()
        jid = JID(jid='player1@domain.tld/0ad-asdf1234')
        # TODO: Check how the real format of data looks like
        game_data = {'players': ['player1', 'player2'], 'nbp': 'foo', 'state': 'init'}
        self.assertTrue(games.add_game(jid, game_data))
        all_games = games.get_all_games()
        game_data.update({'players-init': game_data['players'], 'nbp-init': game_data['nbp'],
                          'state': game_data['state']})
        self.assertListEqual(all_games, [game_data])

    @parameterized.expand([
        ('', {}),
        ('player1@domain.tld/0ad-asdf1234', {}),
        ('player1@domain.tld/0ad-asdf1234', None),
        ('player1@domain.tld/0ad-asdf1234', ''),
    ])
    def test_add_invalid(self, jid, game_data):
        """Test trying to add games with invalid data."""
        games = Games()
        self.assertFalse(games.add_game(jid, game_data))

    def test_remove(self):
        """Test removal of games."""
        games = Games()
        jid1 = JID(jid='player1@domain.tld/0ad-asdf1234')
        jid2 = JID(jid='player3@domain.tld/0ad-qwer2345')
        # TODO: Check how the real format of data looks like
        game_data1 = {'players': ['player1', 'player2'], 'nbp': 'foo', 'state': 'init'}
        games.add_game(jid1, game_data1)
        game_data2 = {'players': ['player3', 'player4'], 'nbp': 'bar', 'state': 'init'}
        games.add_game(jid2, game_data2)
        game_data1.update({'players-init': game_data1['players'], 'nbp-init': game_data1['nbp'],
                           'state': game_data1['state']})
        game_data2.update({'players-init': game_data2['players'], 'nbp-init': game_data2['nbp'],
                           'state': game_data2['state']})
        self.assertListEqual(games.get_all_games(), [game_data1, game_data2])
        games.remove_game(jid1)
        self.assertListEqual(games.get_all_games(), [game_data2])
        games.remove_game(jid2)
        self.assertListEqual(games.get_all_games(), [])

    def test_remove_all_games_for_jid(self):
        """Test removal of all games belonging to a jid."""
        games = Games()

        jids = []

        jids.append(JID(jid="player1@domain.tld", resource="0ad-asdf1234"))
        jids.append(JID(jid="player1@domain.tld", resource="0ad-qwer2345"))
        jids.append(JID(jid="player1@domain.tld", resource="0ad-zxcv3456"))
        jids.append(JID(jid="player2@domain.tld", resource="0ad-tyui4567"))
        jids.append(JID(jid="player3@domain.tld", resource="0ad-ghjk5678"))
        jids.append(JID(jid="player4@domain.tld", resource="0ad-bnmp6789"))

        game_data1 = {'players': ['player1', 'player2'], 'nbp': 'foo', 'state': 'init'}
        games.add_game(jids[0], game_data1)
        game_data2 = {'players': ['player3', 'player4'], 'nbp': 'bar', 'state': 'init'}
        games.add_game(jids[1], game_data2)
        game_data3 = {'players': ['player5', 'player6'], 'nbp': 'bar', 'state': 'init'}
        games.add_game(jids[2], game_data3)
        game_data4 = {'players': ['player7', 'player8'], 'nbp': 'foo', 'state': 'init'}
        games.add_game(jids[3], game_data4)
        game_data5 = {'players': ['player9', 'playera'], 'nbp': 'bar', 'state': 'init'}
        games.add_game(jids[4], game_data5)
        game_data6 = {'players': ['playerb', 'playerc'], 'nbp': 'bar', 'state': 'init'}
        games.add_game(jids[5], game_data6)

        game_data1.update({'players-init': game_data1['players'],
                           'nbp-init': game_data1['nbp'],
                           'state': game_data1['state']})
        game_data2.update({'players-init': game_data2['players'],
                           'nbp-init': game_data2['nbp'],
                           'state': game_data2['state']})
        game_data3.update({'players-init': game_data3['players'],
                           'nbp-init': game_data3['nbp'],
                           'state': game_data3['state']})
        game_data4.update({'players-init': game_data4['players'],
                           'nbp-init': game_data4['nbp'],
                           'state': game_data4['state']})
        game_data5.update({'players-init': game_data5['players'],
                           'nbp-init': game_data5['nbp'],
                           'state': game_data5['state']})
        game_data6.update({'players-init': game_data6['players'],
                           'nbp-init': game_data6['nbp'],
                           'state': game_data6['state']})

        expected_games_dict = {
            jids[0].bare: {jids[0].resource: game_data1, jids[1].resource: game_data2,
                           jids[2].resource: game_data3},
            jids[3].bare: {jids[3].resource: game_data4},
            jids[4].bare: {jids[4].resource: game_data5},
            jids[5].bare: {jids[5].resource: game_data6}}
        self.assertDictEqual(games.games, expected_games_dict)

        games.remove_all_games_for_jid(jids[0])

        expected_games_dict = {
            jids[3].bare: {jids[3].resource: game_data4},
            jids[4].bare: {jids[4].resource: game_data5},
            jids[5].bare: {jids[5].resource: game_data6}}
        self.assertDictEqual(expected_games_dict, games.games)

    def test_remove_unknown(self):
        """Test removal of a game, which doesn't exist."""
        games = Games()
        jid = JID('player1@domain.tld/0ad-asdf1234')
        # TODO: Check how the real format of data looks like
        game_data = {'players': ['player1', 'player2'], 'nbp': 'foo', 'state': 'init'}
        games.add_game(jid, game_data)
        self.assertFalse(games.remove_game(JID('foo@bar.tld/0ad-qwer2345')))

    def test_change_state(self):
        """Test state changes of a games."""
        # slightly unknown how to do that properly, as some data structures aren't known


class TestArgumentParsing(TestCase):
    """Test handling of parsing command line parameters."""

    @parameterized.expand([
        ([], Namespace(domain='lobby.wildfiregames.com', login='xpartamupp', log_level=30,
                       xserver=None, xdisabletls=False,
                       nickname='WFGBot', password='XXXXXX', room='arena')),
        (['--debug'],
         Namespace(domain='lobby.wildfiregames.com', login='xpartamupp', log_level=10,
                   xserver=None, xdisabletls=False,
                   nickname='WFGBot', password='XXXXXX', room='arena')),
        (['--quiet'],
         Namespace(domain='lobby.wildfiregames.com', login='xpartamupp', log_level=40,
                   xserver=None, xdisabletls=False,
                   nickname='WFGBot', password='XXXXXX', room='arena')),
        (['--verbose'],
         Namespace(domain='lobby.wildfiregames.com', login='xpartamupp', log_level=20,
                   xserver=None, xdisabletls=False,
                   nickname='WFGBot', password='XXXXXX', room='arena')),
        (['-m', 'lobby.domain.tld'],
         Namespace(domain='lobby.domain.tld', login='xpartamupp', log_level=30, nickname='WFGBot',
                   xserver=None, xdisabletls=False,
                   password='XXXXXX', room='arena')),
        (['--domain=lobby.domain.tld'],
         Namespace(domain='lobby.domain.tld', login='xpartamupp', log_level=30, nickname='WFGBot',
                   xserver=None, xdisabletls=False,
                   password='XXXXXX', room='arena')),
        (['-m', 'lobby.domain.tld', '-l', 'bot', '-p', '123456', '-n', 'Bot', '-r', 'arena123',
          '-v'],
         Namespace(domain='lobby.domain.tld', login='bot', log_level=20, xserver=None,
                   xdisabletls=False,
                   nickname='Bot', password='123456', room='arena123')),
        (['--domain=lobby.domain.tld', '--login=bot', '--password=123456', '--nickname=Bot',
          '--room=arena123', '--verbose'],
         Namespace(domain='lobby.domain.tld', login='bot', log_level=20, xserver=None,
                   xdisabletls=False,
                   nickname='Bot', password='123456', room='arena123')),
    ])
    def test_valid(self, cmd_args, expected_args):
        """Test valid parameter combinations."""
        self.assertEqual(parse_args(cmd_args), expected_args)

    @parameterized.expand([
        (['-f'],),
        (['--foo'],),
        (['--debug', '--quiet'],),
        (['--quiet', '--verbose'],),
        (['--debug', '--verbose'],),
        (['--debug', '--quiet', '--verbose'],),
    ])
    def test_invalid(self, cmd_args):
        """Test invalid parameter combinations."""
        with self.assertRaises(SystemExit):
            parse_args(cmd_args)


class TestMain(TestCase):
    """Test main method."""

    def test_success(self):
        """Test successful execution."""
        with patch('xpartamupp.xpartamupp.parse_args') as args_mock, \
                patch('xpartamupp.xpartamupp.XpartaMuPP') as xmpp_mock:
            args_mock.return_value = Mock(log_level=30, login='xpartamupp',
                                          domain='lobby.wildfiregames.com', password='XXXXXX',
                                          room='arena', nickname='WFGBot',
                                          xserver=None, xdisabletls=False)
            main()
            args_mock.assert_called_once_with(sys.argv[1:])
            xmpp_mock().register_plugin.assert_has_calls([call('xep_0004'), call('xep_0030'),
                                                          call('xep_0045'), call('xep_0060'),
                                                          call('xep_0199', {'keepalive': True})],
                                                         any_order=True)
            xmpp_mock().connect.assert_called_once_with(None, True, True)
            xmpp_mock().process.assert_called_once_with()

    def test_failing_connect(self):
        """Test failing connect to XMPP server."""
        with patch('xpartamupp.xpartamupp.parse_args') as args_mock, \
                patch('xpartamupp.xpartamupp.XpartaMuPP') as xmpp_mock:
            args_mock.return_value = Mock(log_level=30, login='xpartamupp',
                                          domain='lobby.wildfiregames.com', password='XXXXXX',
                                          room='arena', nickname='WFGBot',
                                          xserver=None, xdisabletls=False)

            xmpp_mock().connect.return_value = False
            main()
            args_mock.assert_called_once_with(sys.argv[1:])
            xmpp_mock().register_plugin.assert_has_calls([call('xep_0004'), call('xep_0030'),
                                                          call('xep_0045'), call('xep_0060'),
                                                          call('xep_0199', {'keepalive': True})],
                                                         any_order=True)
            xmpp_mock().connect.assert_called_once_with(None, True, True)
            xmpp_mock().process.assert_not_called()
