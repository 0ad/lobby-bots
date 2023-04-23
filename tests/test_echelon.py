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

"""Tests for EcheLOn."""

import sys

from argparse import Namespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

from parameterized import parameterized
from slixmpp.jid import JID
from sqlalchemy import create_engine

from xpartamupp.echelon import Leaderboard, main, parse_args
from xpartamupp.lobby_ranking import Base


class TestLeaderboard(TestCase):
    """Test Leaderboard functionality."""

    def setUp(self):
        """Set up a leaderboard instance."""
        db_url = 'sqlite://'
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
        with patch('xpartamupp.echelon.create_engine') as create_engine_mock:
            create_engine_mock.return_value = engine
            self.leaderboard = Leaderboard(db_url)

    def test_create_player(self):
        """Test creating a new player."""
        player = self.leaderboard.get_or_create_player(JID('john@localhost/0ad'))
        self.assertEqual(player.id, 1)
        self.assertEqual(player.jid, 'john@localhost/0ad')
        self.assertEqual(player.rating, -1)
        self.assertEqual(player.highest_rating, None)
        self.assertEqual(player.games, [])
        self.assertEqual(player.games_info, [])
        self.assertEqual(player.games_won, [])

    def test_create_player_with_casing(self):
        """Test creating players with different casing.

        When calling get_or_create_player once with the player name in
        lowercase and once in uppercase should result in the same player
        object, as player names are supposed to be case-insensitive.
        """
        player1 = self.leaderboard.get_or_create_player(JID('john@localhost/0ad'))
        player2 = self.leaderboard.get_or_create_player(JID('JOHN@localhost/0ad'))
        self.assertEqual(player1, player2)

    def test_create_player_with_special_chars(self):
        """Test creating players with special characters.

        Test that creating players whose nicks only differ by allowed
        special characters result in different items in the leaderboard
        database.
        """
        player = self.leaderboard.get_or_create_player(JID('john@localhost/0ad'))
        self.assertEqual(player.id, 1)
        player = self.leaderboard.get_or_create_player(JID('joh.@localhost/0ad'))
        self.assertEqual(player.id, 2)
        player = self.leaderboard.get_or_create_player(JID('joh_@localhost/0ad'))
        self.assertEqual(player.id, 3)
        player = self.leaderboard.get_or_create_player(JID('joh-@localhost/0ad'))
        self.assertEqual(player.id, 4)

    def test_get_profile_no_player(self):
        """Test profile retrieval for not existing player."""
        profile = self.leaderboard.get_profile(JID('john@localhost/0ad'))
        self.assertEqual(profile, {})

    def test_get_profile_player_without_games(self):
        """Test profile retrieval for existing player."""
        self.leaderboard.get_or_create_player(JID('john@localhost/0ad'))
        profile = self.leaderboard.get_profile(JID('john@localhost/0ad'))
        self.assertDictEqual(profile, {'highestRating': None, 'losses': 0, 'totalGamesPlayed': 0,
                                       'wins': 0})

    def test_get_profile_ambiguous_player(self):
        """Test profile retrieval if similar player exists.

        This is a regression test to ensure special characters in player
        names get handled properly when retrieving player profiles.
        """
        self.leaderboard.get_or_create_player(JID('john@localhost/0ad'))
        profile = self.leaderboard.get_profile(JID('joh.@localhost/0ad'))
        self.assertEqual(profile, {})
        profile = self.leaderboard.get_profile(JID('joh_@localhost/0ad'))
        self.assertEqual(profile, {})
        profile = self.leaderboard.get_profile(JID('joh-@localhost/0ad'))
        self.assertEqual(profile, {})

    def test_get_profile_with_casing(self):
        """Test profile retrieval with case differences.

        Test that the same profile gets returned, no matter whether the
        player name is provided as lower case or upper case.
        """
        self.leaderboard.get_or_create_player(JID('john@localhost/0ad'))
        profile1 = self.leaderboard.get_profile(JID('john@localhost/0ad'))
        profile2 = self.leaderboard.get_profile(JID('JOHN@localhost/0ad'))
        self.assertEqual(profile1, profile2)


