# The moderation service
The main moderation service performs and keeps track of mutes, bans,
kicks, etc. and removes them when they expire. 

It also manages moderator reports and warnings.


# Other components
There are other helpful components included: 

## Chat monitor
A chat monitor for simple keyword-based automated moderation,

## Chatbot interface
A chatbot interface to the moderation service,

## Web interface
A web interface to the moderation service.

# Installation
python3 -mvenv venv

venv/bin/pip install -e .

If you want to use the web interface install it with

venv/bin/pip install -e[web_interface]

# Run the services
There are 4 entrypoints:
venv/bin/moderation

venv/bin/chatbot_interface

venv/bin/chat_monitor

venv/bin/web_interface

use the --help argument with those commands to see the usage for 
specifying username, password, etc.
