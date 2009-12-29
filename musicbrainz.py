# Copyright 2009 Doug Orleans.  Distributed under the GNU Affero
# General Public License v3.  See COPYING for details.

import urllib
import urllib2
from xml.dom import minidom
import time

mbns = 'http://musicbrainz.org/ns/mmd-1.0#'
extns = 'http://musicbrainz.org/ns/ext-1.0#'

def xmlHttpRequest(url):
    response = urllib2.urlopen(url)
    info = response.info()
    # TO DO: check info.status
    return minidom.parse(response)

class Resource:
    @classmethod
    def url(cls):
        return 'http://musicbrainz.org/ws/1/' + cls.type + '/'

    @classmethod
    def getElement(cls, id, *inc):
        time.sleep(1)
        fields = { 'type': 'xml', 'inc': ' '.join(inc) }
        url = cls.url() + id + '?' + urllib.urlencode(fields)
        doc = xmlHttpRequest(url)
        return elementField(doc.documentElement, cls.type)

    @classmethod
    def searchElements(cls, **fields):
        time.sleep(1)
        for key in fields:
            fields[key] = fields[key].encode('utf-8')
        fields['type'] = 'xml'
        url = cls.url() + '?' + urllib.urlencode(fields)
        doc = xmlHttpRequest(url)
        return doc.getElementsByTagNameNS(mbns, cls.type)

class Artist(Resource):
    type = 'artist'
    def __init__(self, id=None, elt=None):
        if elt == None:
            elt = self.getElement(id)
        self.score = elt.getAttributeNS(extns, 'score')
        self.id = elt.getAttribute('id')
        self.name = elementFieldValue(elt, 'name')
        self.sortname = elementFieldValue(elt, 'sort-name')
        self.disambiguation = elementFieldValue(elt, 'disambiguation')

    def releaseGroups(self):
        return ReleaseGroup.search(artistid=self.id)

    @classmethod
    def search(cls, **fields):
        artists = cls.searchElements(**fields)
        return [Artist(elt=elt) for elt in artists]

class ReleaseGroup(Resource):
    type = 'release-group'
    def __init__(self, id=None, elt=None):
        if elt == None:
            elt = self.getElement(id, 'artist')
        self.score = elt.getAttributeNS(extns, 'score')
        self.id = elt.getAttribute('id')
        self.type = elt.getAttribute('type')
        self.artist = Artist(elt=elementField(elt, 'artist'))
        self.title = elementFieldValue(elt, 'title')

    @classmethod
    def search(cls, **fields):
        rgs = cls.searchElements(**fields)
        return [ReleaseGroup(elt=elt) for elt in rgs]

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


