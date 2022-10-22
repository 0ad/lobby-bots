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

"""Database schema used by the Chat Monitor."""

import sys

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, DateTime, UnicodeText
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

from moderation.data.database import Base

class Blacklist(Base):
	__tablename__ = 'chatmonitor_blacklist'
	word = Column(String(255), primary_key=True)

class Whitelist(Base):
	__tablename__ = 'chatmonitor_whitelist'
	word = Column(String(255), primary_key=True)

class ProfanityIncident(Base):
	__tablename__ = 'chatmonitor_profanity_incidents'
	id = Column(Integer, primary_key=True)
	timestamp = Column(DateTime)
	player = Column(String(255))
	offending_content = Column(UnicodeText)
	deleted = Column(Boolean)
