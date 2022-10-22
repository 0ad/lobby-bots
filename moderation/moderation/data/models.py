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

"""Database schema used by the Moderation service."""

import sys

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

from moderation.data.database import Base

from chat_monitor.models import ProfanityIncident

#TODO Bans

class Mute(Base):
	__tablename__ = 'mutes'
	id = Column(Integer, primary_key=True)
	player = Column(String(255))
	start = Column(DateTime)
	end = Column(DateTime)
	incident_id = Column(Integer, ForeignKey('chatmonitor_profanity_incidents.id'))
	moderator = Column(String(255), ForeignKey('moderators.jid'))
	active = Column(Boolean, default=True)
	deleted = Column(Boolean)
	incident = relationship('ProfanityIncident')

class Moderator(Base):
	__tablename__ = 'moderators'
	jid = Column(String(255), primary_key=True)
