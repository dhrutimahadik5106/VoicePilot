# 0005: STT output safety (Phase 3C)

## Scope and evidence boundary

A user observed an approximately 6.72-second noisy/incorrect capture producing a
long repetitive Google/Facebook transcript. The original audio, decoder output
and segment metadata were not retained. Noise, capture quality and decoding
behavior cannot be distinguished retrospectively. The regression fixture is a
**synthetic reconstruction**, not a recording or measured hallucination case.
This change adds an output gate; it does not repair audio, change small/cpu/int8,
vocabulary or Phase 3B seed labels, or implement execution.

## Shared policy and result contract

app/stt/output_safety.py owns the reusable deterministic acceptance policy.
The Faster-Whisper adapter collects optional no_speech_prob and avg_logprob
segment metadata and enforces finite segment/character collection budgets.
It uses the shared gate; TranscriptionService applies that same idempotent gate
to every interchangeable engine, using the duration of the actual supplied PCM.
There are no independently duplicated acceptance rules.

An entire rejected result has status unusable_audio, error unusable_audio,
safe rejection_reasons, empty text, raw_transcript, normalized_transcript
and segments, and no language probability. No repetitive words are removed to
salvage a command. Existing failed and cancelled statuses remain distinct.
Exceptions inside policy evaluation produce safety_gate_error without exception
text. Empty/punctuation-only output rejects. Cancellation discards diagnostics.
The resolver blocks every non-successful STT status without reading its transcript.
The explicit text-only resolver remains available: manually entered text bypasses
STT provenance and does not demonstrate that audio passed this gate. No automatic
command execution exists; every proposal retains execution_permitted=false.

## Initial rules and configuration

These are **unvalidated engineering defaults**, not research-derived thresholds,
calibrated probabilities or STT confidence. Settings use the VOICEPILOT_ prefix
and uppercase field names in environment variables. There is no disable switch.

| Settings field | Default | Rule |
| --- | ---: | --- |
| stt_safety_word_repetitions | 8 | Reject at least 8 consecutive identical analysis tokens. |
| stt_safety_phrase_repetitions | 4 | Reject consecutive repeated phrases of 2-8 tokens with at least 4 repetitions. |
| stt_safety_phrase_min_tokens | 16 | Phrase repetitions must also span at least 16 tokens. |
| stt_safety_min_tokens | 30 | Token limit floor. |
| stt_safety_tokens_per_second | 6 | Reject token count strictly above max(30, 6 * audio seconds). |
| stt_safety_min_characters | 180 | Character limit floor. |
| stt_safety_characters_per_second | 40 | Reject character count strictly above max(180, 40 * audio seconds). |
| stt_safety_no_speech_prob | 0.8 | Reject any segment with this value or higher AND the logprob condition. |
| stt_safety_avg_logprob | -1.0 | Joint no-speech condition: this value or lower on the same segment. |
| stt_safety_max_segments | 256 | Reject on consuming segment 257; close the generator. |
| stt_safety_max_output_characters | 8192 | Reject cumulative decoded characters above 8192; close the generator. |

Reason codes are empty_output, repeated_word, repeated_phrase, token_limit,
character_limit, no_speech, output_budget_exceeded, safety_gate_error.
Multiple policy reasons may be returned. Output-budget rejection takes precedence.

Analysis tokens are casefolded, with Unicode punctuation, separators and symbols
treated as boundaries; Indic combining marks are preserved. Tokenization is an
engineering approximation, not a linguistic tokenizer. Character count uses the
larger of raw concatenated text length and segment-boundary-normalized length,
measured in Python Unicode code points. Public successful transcripts remain
unchanged. Missing no-speech metadata is unknown, not invented evidence. Metadata
is evaluated per segment, never by pairing values from different segments.
Compression ratio, language probability and RMS are not standalone rejection
signals (compression ratio and RMS are not consumed by this policy).

## Privacy

Rejected decoder text exists only in a private in-memory diagnostic object attached
through Pydantic PrivateAttr, excluded from repr, ordinary model dumps/JSON, CLI,
logs, exceptions and resolver output. It retains at most 8192 Unicode characters
as an exact decoder prefix; complete=false marks truncation or budget exhaustion.
Diagnostic and budget object repr never include text. There is no export, history,
file write or rejected-audio persistence. Backend transcript logging remains
suppressed. Cancellation removes the diagnostic reference. Python memory is not
securely zeroized; a debugger, explicit private-attribute access or memory dump
can still inspect in-memory content. This is not a security boundary against code
running in the same process. Successful transcripts retain their existing explicit
display/serialization behavior.

## Validation and research methodology

Deterministic tests use synthetic text, metadata, fakes and blocked hardware/model/
network imports. They cover exact threshold boundaries, segment-spanning repetition,
empty output, generator budgets/closure, gate exceptions, cancellation, private
serialization, alternate engines, actual audio duration, multilingual normal commands,
short legitimate repetition, and blocked resolver handoff. No real microphone,
model download or inference benchmark is run.

Future consented audio evaluation needs independently annotated usable/unusable
audio and reference transcripts; uncertain cases need adjudication. Freeze thresholds
before held-out testing, keep development separate, and split future audio by speaker
across train/validation/test. Report numerator, denominator and percentage for:
- Hallucination rejection: hallucinated outputs rejected / all labeled hallucinated outputs.
- False rejection: usable outputs rejected / all labeled usable outputs.
- False acceptance: unusable outputs accepted / all labeled unusable outputs.
- Acceptance coverage: all outputs accepted / all evaluated outputs.

Also report reasons and results by language, duration and noise condition, sample
sizes and uncertainty intervals; zero denominators are N/A, not 0% accuracy.
Report raw ASR WER/CER separately from output-gate rejection and command-resolution
accuracy. Do not infer research performance from synthetic unit tests or the Phase
3B synthetic development seed. Do not tune unrelated rules to improve seed scores.

## Limitations and unresolved risks

Plausible short hallucinations may pass; valid fast speech, long words and intentional
repetition may be rejected. Multilingual/tokenization behavior needs held-out consented
evaluation. Backend VAD/no-speech filtering may hide rejected segments before this gate;
metadata is not ground truth. Any joint no-speech segment currently rejects the complete
result, which is conservative for mixed speech/noise captures. Finite output budgets
bound collection after yielded segments, not native decoder memory allocation, a huge
single yielded string, or a generator blocked inside its next call. No inference
watchdog/process isolation is added. No persistence is added in this phase.
