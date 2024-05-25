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

"""Database schema used by the XMPP bots to store moderation data."""

import argparse
import enum
from datetime import UTC, datetime
from functools import partial
from typing import Any, ClassVar

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    TypeDecorator,
    UnicodeText,
    create_engine,
    func,
    select,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import DeclarativeBase, Mapped, aliased, mapped_column, object_session


class TZDateTime(TypeDecorator):
    """Timezone aware DateTime datatype for SQLAlchemy."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, _):
        """Store datetime values in UTC in the database."""
        if value is not None:
            if not value.tzinfo or value.tzinfo.utcoffset(value) is None:
                raise TypeError("timezone aware datetime object required")
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value, _):
        """Add UTC as timezone for values returned from the database."""
        if value is not None:
            value = value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    """Base class for models.

    Defaults to use a timezone aware datatype for datetimes.
    """

    type_annotation_map: ClassVar[dict[str, TypeDecorator]] = {
        datetime: TZDateTime(),
    }


class Blacklist(Base):
    """Model for profanity terms."""

    __tablename__ = "profanity_blacklist"

    word: Mapped[str] = mapped_column(String(255), primary_key=True)


class Whitelist(Base):
    """Model for terms which are whitelisted from profanity."""

    __tablename__ = "profanity_whitelist"

    word: Mapped[str] = mapped_column(String(255), primary_key=True)


class ProfanityIncident(Base):
    """Model for profanity incidents."""

    __tablename__ = "profanity_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime]
    player: Mapped[str] = mapped_column(String(255))
    offending_content: Mapped[str] = mapped_column(UnicodeText)
    deleted: Mapped[bool]


class JIDNickWhitelist(Base):
    """Model for JIDs which are permitted to change their nick."""

    __tablename__ = "jid_nick_whitelist"

    jid: Mapped[str] = mapped_column(String(255), primary_key=True)


class EventType(enum.Enum):
    """Enum for different event types.

    Used as key for to differentiate records with single table
    inheritance.
    """

    mute = "mute"
    unmute = "unmute"
    kick = "kick"


class ModerationEvent(Base):
    """Base model for moderation events."""

    __tablename__ = "moderation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_date: Mapped[datetime] = mapped_column(default=partial(datetime.now, tz=UTC))
    event_type: Mapped[EventType]
    moderator: Mapped[str] = mapped_column(String(255), ForeignKey("moderators.jid"))
    player: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(UnicodeText)

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_on": "event_type",
        "polymorphic_abstract": True,
    }


class MuteEvent(ModerationEvent):
    """Model for a mute event."""

    mute_end: Mapped[datetime] = mapped_column(nullable=True)

    @hybrid_property
    def is_active(self) -> bool:
        """Filter to return only active mute events.

        A mute event is considered active, if the current time is in
        the range of the mute and there has been no unmute event after
        the muting started.

        Returns true if a mute event is active and false if not.
        """
        in_time_range = self.event_date <= datetime.now(tz=UTC) < self.mute_end
        not_unmuted = not bool(
            object_session(self)
            .execute(
                select(UnmuteEvent)
                .filter_by(player=self.player)
                .filter(UnmuteEvent.event_date >= self.event_date)
                .filter(UnmuteEvent.event_date < self.mute_end)
            )
            .first()
        )

        return in_time_range and not_unmuted

    @is_active.inplace.expression
    @classmethod
    def _is_active_expression(cls) -> str:
        """Filter to return only active mute events.

        A mute event is considered active, if the current time is in
        the range of the mute and there has been no unmute event after
        the muting started.

        Returns an SQLAlchemy filter expression to filter for active
        mute events.
        """
        now = datetime.now(tz=UTC)
        in_time_range = (cls.event_date <= now) & (now < cls.mute_end)
        unmute_event_alias = aliased(UnmuteEvent)
        unmuted = (
            select(func.count("*"))
            .select_from(unmute_event_alias)
            .filter(unmute_event_alias.player == cls.player)
            .filter(unmute_event_alias.event_date >= cls.event_date)
            .filter(unmute_event_alias.event_date < cls.mute_end)
            .limit(1)
            .as_scalar()
        )

        return in_time_range & ~unmuted

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_identity": EventType.mute,
    }


class UnmuteEvent(ModerationEvent):
    """Model for an unmute event."""

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_identity": EventType.unmute,
    }


class KickEvent(ModerationEvent):
    """Model for a kick event."""

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_identity": EventType.kick,
    }


class Moderator(Base):
    """Model for storing the JIDs of lobby moderators."""

    __tablename__ = "moderators"

    jid: Mapped[str] = mapped_column(String(255), primary_key=True)


def parse_args():
    """Parse command line arguments.

    Returns:
         Parsed command line arguments

    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Helper command for database creation",
    )
    parser.add_argument("action", help="Action to apply to the database", choices=["create"])
    parser.add_argument(
        "--database-url",
        help="URL for the moderation database",
        default="sqlite:///lobby_moderation.sqlite3",
    )
    return parser.parse_args()


def main():
    """Entry point a console script."""
    args = parse_args()
    engine = create_engine(args.database_url)
    if args.action == "create":
        Base.metadata.create_all(engine)


if __name__ == "__main__":
    main()
