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

class Voter(db.Model):
    user = db.UserProperty(required=True)
    name = db.StringProperty(required=True)
    url = db.StringProperty(default='')
    year = db.IntegerProperty() # the year currently being edited
    wantsPlain = db.BooleanProperty() # voter prefers plain HTML to Javascript

class Ballot(db.Model):
    voter = db.ReferenceProperty(Voter, required=True)
    year = db.IntegerProperty(required=True)
    anonymous = db.BooleanProperty(default=False)
    preamble = db.TextProperty(default='')
    postamble = db.TextProperty(default='')

class Vote(db.Model):
    ballot = db.ReferenceProperty(Ballot, required=True)
    category = db.StringProperty(default='vote') # vote, mention, or note
    rank = db.IntegerProperty(required=True) # 1-based rank within category
    artist = db.StringProperty(default='')
    release = db.StringProperty(default='')
    comments = db.TextProperty(default='')

class VoterPage(webapp.RequestHandler):
    def validate(self):
        user = users.get_current_user()
        self.logout = users.create_logout_url(self.request.uri)

        self.voter = Voter.gql("WHERE user = :1", user).get()
        if not self.voter:
            # User hasn't entered the secret word.
            return 'invalid'

        self.years = map(lambda y: y.year,
                         Year.gql("WHERE votingIsOpen = True ORDER BY year"))
        if not self.years:
            # No polls are open.
            return 'closed'
        defaultYear = max(self.years)
        self.year = int(self.request.get('year') or self.voter.year
                        or defaultYear)
        if self.year not in self.years:
            self.year = defaultYear
        if self.voter.year != self.year:
            self.voter.year = self.year
            self.voter.put()

        self.ballot = Ballot.gql("WHERE voter = :1 and year = :2",
                                 self.voter, self.year).get()
        return None

class MainPage(VoterPage):
    def validate(self):
        status = VoterPage.validate(self)
        if status == 'invalid':
            self.frontPage()
            return False
        if status == 'closed':
            self.closedPage()
            return False
        return True

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
            for rank in range(1, 21):
                vote = Vote(parent=self.ballot, ballot=self.ballot, rank=rank)
                vote.put()

        votes = dict()
        for category in ['vote', 'mention', 'note']:
            votes[category] = Vote.gql("WHERE ballot = :1 AND category = :2"
                                       " ORDER BY rank", self.ballot, category)

        path = os.path.join(os.path.dirname(__file__), 'main.html')
        self.years.remove(self.year)
        template_values = {
            'admin': users.is_current_user_admin(),
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
            self.redirect(self.request.uri + "#" + addCat)
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
        ballot.put()

        numVotes = dict()
        for cat in ['vote', 'mention', 'note']:
            numVotes[cat] = int(self.request.get(cat + 's'))
            for rank in range(1, numVotes[cat]+1):
                vote = Vote(parent=ballot, ballot=ballot,
                            category=cat, rank=rank)
                vote.artist = self.request.get('%s%dartist' % (cat, rank))
                vote.release = self.request.get('%s%drelease' % (cat, rank))
                vote.comments = self.request.get('%s%dcomments' % (cat, rank))
                vote.put()

        if addCat:
            # Add ten more votes in the requested category.
            for rank in range(numVotes[addCat]+1, numVotes[addCat]+11):
                Vote(parent=ballot, ballot=ballot,
                     category=addCat, rank=rank).put()

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
            'admin': users.is_current_user_admin(),
            'name': name,
            'secret': secret,
            'logout': self.logout
            }
        self.response.out.write(template.render(path, template_values))

    def closedPage(self):
        path = os.path.join(os.path.dirname(__file__), 'closed.html')
        template_values = {
            'voter': self.voter,
            'admin': users.is_current_user_admin(),
            'logout': self.logout
            }
        self.response.out.write(template.render(path, template_values))

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
        
class AjaxHandler(VoterPage):
    def post(self):
        status = self.validate()
        if status:
            self.response.out.write(status)
            return

        name = self.request.get('name')
        value = self.request.get('value')
        if name == 'anonymous':
            self.ballot.anonymous = (value == 'on')
            self.ballot.put()

        if name == 'preamble':
            self.ballot.preamble = value
            self.ballot.put()

        if name == 'postamble':
            self.ballot.postamble = value
            self.ballot.put()


application = webapp.WSGIApplication([('/', MainPage),
                                      ('/profile/', ProfilePage),
                                      ('/admin/', AdminPage),
                                      ('/ajax/', AjaxHandler),
                                      ], debug=True)

def main():
    run_wsgi_app(application)
