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

import os

from datetime import datetime, timedelta
from flask import Flask, request, redirect, url_for, render_template
from flask_security import Security, login_required, \
     SQLAlchemySessionUserDatastore
from moderation.data.database import db_session, create_tables, row2dict
from moderation.data.models import Mute, Moderator
from chat_monitor.models import ProfanityIncident
from pprint import pprint
from sqlalchemy.sql import select, operators
from web_interface.web_interface.web_user_model import WebUser, WebRole

def create_app():
    app = Flask(__name__)
    app.config.from_mapping(
        TEMPLATES_AUTO_RELOAD = True,
        SECRET_KEY='secret_key',
        SECURITY_PASSWORD_SALT="secret_salt",
        SECURITY_REGISTERABLE=True,SECURITY_SEND_REGISTER_EMAIL=False,
        SECURITY_SEND_PASSWORD_CHANGE_EMAIL=False,
        SECURITY_SEND_PASSWORD_RESET_EMAIL=False,
        SECURITY_SEND_PASSWORD_RESET_NOTICE_EMAIL=False
    )

    user_datastore = SQLAlchemySessionUserDatastore(db_session,
                                                WebUser, WebRole)
    security = Security(app, user_datastore)

#    Enable this to intialize a new database.
#    @app.route("/create_database_tables")
#    def initialize_database():
#        create_tables()
#        return redirect("/")

    @app.route("/")
    @login_required
    def index():
        with db_session() as db:
            content=db.execute(select(Mute).where(operators.isnot(Mute.deleted, True), Mute.start >= datetime.now() - timedelta(days=2) ).order_by(Mute.start.desc())).scalars().all()
            content = [row2dict(row) for row in content]
            for item in content:
                print((datetime.now() - item['start']).seconds)
                if item['end'] and item['start']:
                    item['rounded_duration'] = round_duration((item['end'] - item['start']).seconds)
                    item['rounded_start'] = round_duration((datetime.now() - item['start']).seconds)
        return render_template("index.html", content=content)

    @app.route("/mutes")
    @login_required
    def mutes(): ...
#        TODO
#        db_session().execute(select(Mute).filter_by(active=True, deleted is not None).all

    return app


def round_duration(duration):
    '''Get a shortened, human-readable, rounded approximation of the
        duration.
        
        Arguments:
            duration : Duration to convert specified in seconds.

        Returns: String
        
    '''
    def round_nearest_half(number):
        return round(number * 2) /2

    return_=[]
    seconds = duration
    minutes = int(0)
    hours = 0
    days = 0
    weeks = 0
    if seconds > 60:
        minutes = int(seconds / 60)
        if minutes > 60:
            hours = int(minutes / 60)
            if hours > 24:
                days = int(hours / 24)
                if days > 7:
                    return f"about {round_nearest_half(days/7):g} weeks"
                return f"about {round_nearest_half(hours/24):g} days"
            return f"about {round_nearest_half(minutes/60):g} hours"
        return f"about {round_nearest_half(seconds/60):g} minutes"
    return f"about {seconds} seconds"

