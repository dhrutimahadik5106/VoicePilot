# VoicePilot command seed v1

This is an 80-row synthetic development/test seed, not a research training
dataset or evidence of real-world accuracy. No human recording was fabricated,
collected, transcribed or inspected in Phase 3B. All rows are synthetic_text.
Language coverage is illustrative English, Hindi, Marathi and mixed-language
text, not a validated linguistic corpus. Multilingual phrasing needs native
speaker review before any research use.

## Schema and provenance

schema-v1.json is exported from DatasetRow in app/commands/models.py. Each row
requires schema_version=1.0, unique command_id, language, input_transcript,
canonical_intent (or null for unsupported/negated/compound input), entities,
canonical_command, variation_type, expected_confirmation_requirement and
source_type. Optional anonymous_speaker_id, noise_condition and consent_reference
are null for synthetic text. Empty entity dictionaries/null canonical commands
can label incomplete or unresolved entities. A typo with a known intended entity
can retain that entity as its annotation even when the resolver abstains.

The twelve labels describe proposed application/media/volume/help intents, not
implemented actions. Current code cannot open applications or control media.
Entities are a small closed vocabulary. Unknown applications/titles must not be
silently substituted. Similar-name and shared-alias cases require confirmation.

aliases-v1.json and intents-v1.json were independently defined before seed rows.
The resolver never loads seed examples. Vocabulary entries are entity names and
documented aliases, not a lookup table copied from every seed sentence. Shared
shorthand such as browser or taare is deliberately ambiguous. Tharism Infer is
traceable to the user's reported ASR error for Taare Zameen Par; it is not a
pronunciation. Even an exact observed-error match requires explicit confirmation.
The synthetic row containing it is not a claim of a human recording.

The seed includes supported patterns, unsupported paraphrases and challenging
negatives. Do not repeatedly tune patterns against seed metrics merely to reach
100%. Report misses and use genuinely independent data for future assessment.
No split or training claim is made for this small development seed.

## Interpretation and score policy

raw_transcript is the exact input Python string. normalized_transcript applies
NFC, case-folding, punctuation-to-space (except apostrophes), and whitespace
collapse for matching; Indic combining marks are preserved. Assistant invocation
and polite prefixes are parsed separately. canonical_command is a separate,
visible proposal. None of these proposals can execute.

Scores are heuristic match scores, not probabilities, calibrated confidence,
STT confidence or authorization. Canonical entity hits score 1.0, ordinary
aliases 0.98, observed ASR errors 0.75. Fuzzy suggestions use SequenceMatcher
ratio times 0.85. Defaults: acceptance threshold 0.95, suggestion threshold 0.65,
ambiguity margin 0.08, at most five candidates. Fuzzy matches never become
resolved even if thresholds change. Shorthand/observed-error metadata cannot
disable confirmation. Multiple exact candidates never pick an arbitrary winner.
Exact vocabulary hits take priority over fuzzy suggestions; the margin handles
fuzzy ties. Unknown entities and missing slots remain unset.

Negation, coordination and multiline command lists are conservatively rejected.
The guard covers documented markers, not every grammatical construction.
Patterns must match the entire remaining command. This can reject legitimate
titles containing coordination/negation words and unsupported paraphrases.
This deliberate abstention is not language understanding or a safety guarantee
for future executors. There is no confirmation/execution handler in this phase.

## Evaluation definitions

Every metric contains numerator, denominator and percentage (null if denominator
is zero), plus source/language/variation counts. Evaluation writes no history.

- Intent accuracy: exact predicted intent, including null, / all rows.
- Exact entity accuracy: exact whole entity dictionary / all rows.
- Canonical-command accuracy: exact proposed command, including null, / all rows.
- Confirmation rate: confirmation-required results / all rows.
- Acceptance coverage: resolved interpretations without confirmation / all rows.
- False-accept rate: accepted rows despite incorrect intent/entities/command,
  unknown ground truth, or expected confirmation / the union of rows requiring
  confirmation, labeled unknown, or interpreted incorrectly.
- False accepts among accepted: same numerator / accepted rows.

Here acceptance means interpretation acceptance only, never execution permission.
The additional denominator makes the false-accept definition explicit rather
than hiding it behind coverage. Correct abstentions on null labels count as
correct; many intents need no entities, which can inflate entity accuracy.
These seed metrics measure command resolution, not raw ASR WER/CER, pronunciation,
accent robustness, acoustic noise tolerance or end-to-end task success.
No real-world/generalization, publication or benchmark claim follows from them.

## Future consented audio policy (not implemented)

Obtain separate, informed opt-in before recording, storing, labeling, sharing or
reusing speech. Explain purpose, retention, access, withdrawal and publication
scope. Consent to microphone testing does not authorize dataset collection or
speaker enrollment. Never infer consent from participation or a transcript.

Use random speaker pseudonyms matching spk_<16 hex characters>. Store the identity
mapping and consent receipts separately in restricted storage, outside Git.
A consented_recording metadata row must include a pseudonym and an opaque consent
reference; optional noise labels must reflect observed conditions. Do not invent
speaker demographics, noise, recordings or consent metadata. Voices can identify
people: pseudonymization alone is not anonymization. Redact names, accounts,
locations and other personal content as appropriate and review before release.

Remove identifying filenames and unnecessary metadata. Minimize raw-audio access
and retention; document deletion/withdrawal propagation to derived datasets.
recordings/, models/ and data/commands/private/ are ignored, not encrypted or
access-controlled by Git. Do not store actual receipts/identity mappings there
merely because a path is ignored. No private-data directory is created here.

Future train/validation/test assignment must be speaker-disjoint. Group every
recording, transcript, noise augmentation and derivative from a speaker into the
same split; deduplicate recordings across splits. Lock test speakers before rule
tuning. Never create row-random audio splits or move speaker variants across
splits. Keep synthetic development data separate and disclose all provenance.

## Manual-validation refinement: Spotify play workflow

Only the full English form open <exact Spotify alias> and play <media> is treated
as one play_media proposal. Optional recognized assistant address prefixes are
context. Other coordinators/actions, negation, shell separators and unknown/fuzzy
application names remain blocked. Missing/unknown media remains unresolved.
No proposal is executed. The normalized matching view of this workflow is
play <media>; raw input is unchanged and no alias text is substituted into it.

The user-observed prefix Play VoicePilot is recognized only before this complete
workflow and requires confirmation as observed_address_form. Tharism Infer
continues to carry observed_asr_error provenance and requires confirmation.

Punctuation already became spaces, so reported punctuation-related token joining
was not reproduced in the inspected code. Zero-width space/BOM separators now
also become spaces; ordinary word boundaries are preserved. The CLI/resolver
returns the exact string received, including already joined TaareZameen.
Upstream STT concatenates raw segment text without inserted spaces and could
produce that boundary across segments. Without original arguments/segments,
application-versus-terminal-copy provenance cannot be determined. No raw STT
text is rewritten by this fix.

One seed annotation, open Spotify and play Taare Zameen Par, changes from rejected
compound to the newly approved play_media workflow. No other labels, aliases,
thresholds or unrelated rules were tuned. Metrics before/after therefore include
this disclosed specification change; they remain synthetic development metrics.
