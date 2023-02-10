#!/usr/bin/env python3

"""setup.py for 0ad XMPP lobby bots."""

from setuptools import find_packages, setup

TEST_REQUIREMENTS = [
    'coverage',
    'hypothesis',
    'parameterized',
]

setup(
    name='XpartaMuPP',
    version='0.24',
    description='Multiplayer lobby bots for 0ad',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'echelon=xpartamupp.echelon:main',
            'xpartamupp=xpartamupp.xpartamupp:main',
            'echelon-db=xpartamupp.lobby_ranking:main',
        ]
    },
    install_requires=[
        'defusedxml',
        'slixmpp>=1.8.0',
        'sqlalchemy>=1.4.0',
    ],
    extras_require={'tests': TEST_REQUIREMENTS},
    tests_require=TEST_REQUIREMENTS,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Games/Entertainment',
        'Topic :: Internet :: XMPP',
    ],
    zip_safe=False,
    test_suite='tests',
)
