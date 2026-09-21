"""Explicit public transition table; terminal sessions cannot be reused."""
from types import MappingProxyType
from app.session.models import State as S, SessionError

TERMINAL = frozenset({S.COMPLETED,S.BLOCKED,S.CANCELLED,S.TIMED_OUT,S.FAILED,S.STOPPED})
_FORWARD = {
    S.IDLE:{S.READY}, S.READY:{S.ACTIVATION}, S.ACTIVATION:{S.LISTENING},
    S.LISTENING:{S.AUTHENTICATING}, S.AUTHENTICATING:{S.UNDERSTANDING},
    S.UNDERSTANDING:{S.CLARIFICATION,S.PLANNING}, S.CLARIFICATION:{S.PLANNING},
    S.PLANNING:{S.RISK}, S.RISK:{S.CONFIRMATION,S.AUTHORIZED},
    S.CONFIRMATION:{S.AUTHORIZED}, S.AUTHORIZED:{S.EXECUTING},
    S.EXECUTING:{S.OBSERVING}, S.OBSERVING:{S.VERIFYING},
    S.VERIFYING:{S.RESPONDING}, S.RESPONDING:{S.COMPLETED},
}
TRANSITIONS = MappingProxyType({state: frozenset() if state in TERMINAL else
    frozenset(_FORWARD[state] | (TERMINAL - {S.COMPLETED})) for state in S})


def transition(current, target):
    if type(current) is not S or type(target) is not S or target not in TRANSITIONS[current]:
        raise SessionError("invalid_transition")
    return target
