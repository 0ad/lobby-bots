This is a web interface to the lobby moderation service.

# Install
This is an extra part of the Moderation package. To install the web interface, 
start from the Moderation package source root directory.

`cd moderation/`

If you didn't already create a venv create it with
`python3 -m venv venv`

Run pip from within the venv.
`venv/bin/pip install -e .[web_interface]`

# Test run
For development and other purposes we can run the web interface from the command 
line or other method.
`venv/bin/web_interface`

