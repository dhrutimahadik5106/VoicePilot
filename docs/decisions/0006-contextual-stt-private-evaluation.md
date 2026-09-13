# 0006: Contextual STT and private evaluation foundation

Status: implemented foundation; no real accuracy experiment performed.

## Scope and evidence

Phase 3D established identical prepared inputs and STT results for one controlled
capture. This is not proof of general multilingual accuracy. Phase 3E separates
acoustic transcription, optional shadow refinement, and non-executing command
interpretation. No measured improvement, perfect transcription, linguistic corpus
validation, or research benchmark result is claimed.

Current personal-name hints were removed from tracked configuration, examples,
documentation and tests. No personal sentence or association was added. Older Git
commits may retain previous content. History removal needs separate approval and
was not attempted.

## Private data boundary

Preferred real-data root: `%LOCALAPPDATA%\VoicePilot\private-evaluation\`, outside
the repository and its OneDrive sync tree. Tools never create this root. The explicit
repository alternative `data/stt/private/` is ignored. Private manifest/overlay
suffixes, per-utterance reports and evaluation exports are also ignored. Git ignore
is neither encryption nor access control, and does not disable cloud synchronization.
No consent receipt, identity mapping, recording or real transcript is tracked.

A real manifest is an object with schema_version=1.0 and 1-10000 rows. Each row has
an opaque recording ID, source_type, relative WAV reference and SHA-256, reviewed
ground truth, language/script, speaker pseudonym, session, recording group,
development/validation/test split, noise label, content type, usability annotation,
task type and expected command labels. Real rows also require an opaque consent
reference, evaluation_permitted=true and a non-expired retention review date.
Consent flags are operator attestations, not independent proof of informed consent.
Receipts and identity mappings belong in separate restricted storage.

Manifest validation opens only the selected manifest and checks audio path metadata;
it does not read audio. Paths resolve inside the explicitly approved root, including
symlink resolution. Public repository paths are refused. The evaluator verifies
bounded WAV bytes against the annotated hash only after explicit audio-evaluation
consent. It never scans recording folders. UTF-8 manifest/overlay errors are replaced
with safe error codes; private fields are absent from repr and ordinary serialization.

Validation rejects unknown schemas, missing consent, unreviewed references, duplicate
IDs and cross-split speaker/session/recording-group/audio-hash or resolved-path overlap.
Recording groups must cover all derived versions. It cannot discover undeclared
near-duplicates or independently judge transcript truth. A conservative check rejects
multiword ground-truth text copied into a public vocabulary form, including punctuation
variants. It does not infer how a vocabulary was authored; independent review remains
necessary. Do not construct private overlays from held-out answers either.

One-speaker results are personal development evidence. Mixed-split results are labelled
pooled, not held-out scores. Validate all splits before selecting --split test.
Public fixtures and the demo are explicitly fictional; no real data is imported.

## Contextual vocabulary

context-v1 contains 11 deliberately small entries: one assistant, five existing
applications, three supported actions, one fictional location and one fictional media
title. Forms cover English, Hindi, Marathi, transliterations, abbreviation and
alternate spelling. Review means engineering review, not native-speaker validation.
The schema also supports user-confirmed observed ASR variants, but they are excluded
from hotwords and require confirmation. No real observed variant was imported.

Each form preserves language/script/kind/provenance, review status, confirmation and
hint/refinement eligibility. Context vocabulary does not add resolver aliases, intents
or acceptance permissions. A private overlay requires an explicit path and approved
root through the evaluation command; it is never automatically discovered.

Context mode is off by default. --contextual opts in for microphone, file, sessions
and parity. The shared engine compiles hints from the same settings and request
language. In contextual mode, initial_prompt is empty and a single hotword list avoids
repetition. Limits are 300 hotword characters and 96 tokenizer tokens; the interface
also bounds initial_prompt to 500 characters (currently unused). Counting includes
the backend's leading space. No cached tokenizer or an invalid tokenizer result means
no hints, with tokenizer_unavailable/tokenizer_error recorded. No tokenizer is fetched
for inspection. Deduplication is NFC/casefold-based; output forms preserve their script.

Without contextual mode, the existing public static prompt/hotwords remain, with the
personal hint removed. Model small/cpu/int8, beam=5, temperature=0, backend previous-text
conditioning, VAD and safety thresholds are unchanged. Hints are not vocabulary
constraints, pronunciation dictionaries or confidence estimates.

## Shadow refinement

Raw transcript remains the exact concatenated model segments under the existing
contract. normalized_transcript remains the whitespace-joined view. A separate
Refinement object has an optional refined_transcript, source_view, shadow-v1 version,
changed spans, rule IDs, alternatives, evidence category and confirmation requirement.
Spans index the normalized view. Text is excluded from normal serialization/repr;
inspection is an explicit local action.

Only two whole-utterance Hindi/Marathi courtesy-boundary proposals are implemented.
Both require confirmation. No rule runs inside a larger sentence. Unknown words,
names, applications, numbers, dates, URLs, emails, negation and commands abstain.
This narrow scope avoids reconstructing content or pretending spelling correction
can recover missing words. Refined text never replaces CLI output or enters the
resolver. Failed/rejected/cancelled results produce no refinement text. No rule
is a calibrated probability. Public examples are fictional.

## Experimental arms and reproducibility

A: small with both static and contextual hints disabled, for an explicit unhinted
baseline. B: the same settings/audio with versioned contextual hints. C: reuse B's
successful hypothesis with shadow proposals. D_from_A/D_from_B: apply the unchanged
resolver to fixed raw hypotheses. There is no refined-input command acceptance.
E: medium multilingual placeholder only; execution is rejected pending separate
approval/download. Real evaluation is cached-model-only.

One frozen common settings snapshot supplies A/B; only contextual mode differs.
The same immutable PCM is loaded once per row; actual prepared model inputs must
be numerically identical. Two small-model instances isolate arm state; processing
order alternates between rows. C/D never trigger extra ASR. Metadata records the
model reference, installed Faster-Whisper version, effective language mode, generic
hardware/device summary, decoding/VAD/safety configuration, vocabulary/refinement
versions, context status counts and cold/warm counts. A precise model snapshot
revision is labelled unavailable rather than fabricated. Context output text and
private overlay content are not aggregate metadata.

Language defaults to each manifest language, with mixed rows using auto detection.
--language auto selects automatic detection for all rows; en/hi/mr select a fixed
language condition. Compare language modes separately. Local model nondeterminism
can still affect outputs despite identical prepared audio.

## Exact metric definitions

Scoring copies use NFC, casefold, Unicode punctuation-to-space and whitespace collapse.
No transliteration is applied. Devanagari vowel signs and nukta are retained. Raw
and refined hypotheses are reported as separate arms, never merged or relabelled.

- WER: minimum word insertions/deletions/substitutions divided by reference words.
- CER: code-point edit distance after removing scoring spaces, divided by reference
  code points; this is not grapheme CER.
- Whitespace-sensitive CER: code-point edit distance including normalized word spaces,
  divided by reference length including spaces.
- Boundary error: when non-space strings agree exactly, mismatched space-boundary
  positions divided by the number of inter-code-point gaps. Otherwise ineligible;
  sample_count discloses this restriction. Whitespace-sensitive CER covers other cases.
- Accepted-only metrics score succeeded STT, with successful_stt_coverage alongside.
  Delivered-output metrics score every completed row; rejected/failed output is empty.
  No discarded decoder hypothesis is retained or scored behind the safety gate.
- Empty references retain insertion numerators with null percentages for zero
  denominators; empty-reference word insertions are reported separately. WER can
  exceed 100 percent.
- Intent accuracy is exact intent match on command rows, including null. Exact entity
  accuracy compares the whole dictionary; per-slot accuracy uses rows with that slot
  in reference or prediction. Canonical accuracy is exact proposal-string equality.
- Confirmation rate: confirmation-required proposals / command rows. Acceptance
  coverage: succeeded STT resolved without confirmation / command rows.
- Unsafe false acceptance: accepted incorrect/unknown/confirmation-required proposals
  divided by the union of expected-confirmation, unknown-intent and incorrect-result
  opportunities. Also report the same numerator / accepted proposals. Acceptance is
  interpretation acceptance only; execution remains prohibited.
- False rejection: unusable_audio / independently labelled usable speech.
  transcription_failed outcomes are reported separately, not called safety rejection.
- Non-speech rejection: unusable_audio / labelled non-speech. Successful spurious
  output: succeeded nonempty output / labelled non-speech. These are operational
  proxies, not measured hallucination-detector recall.
- Timings: sample count, sum, mean, p50/p95 for inference, total STT processing and
  refinement. Per-clip RTF = STT processing / source duration; weighted_rtf = sum of
  STT processing / sum of source duration. C/D reuse source ASR timing, not extra ASR
  cost; refinement time is separate. Never sum arm timings as independent work.

Rates carry numerators, denominators, percentages and eligible sample counts. Reports
are overall and by language, with split counts. Missing populations have null rates.
No prompt text, audio sample, speaker/session ID, path, reference or hypothesis appears
in aggregate output. --show-utterances explicitly authorizes local per-utterance display;
only successful hypotheses appear. There is no export writer or automatic persistence.
Cancellation discards accumulated output and clears model-input snapshots.

## Validation and research use

Automated tests use generated PCM, fictional annotations, fake capture/STT/tokenizers
and temporary directories. Model/hardware imports and network calls are blocked.
Fakes demonstrate routing/contracts/scoring, not recognition quality or real VAD
performance. No external private directory or real dataset was created.

After separate consent: choose a restricted nonsynced root; define retention,
withdrawal and publication permissions; collect new consented material separately;
assign pseudonyms; independently review ground truth; group speakers/sessions/derived
recordings; validate all splits; freeze vocabulary/rules on development data; run
paired cached-small arms on locked test data; inspect paired differences and uncertainty.
Keep receipts/identity mapping separate. Review aggregates before any public release.
No per-speaker generalization or improvement claim follows from a small personal pilot.
