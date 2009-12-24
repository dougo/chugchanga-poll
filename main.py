# Copyright 2009 Doug Orleans.  Distributed under the GNU Affero
# General Public License v3.  See COPYING for details.

import os
import cgi
import itertools
import urllib
import urllib2
from xml.dom import minidom
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from django.utils import simplejson
from models import Voter, Year, Ballot, Vote, Release, Artist, secretWord, categories

# Base class for voter pages.
class VoterPage(webapp.RequestHandler):
    # Returns:
    #  'invalid': if the user has not entered the secret word
    #  'closed': if there are no poll years currently open
    #  None: otherwise
    # Sets instance variables:
    #  logout: URL
    #  voter: Voter
    #  years: list of Years (ints) whose polls are open
    #  year: year (int) currently being voted on by voter
    #  ballot: Ballot for current voter and year, or None
    def validate(self):
        user = users.get_current_user()
        self.logout = users.create_logout_url(self.request.uri)

        self.voter = Voter.gql('WHERE user = :1', user).get()
        if not self.voter:
            return 'invalid'

        self.years = map(lambda y: y.year,
                         Year.gql('WHERE votingIsOpen = True ORDER BY year'))
        if not self.years:
            return 'closed'
        defaultYear = max(self.years)
        self.year = int(self.request.get('year') or self.voter.year
                        or defaultYear)
        if self.year not in self.years:
            self.year = defaultYear
        if self.voter.year != self.year:
            self.voter.year = self.year
            self.voter.put()

        self.ballot = Ballot.gql('WHERE voter = :1 and year = :2',
                                 self.voter, self.year).get()
        return None

class ProfilePage(VoterPage):
    def get(self):
        if self.validate():
            return
        path = os.path.join(os.path.dirname(__file__), 'profile.html')
        template_values = {
            'voter': self.voter,
            'logout': self.logout,
            }
        self.response.out.write(template.render(path, template_values))
        
    def post(self):
        if self.validate():
            return
        self.voter.name = self.request.get('name') or self.voter.user.nickname()
        self.voter.url = self.request.get('url')
        self.voter.put()
        self.redirect('/')
        
class MainPage(VoterPage):
    # Returns:
    #  False: and displays the front page if the user hasn't entered
    #    the secret word, or the closed page if no polls are open
    #  True: otherwise
    def validate(self):
        status = VoterPage.validate(self)
        if status == 'invalid':
            self.frontPage()
            return False
        if status == 'closed':
            self.closedPage()
            return False
        return True

    def frontPage(self):
        user = users.get_current_user()
        secret = self.request.get('secret')
        name = self.request.get('name')
        if secret == secretWord():
            Voter(user=user, name=name or user.nickname()).put()
            self.redirect(self.request.uri)
            return
        path = os.path.join(os.path.dirname(__file__), 'front.html')
        template_values = {
            'user': user,
            'name': name,
            'secret': secret,
            'logout': self.logout
            }
        self.response.out.write(template.render(path, template_values))

    def closedPage(self):
        path = os.path.join(os.path.dirname(__file__), 'closed.html')
        template_values = {
            'voter': self.voter,
            'logout': self.logout
            }
        self.response.out.write(template.render(path, template_values))

    def get(self):
        if not self.validate():
            return

        view = self.request.get('view')
        if view:
            self.voter.wantsPlain = (view == 'plain')
            self.voter.put()

        if not self.ballot:
            self.ballot = Ballot(parent=self.voter, voter=self.voter,
                                 year=self.year)
            self.ballot.put()

        votes = dict()
        if self.voter.wantsPlain:
            # Fill in gaps in the ranking with blank Votes.
            for category in categories:
                if category == categories[0]:
                    max = 20
                else:
                    max = self.ballot.maxRank(category)
                votes[category] = [self.ballot.getVote(category, rank)
                                   for rank in range(1, max+1)]
        else:
            for category in categories:
                votes[category] = [vote.toDict()
                                   for vote in self.ballot.getVotes(category)]
            votes = simplejson.dumps(votes, indent=4)

        path = os.path.join(os.path.dirname(__file__), 'main.html')
        self.years.remove(self.year)
        template_values = {
            'logout': self.logout,
            'year': self.year,
            'other_years': self.years,
            'ballot': self.ballot,
            'votes': votes,
            }
        self.response.out.write(template.render(path, template_values))

    def post(self):
        if not self.validate():
            return

        votes = set(self.ballot.vote_set)
        addCat = self.request.get('add')
        db.run_in_transaction(self.update, votes, addCat)
        if addCat:
            self.redirect(self.request.uri + '#' + addCat)
        else:
            self.redirect(self.request.uri)

    def update(self, votes, addCat):
        # Delete the old ballot and votes and replace them with the
        # request data.  This avoids cases where the form data doesn't
        # match the current database (e.g. from the back button or a
        # cloned window).
        if self.ballot:
            db.delete(votes)
            self.ballot.delete()

        ballot = Ballot(parent=self.voter, voter=self.voter, year=self.year)
        if self.request.get('anonymous'):
            ballot.anonymous = True
        ballot.preamble = self.request.get('preamble')
        ballot.postamble = self.request.get('postamble')
        numVotes = dict()
        for cat in categories:
            numVotes[cat] = int(self.request.get(cat + 's'))
        ballot.honorable = numVotes['honorable']
        if addCat == 'honorable':
            ballot.honorable += 10
        ballot.notable = numVotes['notable']
        if addCat == 'notable':
            ballot.notable += 10
        ballot.put()

        for cat in categories:
            for rank in range(1, numVotes[cat]+1):
                artist = self.request.get('%s%dartist' % (cat, rank))
                title = self.request.get('%s%dtitle' % (cat, rank))
                comments = self.request.get('%s%dcomments' % (cat, rank))
                if artist or title or comments:
                    vote = Vote(parent=ballot, ballot=ballot,
                                category=cat, rank=rank,
                                artist=artist, title=title, comments=comments)
                    vote.put()

