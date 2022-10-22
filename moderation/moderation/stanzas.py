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

"""XMPP plugins for the moderation service"""

from slixmpp.xmlstream import ET, ElementBase
from pprint import pprint

"""Classes for generating and parsing IQ stanzas."""

class ModerationXmppPlugin(ElementBase):
    name = 'query'
    namespace = 'jabber:iq:moderation'
    plugin_attrib = 'moderation'

class ModerationCommand(ElementBase):
    name = 'command'
    namespace = 'jabber:iq:moderation'
    plugin_attrib = 'moderation_command'
    interfaces = {'command_name', 'params', 'results'}

    def get_command_name(self):
        return self._get_attr('name')

    def set_command_name(self, value):
        return self._set_attr('name', value)

    def get_params(self):
        params = self.xml.find('{%s}params' % self.namespace)
        if params is not None: return { key:item for (key, item) in params.attrib.items() }
        return {}

    def set_params(self, params):
        self.xml.append(ET.Element('params', params))

    def get_results(self):
        results = []
        results_xml = self.xml.findall('{%s}result' % (self.namespace))
        if results_xml is not None: 
            for result in results_xml: 
                results.append({ key:item for (key, item) in result.attrib.items() })
        return results

    def add_result(self, result):
        result = { key:str(item) for key,item in result.items()}
        self.xml.append(ET.Element('result', result))

    def set_results(self, result):
        if type(result) is not list:
            results = [ result ]
        else: results = result
        
        # Remove any result elements already present
        results_xml = self.xml.find('{%s}result' % self.namespace)
        if results_xml is not None:
            for result in results_xml:
                self.xml.remove(result)

        for result in results:
            self.xml.append(ET.Element('result', result))