class TestArgumentParsing(TestCase):
    """Test handling of parsing command line parameters."""

    @parameterized.expand([
        ([],
         Namespace(domain='lobby.wildfiregames.com', login='EcheLOn', log_level=30, xserver=None,
                   no_verify=False, nickname='RatingsBot', password='XXXXXX', room='arena',
                   database_url='sqlite:///lobby_rankings.sqlite3')),
        (['--debug'],
         Namespace(domain='lobby.wildfiregames.com', login='EcheLOn', log_level=10, xserver=None,
                   no_verify=False, nickname='RatingsBot', password='XXXXXX', room='arena',
                   database_url='sqlite:///lobby_rankings.sqlite3')),
        (['--quiet'],
         Namespace(domain='lobby.wildfiregames.com', login='EcheLOn', log_level=40, xserver=None,
                   no_verify=False, nickname='RatingsBot', password='XXXXXX', room='arena',
                   database_url='sqlite:///lobby_rankings.sqlite3')),
        (['--verbose'],
         Namespace(domain='lobby.wildfiregames.com', login='EcheLOn', log_level=20, xserver=None,
                   no_verify=False, nickname='RatingsBot', password='XXXXXX', room='arena',
                   database_url='sqlite:///lobby_rankings.sqlite3')),
        (['-m', 'lobby.domain.tld'],
         Namespace(domain='lobby.domain.tld', login='EcheLOn', log_level=30, nickname='RatingsBot',
                   xserver=None, no_verify=False, password='XXXXXX', room='arena',
                   database_url='sqlite:///lobby_rankings.sqlite3')),
        (['--domain=lobby.domain.tld'],
         Namespace(domain='lobby.domain.tld', login='EcheLOn', log_level=30, nickname='RatingsBot',
                   xserver=None, no_verify=False, password='XXXXXX', room='arena',
                   database_url='sqlite:///lobby_rankings.sqlite3')),
        (['-m', 'lobby.domain.tld', '-l', 'bot', '-p', '123456', '-n', 'Bot', '-r', 'arena123',
          '-v'],
         Namespace(domain='lobby.domain.tld', login='bot', log_level=20, nickname='Bot',
                   xserver=None, no_verify=False, password='123456', room='arena123',
                   database_url='sqlite:///lobby_rankings.sqlite3')),
        (['--domain=lobby.domain.tld', '--login=bot', '--password=123456', '--nickname=Bot',
          '--room=arena123', '--database-url=sqlite:////tmp/db.sqlite3', '--verbose'],
         Namespace(domain='lobby.domain.tld', login='bot', log_level=20, nickname='Bot',
                   xserver=None, no_verify=False, password='123456', room='arena123',
                   database_url='sqlite:////tmp/db.sqlite3')),
        (['--no-verify'],
         Namespace(domain='lobby.wildfiregames.com', login='EcheLOn', log_level=30, xserver=None,
                   no_verify=True, nickname='RatingsBot', password='XXXXXX', room='arena',
                   database_url='sqlite:///lobby_rankings.sqlite3')),
    ])
    def test_valid(self, cmd_args, expected_args):
        """Test valid parameter combinations."""
        with patch.object(sys, 'argv', ['echelon'] + cmd_args):
            self.assertEqual(expected_args, parse_args())

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
        with patch.object(sys, 'argv', ['echelon'] + cmd_args), self.assertRaises(SystemExit):
            parse_args()


class TestMain(TestCase):
    """Test main method."""

    def test_success(self):
        """Test successful execution."""
        with patch('xpartamupp.echelon.parse_args') as args_mock, \
                patch('xpartamupp.echelon.Leaderboard') as leaderboard_mock, \
                patch('xpartamupp.echelon.EcheLOn') as xmpp_mock, \
                patch('xpartamupp.echelon.asyncio') as asyncio_mock:
            args_mock.return_value = Mock(log_level=30, login='EcheLOn',
                                          domain='lobby.wildfiregames.com', password='XXXXXX',
                                          room='arena', nickname='RatingsBot',
                                          database_url='sqlite:///lobby_rankings.sqlite3',
                                          xserver=None, no_verify=False)
            main()
            args_mock.assert_called_once_with()
            leaderboard_mock.assert_called_once_with('sqlite:///lobby_rankings.sqlite3')
            xmpp_mock().register_plugin.assert_has_calls([call('xep_0004'), call('xep_0030'),
                                                          call('xep_0045'), call('xep_0060'),
                                                          call('xep_0199', {'keepalive': True})],
                                                         any_order=True)
            xmpp_mock().connect.assert_called_once_with(None)
            asyncio_mock.get_event_loop.assert_called_once_with()
            asyncio_mock.get_event_loop.return_value.run_forever_assert_called_once_with()
