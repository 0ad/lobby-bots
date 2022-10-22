# 0 A.D. / Pyrogenesis Multiplayer Lobby Setup

This branch contains some of the utilities, tools, scripts, etc. that are used on the Wildfire 
Games multiplayer lobby server.

Here we can document some things about how we deploy the various services to run the multiplayer 
lobby.

The source code for the moderation service is located here. It helps to manage moderation tasks 
and provides tools for moderators and lobby helpers.

 
There are additional functionalities added to the services as they're deployed currently.


See these 2 commits:
To run the xpartamupp and echelon services with a debug console:
https://github.com/0ad/lobby-bots/commit/08e1567937578b81d68aa9c7c4cde916dc041960

To load command line arguments from environment variables:
https://github.com/0ad/lobby-bots/commit/7b47a8e0c380f9fd2a5f132bac3511f623928a8b


The services are deployed using systemd services as detailed here: 
https://code.wildfiregames.com/D1661?vs=on&id=8428#change-mOzKjFpsyS47
