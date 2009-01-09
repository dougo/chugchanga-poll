# Copyright 2009 Doug Orleans.  Distributed under the GNU Affero
# General Public License v3.  See COPYING for details.

import os
import cgi
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

# Globals is a singleton class whose instance hold global values.
class Globals(db.Model):
    # Users must enter the secret word before they become Voters.
    secretWord = db.StringProperty()

def secretWord():
    globals = Globals.all().get()
    return globals.secretWord if globals else None

# Each Year object signifies whether voting is still open for that year.
class Year(db.Model):
    year = db.IntegerProperty(required=True)
    votingIsOpen = db.BooleanProperty(default=True)

class Voter(db.Model):
    user = db.UserProperty(required=True)
    year = db.IntegerProperty() # the year currently being edited

class Ballot(db.Model):
    voter = db.ReferenceProperty(Voter, required=True)
    year = db.IntegerProperty(required=True)
    anonymous = db.BooleanProperty(default=False)
    preamble = db.TextProperty(default='')
    postamble = db.TextProperty(default='')

class Vote(db.Model):
    ballot = db.ReferenceProperty(Ballot, required=True)
    rank = db.IntegerProperty(required=True)
    artist = db.StringProperty(default='')
    release = db.StringProperty(default='')
    comments = db.TextProperty(default='')

class MainPage(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        logout = users.create_logout_url(self.request.uri)

        voter = Voter.gql("WHERE user = :1", user).get()
        if not voter:
            # User hasn't entered the secret word, show him the front page.
            self.frontPage(user, logout)
            return

        years = map(lambda y: y.year,
                    Year.gql("WHERE votingIsOpen = True ORDER BY year"))
        if not years:
            self.closedPage(user, logout)
            return
        defaultYear = max(years)
        year = int(self.request.get('year') or voter.year or defaultYear)
        if year not in years:
            year = defaultYear
        if voter.year != year:
            voter.year = year
            voter.put()

        ballot = Ballot.gql("WHERE voter = :1 and year = :2", voter, year).get()
        if not ballot:
            ballot = Ballot(voter=voter, year=year)
            ballot.put()
            for rank in range(1, 21):
                vote = Vote(ballot=ballot, rank=rank)
                vote.put()

        if self.request.method == 'POST':
            ballot.anonymous = (self.request.get('anonymous') == 'on')
            ballot.preamble = self.request.get('preamble')
            ballot.postamble = self.request.get('postamble')
            ballot.put()
            for rank in range(1, 21):
                vote = Vote.gql("WHERE ballot = :1 and rank = :2",
                                ballot, rank).get()
                vote.artist = self.request.get('artist%d' % rank)
                vote.release = self.request.get('release%d' % rank)
                vote.comments = self.request.get('comments%d' % rank)
                vote.put()
            self.redirect(self.request.uri)
            return

        path = os.path.join(os.path.dirname(__file__), 'main.html')
        votes = ballot.vote_set
        votes.order('rank')
        years.remove(year)
        template_values = {
            'user': user,
            'admin': users.is_current_user_admin(),
            'logout': logout,
            'year': year,
            'other_years': years,
            'ballot': ballot,
            'votes': votes
            }
        self.response.out.write(template.render(path, template_values))

    def post(self):
        return self.get()

    def frontPage(self, user, logout):
        secret = self.request.get('secret')
        if secret == secretWord():
            Voter(user=user).put()
            self.redirect(self.request.uri)
            return
        path = os.path.join(os.path.dirname(__file__), 'front.html')
        template_values = {
            'user': user,
            'admin': users.is_current_user_admin(),
            'secret': secret,
            'logout': logout
            }
        self.response.out.write(template.render(path, template_values))

    def closedPage(self, user, logout):
        path = os.path.join(os.path.dirname(__file__), 'closed.html')
        template_values = {
            'user': user,
            'admin': users.is_current_user_admin(),
            'logout': logout
            }
        self.response.out.write(template.render(path, template_values))

class AdminPage(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        logout = users.create_logout_url(self.request.uri)
        secret = secretWord()
        years = Year.all()
        years.order('-year')
        path = os.path.join(os.path.dirname(__file__), 'admin.html')
        template_values = {
            'user': user,
            'secret': secret,
            'years': years,
            'logout': logout
            }
        self.response.out.write(template.render(path, template_values))
        
    def post(self):
        globals = Globals.all().get() or Globals()
        globals.secretWord = self.request.get('secret')
        globals.put()
        for y in Year.all():
            y.votingIsOpen = (self.request.get('year' + str(y.year)) == 'on')
            y.put()
        addYear = self.request.get('addYear')
        if addYear:
            Year(year=int(addYear)).put()
            self.redirect('.')
        else:
            self.redirect('/')


application = webapp.WSGIApplication([('/', MainPage),
                                      ('/admin/', AdminPage)],
                                     debug=True)

def main():
    run_wsgi_app(application)
