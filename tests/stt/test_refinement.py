import pytest
from threading import Event

from app.core.config import Settings
from app.stt.models import TranscriptSegment
from app.stt.output_safety import apply_output_safety
from app.stt.refinement import RULES, refine
from tests.evaluation import result, SECRET
from tests.stt import isolated_stt


@pytest.mark.parametrize('language', ['hi', 'mr'])
@pytest.mark.parametrize('text', list(RULES))
def test_shadow_proposal_raw_preservation_evidence_idempotence(language, text):
    original = result(' ' + text + ' ', language)
    shadow = refine(original)
    assert original.raw_transcript == shadow.raw_transcript == ' ' + text + ' '
    assert shadow.normalized_transcript == text
    assert shadow.refined_transcript == RULES[text][0] and shadow.requires_confirmation
    change = shadow.changes[0]
    assert (change.start, change.end) == (0, len(text))
    assert change.alternatives == (text, RULES[text][0])
    assert change.rule_id and shadow.rule_set_version and shadow.source_view == 'normalized_transcript'
    assert refine(result(shadow.refined_transcript, language)).changes == ()


def test_unicode_segments_not_rewritten():
    segments = (TranscriptSegment(text='\u0915\u0943\u0020', start=0, end=.2), TranscriptSegment(text='\u092a\u092f\u093e', start=.2, end=.5))
    original = result(language='hi', segments=segments)
    before = original.model_dump_json()
    shadow = refine(original)
    assert shadow.raw_transcript == '\u0915\u0943\u0020\u092a\u092f\u093e'
    assert original.model_dump_json() == before


@pytest.mark.parametrize('text', [
    'Fableperson', '42', '2026-10-01', 'https://fictional.invalid/a', 'person@example.invalid',
    'Spotify', 'Chrome Beta', "do not stop", '\u092e\u0924\u0020\u0930\u094b\u0915\u094b',
    '\u0928\u0915\u094b', '\u0915\u0943\u0020\u092a\u092f\u093e' + ' Spotify', 'Fableperson ' + '\u0915\u0943\u0020\u092a\u092f\u093e',
    '\u0915\u093f', '\u0915\u0940', '\u0915\u093c', '\u0915', SECRET,
])
def test_protected_or_unknown_text_abstains(text):
    shadow = refine(result(text, 'hi'))
    assert shadow.changes == () and shadow.refined_transcript is None
    assert shadow.raw_transcript == text


def test_wrong_language_and_non_success_excluded():
    text = next(iter(RULES))
    assert refine(result(text, 'en')).changes == ()
    checked = apply_output_safety(result('stop ' * 8), Settings())
    assert checked.status == 'unusable_audio'
    assert refine(checked).raw_transcript == '' and refine(checked).changes == ()
    cancel = Event(); cancel.set()
    cancelled = apply_output_safety(result(text, 'hi'), Settings(), cancel)
    assert refine(cancelled).raw_transcript == ''


def test_default_serialization_and_repr_hide_text():
    shadow = refine(result(SECRET))
    assert SECRET not in repr(shadow) + shadow.model_dump_json()
    assert shadow.inspection()['raw_transcript'] == SECRET
