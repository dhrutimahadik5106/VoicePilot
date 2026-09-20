"""Single-use random public phrases: replay friction, never strong liveness."""
import secrets
import re
import unicodedata
from hashlib import sha256
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


NORMALIZATION_VERSION = "owner-phrase-normalization-v1"
# Pin exact public corpus bytes/order for owner-phrases-v1. This is a regression
# identifier, not authentication; no protected calibration binding is changed.
CORPUS_SHA256 = "0b48cf8679754cd3e9506744e33316365737634d88fb5b7dba9e7455f98e7f84"


def normalize_phrase(text):
    """Canonical comparison only; never rewrite raw STT or infer missing words."""
    if type(text) is not str or not 0 < len(text) <= 300:
        raise OwnerError("phrase_mismatch")
    text = unicodedata.normalize("NFC", text)
    if any(unicodedata.category(char).startswith("C") and char not in "\t\r\n"
           for char in text):
        raise OwnerError("phrase_mismatch")
    text = unicodedata.normalize("NFC", text.casefold())
    text = " ".join(text.split()).rstrip(".,!?;:").rstrip()
    if not text:
        raise OwnerError("phrase_mismatch")
    return text


def validate_corpus(phrases=PHRASES):
    """Pure import-safe validation; reject whitespace, fused words and corpus drift."""
    if type(phrases) is not tuple or len(phrases) != 12:
        raise OwnerError("phrase_mismatch")
    for phrase in phrases:
        if (type(phrase) is not str or len(phrase) > 120
                or re.fullmatch(r"[A-Z][a-z]*(?: [a-z]+){7,11}", phrase) is None):
            raise OwnerError("phrase_mismatch")
    if len({normalize_phrase(phrase) for phrase in phrases}) != len(phrases):
        raise OwnerError("phrase_mismatch")
    if sha256("\n".join(phrases).encode("ascii")).hexdigest() != CORPUS_SHA256:
        raise OwnerError("phrase_mismatch")


validate_corpus()


class Challenges:
    def __init__(self, cfg, *, clock=monotonic, choose=secrets.choice):
        validate_corpus(PHRASES)
        self.cfg, self.clock, self.choose = cfg, clock, choose
        self.pending = {}

    def create(self, session, *, present=None):
        if type(session) is not UUID or len(self.pending) >= 128:
            raise OwnerError()
        challenge = Challenge(phrase=self.choose(PHRASES))
        # Presentation is synchronous. Consent precedes this call; the deadline
        # starts only after the selected phrase has been displayed successfully.
        if present is not None:
            present(challenge.phrase)
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
        if expected not in PHRASES or normalize_phrase(expected) != normalize_phrase(transcript):
            raise OwnerError("phrase_mismatch")
