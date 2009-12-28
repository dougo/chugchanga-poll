# Copyright 2009 Doug Orleans.  Distributed under the GNU Affero
# General Public License v3.  See COPYING for details.

import os
import itertools
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from django.utils import simplejson
from models import Voter, Year, Ballot, Vote, Release, Artist, Globals
import musicbrainz
mb = musicbrainz

class Page(webapp.RequestHandler):
    def render(self, template_file, **template_values):
        path = os.path.join(os.path.dirname(__file__), template_file)
        self.response.out.write(template.render(path, template_values))

# Base class for voter pages.
class VoterPage(Page):
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
        self.render('profile.html', voter=self.voter, logout=self.logout)
        
    def post(self):
        if self.validate():
            return
        self.voter.name = self.request.get('name') or self.voter.user.nickname()
        self.voter.url = self.request.get('url')
        self.voter.put()
        self.redirect('..')
        
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
        if Globals.checkSecretWord(secret):
            Voter(user=user, name=name or user.nickname()).put()
            self.redirect(self.request.uri)
            return
        self.render('front.html', user=user, name=name, secret=secret,
                    logout=self.logout)

    def closedPage(self):
        self.render('closed.html', voter=self.voter, logout=self.logout)

    def get(self):
        if not self.validate():
            return

        view = self.request.get('view')
        if view:
            self.voter.wantsPlain = (view == 'plain')
            self.voter.put()

        if not self.ballot:
            self.ballot = Ballot(voter=self.voter, year=self.year)
            self.ballot.put()

        votes = dict()
        if self.voter.wantsPlain:
            # Fill in gaps in the ranking with blank Votes.
            for category in Ballot.categories:
                if category == Ballot.categories[0]:
                    max = 20
                else:
                    max = self.ballot.maxRank(category)
                votes[category] = [self.ballot.getVote(category, rank)
                                   for rank in range(1, max+1)]
        else:
            for category in Ballot.categories:
                votes[category] = [vote.toDict()
                                   for vote in self.ballot.getVotes(category)]
            votes = simplejson.dumps(votes, indent=4)

        self.years.remove(self.year)
        self.render('main.html', logout=self.logout, year=self.year,
                    other_years=self.years, ballot=self.ballot, votes=votes)

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
        # Delete the old votes and replace them with the request data.
        # This avoids cases where the form data doesn't match the
        # current database (e.g. from the back button or a cloned
        # window).
        if self.ballot:
            db.delete(votes)
            ballot = self.ballot
        else:
            ballot = Ballot(voter=self.voter, year=self.year)

        ballot.anonymous = bool(self.request.get('anonymous'))
        ballot.preamble = self.request.get('preamble')
        ballot.postamble = self.request.get('postamble')
        numVotes = dict()
        for cat in Ballot.categories:
            numVotes[cat] = int(self.request.get(cat + 's'))
        ballot.honorable = numVotes['honorable']
        if addCat == 'honorable':
            ballot.honorable += 10
        ballot.notable = numVotes['notable']
        if addCat == 'notable':
            ballot.notable += 10
        ballot.put()

        for cat in Ballot.categories:
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

class ResultsPage(Page):
    def get(self):
        years = Year.gql('ORDER BY year DESC')
        ballots = [(y, list(y.nonEmptyBallots())) for y in years]
        self.render('results.html', ballots=ballots)

class BallotPage(Page):
    def get(self, id):
        ballot = Ballot.get_by_id(int(id))
        if not ballot:
            self.response.out.write('No such ballot: ' + id)
            return
        name = 'Anonymous Chugchanga Member #' + id \
            if ballot.anonymous else ballot.voter.name
        votes = ballot.getVotesDict()
        self.render('ballot.html', name=name, ballot=ballot, votes=votes)
        
class CanonIndexPage(Page):
    def get(self):
        uncanonicalized = Vote.gql('WHERE release = :1 ORDER BY artist', None)
        canonicalized = [(r, r.vote_set) for r in Release.all()]
        canonicalized.sort(key=lambda rv: rv[0].artist.sortname)
        self.render('cindex.html', uncanonicalized=uncanonicalized,
                    canonicalized=canonicalized)

class CanonPage(Page):
    @staticmethod
    def getVote(ballotID, voteID):
        ballotKey = db.Key.from_path(Ballot.kind(), int(ballotID))
        return Vote.get_by_id(int(voteID), ballotKey)

    def get(self, ballotID, voteID):
        vote = self.getVote(ballotID, voteID)
        if not vote:
            self.response.out.write('No such vote: ' + ballotID + '/' + voteID)
            return
        rgs = mb.ReleaseGroup.search(title=vote.title, artist=vote.artist)
        if not rgs:
            for artist in mb.Artist.search(name=vote.artist):
                rgs += artist.releaseGroups()
        self.render('canon.html', v=vote, releases=rgs)

    def post(self, ballotID, voteID):
        vote = self.getVote(ballotID, voteID)
        vote.release = Release.get(self.request.get('releaseid'))
        vote.put()
        self.redirect('..')
            
class BackupPage(Page):
    def get(self):
        self.response.headers['Content-Type'] = "text/xml"
        self.response.out.write('<?xml version="1.0" encoding="UTF-8"?>')
        self.response.out.write('<chugchanga-poll>')
        for model in [Globals, Year, Voter, Ballot, Vote, Release, Artist]:
            for obj in model.all():
                self.response.out.write(obj.to_xml())
        self.response.out.write('</chugchanga-poll>')
        

application = webapp.WSGIApplication([('/members/', MainPage),
                                      ('/members/profile/', ProfilePage),
                                      ('/members/ajax/', AjaxHandler),
                                      ('/', ResultsPage),
                                      ('/ballot/([0-9]+)/', BallotPage),
                                      ('/admin/canon/', CanonIndexPage),
                                      ('/admin/canon/([0-9]+)/([0-9]+)', CanonPage),
                                      ('/admin/backup', BackupPage),
                                      ], debug=True)

def main():
    run_wsgi_app(application)

if __name__ == '__main__':
    main()
