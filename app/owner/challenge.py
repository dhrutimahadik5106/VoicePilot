"""Single-use random public phrases: replay friction, never strong liveness."""
import secrets
import re
from time import monotonic
from uuid import UUID
from app.owner.models import Challenge, OwnerError

PHRASES = (
    "A blue notebook rests beside the quiet garden window",
    "Seven bright flowers grow near the little wooden gate",
    "The morning clouds move slowly over the green hill",
    "A silver bicycle stands beside the tall garden wall",
    "Three small boats float across the peaceful blue lake",
    "The yellow lantern shines beside the open kitchen door",
    "A gentle breeze moves the leaves above the empty bench",
    "Five red birds gather near the stone water fountain",
    "The little clock stands beside a clean glass bowl",
    "A green umbrella rests near the quiet station entrance",
    "Four white clouds drift beyond the distant mountain peak",
    "The orange basket holds several fresh apples and pears",
)


def words(text):
    if type(text) is not str or len(text) > 300:
        raise OwnerError("phrase_mismatch")
    return re.sub(r"[.,!?]", "", text.casefold()).split()


class Challenges:
    def __init__(self, cfg, *, clock=monotonic, choose=secrets.choice):
        self.cfg, self.clock, self.choose = cfg, clock, choose
        self.pending = {}

    def create(self, session):
        if type(session) is not UUID or len(self.pending) >= 128:
            raise OwnerError()
        challenge = Challenge(phrase=self.choose(PHRASES))
        self.pending[challenge.handle] = (challenge, session, self.clock() + self.cfg.challenge_expiry)
        return challenge

    def consume(self, challenge, session):
        if type(challenge) is not Challenge:
            raise OwnerError("challenge_replayed")
        row = self.pending.pop(challenge.handle, None)
        if row is None:
            raise OwnerError("challenge_replayed")
        if self.clock() >= row[2]:
            raise OwnerError("challenge_expired")
        if row[0] != challenge or row[1] != session:
            raise OwnerError("binding_mismatch")
        return row[0].phrase

    def verify(self, expected, transcript):
        if words(expected) != words(transcript):
            raise OwnerError("phrase_mismatch")
