#!/usr/bin/env python3

"""setup.py for 0ad lobby moderation."""

from setuptools import find_packages, setup

WEB_INTERFACE_REQUIREMENTS = [
    'MarkupSafe==2.0.1',
    'email_validator',
    'Flask',
    'Flask-security',
    'bcrypt==3.1.7',
]
TEST_REQUIREMENTS = [
    'coverage',
    'hypothesis',
    'parameterized',
]

setup(
    name='Lobby Moderation Application',
    version='0.27',
    description='Service to aid moderating the lobby',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'chat_monitor=chat_monitor.chat_monitor:main',
            'chatbot_interface=chatbot_interface.chatbot_interface:main',
            'moderation=moderation.moderation:main',
            'web_interface=web_interface.web_interface.web_interface:main',
        ]
    },
    install_requires=[
        'aioscheduler',
        'dnspython',
        'ptpython',
        'PyMysql',
        'pytimeparse',
        'sqlalchemy',
        'slixmpp',

    ],
    extras_require={'tests': TEST_REQUIREMENTS, 'web_interface': WEB_INTERFACE_REQUIREMENTS},
    tests_require=TEST_REQUIREMENTS,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.7',
        'Topic :: Games/Entertainment',
        'Topic :: Internet :: XMPP',
    ],
    zip_safe=False,
    test_suite='tests',
)
