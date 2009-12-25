# Copyright 2009 Doug Orleans.  Distributed under the GNU Affero
# General Public License v3.  See COPYING for details.

import urllib
import urllib2
from xml.dom import minidom

mbns = 'http://musicbrainz.org/ns/mmd-1.0#'
extns = 'http://musicbrainz.org/ns/ext-1.0#'

class Artist:
    def __init__(self, id=None, elt=None):
        if elt == None:
            url = 'http://musicbrainz.org/ws/1/artist/' + id + '?type=xml'
            doc = minidom.parse(urllib2.urlopen(url))
            elt = elementField(doc.documentElement, 'artist')
        self.id = elt.getAttribute('id')
        self.name = elementFieldValue(elt, 'name')
        self.sortname = elementFieldValue(elt, 'sort-name')

class ReleaseGroup:
    def __init__(self, elt):
        self.score = elt.getAttributeNS(extns, 'score')
        self.id = elt.getAttribute('id')
        self.type = elt.getAttribute('type')
        self.artist = Artist(elt=elementField(elt, 'artist'))
        self.title = elementFieldValue(elt, 'title')

    @staticmethod
    def search(**fields):
        fields['type'] = 'xml'
        url = ('http://musicbrainz.org/ws/1/release-group/?'
               + urllib.urlencode(fields))
        result = urllib2.urlopen(url)
        doc = minidom.parse(result)
        rgs = doc.getElementsByTagNameNS(mbns, 'release-group')
        return [ReleaseGroup(elt) for elt in rgs]

def elementField(elt, fieldName):
    fields = elt.getElementsByTagNameNS(mbns, fieldName)
    if fields:
        return fields[0]

def elementFieldValue(elt, fieldName):
    field = elementField(elt, fieldName)
    if field:
        return textContent(field)

# Node.textContent is only in DOM Level 3...
def textContent(node):
    node.normalize()
    return ''.join(node.data for node in node.childNodes
                   if node.nodeType == node.TEXT_NODE)