class AjaxHandler(VoterPage):
    def post(self):
        status = self.validate()
        if status:
            self.response.out.write(status)
            self.response.set_status(401) # Unauthorized
            return

        field = self.request.get('field')
        value = self.request.get('value')
        category = self.request.get('category')
        rank = self.request.get('rank')
        rank = int(rank) if rank else 0

        if category:
            vote = self.ballot.getVote(category, rank)
            if field == 'artist':
                vote.artist = value
            if field == 'title':
                vote.title = value
            if field == 'comments':
                vote.comments = value
            if vote.artist or vote.title or vote.comments:
                vote.put()
                if category == 'honorable' and rank > self.ballot.honorable:
                    self.ballot.honorable = rank
                    self.ballot.put()
                if category == 'notable' and rank > self.ballot.notable:
                    self.ballot.notable = rank
                    self.ballot.put()
            else:
                vote.delete()
        else:
            if field == 'anonymous':
                self.ballot.anonymous = (value == 'on')
            if field == 'preamble':
                self.ballot.preamble = value
            if field == 'postamble':
                self.ballot.postamble = value
            self.ballot.put()

class ResultsPage(webapp.RequestHandler):
    def get(self):
        path = os.path.join(os.path.dirname(__file__), 'results.html')
        years = Year.gql('ORDER BY year DESC')
        ballots = [(y, list(y.nonEmptyBallots())) for y in years]
        template_values = {
            'ballots': ballots,
            }
        self.response.out.write(template.render(path, template_values))

class BallotPage(webapp.RequestHandler):
    def get(self, key):
        path = os.path.join(os.path.dirname(__file__), 'ballot.html')
        ballot = Ballot.get(key)
        if not ballot:
            self.response.out.write('No such ballot: ' + key)
            return
        name = 'Anonymous Chugchanga Member #' + str(ballot.key().id()) \
            if ballot.anonymous else ballot.voter.name
        votes = ballot.getVotesDict()
        template_values = {
            'name': name,
            'ballot': ballot,
            'votes': votes
            }
        self.response.out.write(template.render(path, template_values))
        

mbns = 'http://musicbrainz.org/ns/mmd-1.0#'
extns = 'http://musicbrainz.org/ns/ext-1.0#'

class CanonIndexPage(webapp.RequestHandler):
    def get(self):
        path = os.path.join(os.path.dirname(__file__), 'cindex.html')
        uncanonicalized = Vote.gql('WHERE release = :1 ORDER BY artist', None)
        canonicalized = [r for r in Release.all()]
        canonicalized.sort(key=lambda r: r.artist.sortname)
        template_values = {
            'uncanonicalized': uncanonicalized,
            'canonicalized': canonicalized,
            }
        self.response.out.write(template.render(path, template_values))

class CanonPage(webapp.RequestHandler):
    def get(self, key):
        path = os.path.join(os.path.dirname(__file__), 'canon.html')
        vote = Vote.get(key);
        if vote:
            fields = { 'type': 'xml',
                       'title': vote.title,
                       'artist': vote.artist,
                       }
            url = 'http://musicbrainz.org/ws/1/release-group/?' \
                + urllib.urlencode(fields)
            result = urllib2.urlopen(url)
            doc = minidom.parse(result)
            releases = doc.getElementsByTagNameNS(mbns, 'release-group')
            releases = [releaseElementToDict(elt) for elt in releases]
            for i in range(len(releases)):
                releases[i]['index'] = i
            template_values = {
                'v': vote,
                'releases': releases,
                'doc': doc.toprettyxml(),
                }
        else:
            template_values = { }
        self.response.out.write(template.render(path, template_values))

    def post(self, key):
        r = self.request.get('release')
        release = \
            Release(artist=Artist.get(self.request.get('artistid' + r)),
                    title=self.request.get('title' + r),
                    mbid=self.request.get('releaseid' + r, default_value=None),
                    url=self.request.get('releaseurl' + r, default_value=None),
                    )
        release.put()
        vote = Vote.get(key);
        vote.release = release
        vote.put()
        self.redirect('/canon/');
            
def releaseElementToDict(elt):
    return {
        'score': elt.getAttributeNS(extns, 'score'),
        'mbid': elt.getAttribute('id'),
        'type': elt.getAttribute('type'),
        'artist': artistElementToDict(elementField(elt, 'artist')),
        'title': elementFieldValue(elt, 'title'),
        }

def artistElementToDict(elt):
    return {
        'mbid': elt.getAttribute('id'),
        'name': elementFieldValue(elt, 'name'),
        'sortname': elementFieldValue(elt, 'sortname'),
        }

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


application = webapp.WSGIApplication([('/', MainPage),
                                      ('/profile/', ProfilePage),
                                      ('/ajax/', AjaxHandler),
                                      ('/results/', ResultsPage),
                                      ('/ballot/([^/]+)/', BallotPage),
                                      ('/canon/', CanonIndexPage),
                                      ('/canon/([^/]+)', CanonPage),
                                      ], debug=True)

def main():
    run_wsgi_app(application)

if __name__ == '__main__':
    main()
