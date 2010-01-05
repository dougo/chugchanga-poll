# Copyright 2009 Doug Orleans.  Distributed under the GNU Affero
# General Public License v3.  See COPYING for details.

import itertools
import collections
from xml.sax.saxutils import escape
from google.appengine.ext import db
import musicbrainz
mb = musicbrainz

# Globals is a singleton class whose instance hold global values.
class Globals(db.Model):
    # Users must enter the secret word before they become Voters.
    secretWord = db.StringProperty()

    @classmethod
    def checkSecretWord(cls, word):
        globals = cls.all().get()
        secret = globals.secretWord if globals else None
        return word == secret

# Each Year object signifies whether voting is still open for that year.
class Year(db.Model):
    year = db.IntegerProperty(required=True)
    votingIsOpen = db.BooleanProperty(default=True)

    # Returns the Year object for a given year.
    @classmethod
    def get(cls, year):
        return cls.gql('WHERE year = :1', int(year)).get()

    # Returns a Query for all ballots for this year.
    def ballots(self):
        return Ballot.gql('WHERE year = :1', self.year)

    # Returns an iterator for all non-empty ballots for this year.
    def nonEmptyBallots(self):
        return itertools.ifilterfalse(Ballot.isEmpty, self.ballots())

    # Returns a list of tuples of releases and dicts mapping categories to
    # lists of votes.
    def countVotes(self):
        count = collections.defaultdict(lambda: collections.defaultdict(list))
        for b in self.ballots():
            for c, vs in b.getVotesDict().iteritems():
                for v in vs:
                    if v.release:
                        count[v.release][c].append(v)
        return count.items()

    def rankReleases(self):
        def key(item):
            return len(item[1]['favorite']), len(item[1]['honorable'])
        rank = 1
        votes = sorted(self.countVotes(), key=key, reverse=True)
        for k, g in itertools.groupby(votes, key):
            nextRank = rank
            for item in g:
                rr = RankedRelease.gql('WHERE year = :1 AND release = :2',
                                       self.year, item[0]).get()
                if rr:
                    rr.rank = rank
                else:
                    rr = RankedRelease(year=self.year, release=item[0],
                                       rank=rank)
                rr.put()
                nextRank += 1
            rank = nextRank

    def byVotes(self):
        return RankedRelease.gql('WHERE year = :1 ORDER BY rank', self.year)

    def byArtist(self):
        return sorted(RankedRelease.gql('WHERE year = :1', self.year),
                      key=lambda rr: (rr.release.artist.sortname.lower(),
                                      rr.release.title.lower()))

class RankedRelease(db.Model):
    year = db.IntegerProperty(required=True)
    rank = db.IntegerProperty(required=True)
    release = db.ReferenceProperty(required=True)

    def link(self):
        return self.release.link()
    def votes(self, category):
        # TO DO: cache these as db.ListProperty(db.Key)?
        # TO DO: sort by voter name
        return [v for v in Vote.gql('WHERE release = :1 AND category = :2',
                                    self.release, category)
                if v.ballot.year == self.year]
    def favorite(self):
        return self.votes('favorite')
    def honorable(self):
        return self.votes('honorable')
    def notable(self):
        return self.votes('notable')

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
    honorable = db.IntegerProperty(default=0)
    notable = db.IntegerProperty(default=0)

    def name(self):
        if self.anonymous:
            return 'Anonymous Chugchanga-L Member #' + str(self.key().id())
        return self.voter.name

    categories = ['favorite', 'honorable', 'notable']

    # Returns True iff the ballot has no votes.
    def isEmpty(self):
        return self.vote_set.count() == 0

    # Returns the ballot's vote with the given category and rank.  If
    # there is no such vote, a new Vote is returned.  The new Vote is
    # *not* stored in the database.
    def getVote(self, category, rank):
        vote = Vote.gql('WHERE ballot = :1 AND category = :2 AND rank = :3',
                        self, category, rank).get()
        if vote:
            return vote
        return Vote(parent=self, ballot=self,
                    category=category, rank=rank)

    # Returns the highest rank of the ballot's votes in the given
    # category, or zero if there are none.
    def maxRank(self, category):
        if category == 'favorite':
            return 20
        if category == 'honorable':
            return self.honorable
        if category == 'notable':
            return self.notable

    # Returns an iterable of the ballot's votes in the given category,
    # in ascending order by rank.
    def getVotes(self, category):
        return Vote.gql('WHERE ballot = :1 AND category = :2 ORDER BY rank',
                        self, category)

    # Returns a dict mapping categories to iterables of the ballot's
    # votes for that category.
    def getVotesDict(self):
        votes = dict()
        for category in self.categories:
            votes[category] = self.getVotes(category)
        return votes

class Artist(db.Model):
    name = db.StringProperty(required=True)
    sortname = db.StringProperty(required=True)
    mbid = db.StringProperty()  # MusicBrainz identifier
    url = db.LinkProperty()     # other URL, if not in MusicBrainz

    def releases(self):
        return Release.gql('WHERE artist = :1 ORDER BY title', self)

    @staticmethod
    def get(mbid):
        artist = Artist.gql('WHERE mbid = :1', mbid).get()
        if not artist:
            mbArtist = mb.Artist(mbid)
            artist = Artist(name=mbArtist.name,
                            sortname=mbArtist.sortname,
                            mbid=mbid)
            artist.put()
        return artist

class Release(db.Model):
    artist = db.ReferenceProperty(Artist, required=True)
    title = db.StringProperty(required=True)
    mbid = db.StringProperty()
    url = db.LinkProperty()

    def markup(self):
        return '<strong>%s</strong>, <cite>%s</cite>' % (self.artist.name,
                                                         self.title)

    def local(self):
        return '/artist/%d#%d' % (self.artist.key().id(), self.key().id())

    def link(self):
        return '<a href="%s">%s</a>' % (self.local(), self.markup())

    def __hash__(self):
        return self.key().__hash__()
    def __eq__(self, r):
        return self.key() == r.key()

    def votes(self):
        votes = list(self.vote_set)
        votes.sort(key=lambda v: (v.ballot.year, v.category, v.ballot.name()))
        return votes

    @staticmethod
    def get(mbid):
        release = Release.gql('WHERE mbid = :1', mbid).get()
        if not release:
            mbRelease = mb.ReleaseGroup(mbid)
            release = Release(artist=Artist.get(mbRelease.artist.id),
                              title=mbRelease.title,
                              mbid=mbRelease.id)
            release.put()
        return release

class Vote(db.Model):
    ballot = db.ReferenceProperty(Ballot, required=True)
    category = db.StringProperty(default=Ballot.categories[0])
    rank = db.IntegerProperty(required=True) # 1-based rank within category
    release = db.ReferenceProperty(Release)
    artist = db.StringProperty(default='')
    title = db.StringProperty(default='')
    comments = db.TextProperty(default='')

    def toDict(self):
        return { 'rank': self.rank,
                 'artist': escape(self.artist),
                 'title': escape(self.title),
                 'comments': escape(self.comments) }

    def url(self):
        return '/ballot/%d#%s-%d' % (self.ballot.key().id(),
                                     self.category, self.rank)

    def link(self):
        return '<a href="%s">%s</a>' % (self.url(), self.ballot.name())
