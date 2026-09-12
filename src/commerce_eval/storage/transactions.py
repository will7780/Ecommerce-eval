"""Bind existing repository operations to one caller-owned transaction."""

from contextlib import contextmanager


class BoundSessions:
    def __init__(self, session):
        self.session = session

    @contextmanager
    def __call__(self):
        self.session.flush()
        yield self.session

    @contextmanager
    def begin(self):
        yield self.session
        self.session.flush()


class BoundDatabase:
    def __init__(self, database, session):
        self.path = database.path
        self.engine = database.engine
        self.sessions = BoundSessions(session)
