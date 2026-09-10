# VoicePilot

Phases 1-3 implement project foundation, explicit audio input and local STT.
Recognized speech is displayed as text and is never executed.
Python 3.12.10 and the existing venv are preserved; no packages were changed.
This is not production-ready.

The user verified Phase 2 device listing, recording, WAV saving, cancellation and
audio quality. In manual Phase 3 testing, base misrecognized words and endings;
small improved VoicePilot/Spotify recognition but one first run took 262.431s.
That observation did not separate model initialization from inference and is
not an inference benchmark. The refinements below are fake-tested only; their
real accuracy and performance have not been measured.

## Run from the project root

Use the existing interpreter explicitly; activation is unnecessary. Do not
recreate venv or install/upgrade packages. Direct dependencies remain pydantic,
pydantic-settings, numpy, sounddevice and faster-whisper; tests use pytest.

**Model notice:** the first transcription with small may download that model into
the ignored models/whisper cache. Recognition itself stays local; audio is never
uploaded. These manual commands were not automatically executed.

```powershell
# Flexible duration: stop by Enter, cancel, or the safety limit
.\venv\Scripts\python.exe -m app.stt.cli microphone

# Keep one process/model alive for consecutive deliberate recordings
.\venv\Scripts\python.exe -m app.stt.cli microphone --session

# Explicit limit of ten seconds
.\venv\Scripts\python.exe -m app.stt.cli microphone --seconds 10

# Opt in to automatic stopping after two seconds of silence following speech
.\venv\Scripts\python.exe -m app.stt.cli microphone --silence-seconds 2

# English; or use --language auto and speak a short Hindi/Marathi sentence
.\venv\Scripts\python.exe -m app.stt.cli microphone --language en
.\venv\Scripts\python.exe -m app.stt.cli microphone --language auto

# Transcribe only this explicitly selected file
.\venv\Scripts\python.exe -m app.stt.cli file recordings\phase2-test.wav
```

Press Enter at the consent prompt to start. During capture, Enter stops and keeps
the samples for transcription; c or Ctrl+C cancels and discards them. Elapsed
seconds are displayed while the foreground terminal is polled. No global hooks,
background input reader or continuous listening are used. Keep terminal focus.

Without --seconds, capture has no short fixed limit: it stops on Enter, optional
silence detection, or the safety maximum. The safety maximum defaults to 120s
and cannot exceed 120s. The STT duration limit also caps capture. --seconds adds
an explicit shorter cap; either cap can still end speech, so stop before it.
Native driver calls can delay a stop request despite application limits.

Silence stopping defaults off. When enabled, block RMS above the configured
threshold first marks speech activity; subsequent below-threshold blocks count
toward the silence interval. Renewed activity resets that interval. Leading
silence waits for Enter/cancellation/safety rather than immediately stopping.
This is an energy heuristic, not linguistic end-of-sentence detection. Background
noise can prevent stopping, and quiet speech/long pauses can stop too early.
Trailing captured silence is retained. Adjust or disable this feature as needed.

Audio is not saved automatically. STT has no --save option. Session mode keeps
one model loaded while asking for fresh consent before each recording; the
microphone is stopped between requests. Type q/c at the next consent prompt to
end the session. Cancellation ends the current session and discards its current
capture/transcript. No history database or permanent transcript is created.

## Accuracy and vocabulary settings

.env.example lists VOICEPILOT_ environment variables. Settings do not load a
model, access devices, read .env automatically, or create directories.

Defaults:
- WHISPER_MODEL=small, WHISPER_DEVICE=cpu, WHISPER_COMPUTE_TYPE=int8.
- STT_BEAM_SIZE=5 (1-10); STT_TEMPERATURE=0 (0-1).
- STT_LANGUAGE=auto; STT_VAD_FILTER=true; STT_WORD_TIMESTAMPS=false.
- STT_VAD_MIN_SILENCE_DURATION_MS=1000 (100-5000); VAD speech padding is 400ms.
- AUDIO_MAX_DURATION_SECONDS=120 and STT_MAX_DURATION_SECONDS=120; both may
  be lowered to 0.1s. There is no unbounded capture mode.
- AUDIO_SILENCE_STOP_ENABLED=false; AUDIO_SILENCE_DURATION_SECONDS=2
  (0.25-30); AUDIO_SILENCE_THRESHOLD=0.01 (normalized RMS, greater than 0 to 0.25).

Faster-Whisper receives STT_INITIAL_PROMPT and STT_HOTWORDS with default vocabulary
VoicePilot, Spotify, WhatsApp, Chrome, YouTube and Dhruti. These are decoding hints,
not replacement rules or instructions to execute. Custom prompt/hotword text is
bounded and rejects control characters; neither is logged. Empty strings disable
the respective hint. The installed Faster-Whisper supports the hotwords option.

No arbitrary correction is performed: "Play Voice Pilot" will not be silently
changed to "Hey VoicePilot". Structured results preserve:
- raw_transcript: exact backend segment strings concatenated in time order.
- normalized_transcript: only leading/trailing segment whitespace is trimmed
  and segment boundaries joined with one space. Internal text and words remain.
- text: the compatibility field for normalized_transcript.
Segments retain their raw text. CLI display also removes terminal control
characters, with no length truncation or lexical rewrite.

Accuracy is not guaranteed. Vocabulary bias can introduce unwanted words; VAD
can omit quiet speech; accents, noise and pauses matter. Small may still be slow
on a 16 GB laptop. No medium/large model or GPU migration is made. No performance,
WER or accuracy improvement is claimed from fake tests.

Use multilingual small for Hindi/Marathi; .en models only support English.
Short utterances and mixed-language speech make auto-detection less reliable,
and English domain hints may bias multilingual output. Try an explicit language
code or empty hints when appropriate. Language probability is detection metadata,
not transcription confidence, and is omitted for forced-language requests.

## Cold versus warm timing

Each result/CLI output separates:
- model_load_duration: model initialization, including model download/cache
  resolution when needed. This is never counted as pure inference.
- inference_duration: backend transcribe call and full segment-generator
  consumption, including language detection/VAD/decoding and segment conversion.
- processing_duration / total_processing_duration: engine preparation, load and
  inference plus orchestration. Excludes microphone capture, WAV file reading
  and final cleanup.
- source_audio_duration and real_time_factor: total processing / audio seconds,
  unavailable when source duration is zero.
- cold_start: true when this engine needed to construct its model, false when
  it reused its model, and unknown for requests rejected before that decision.

Cold does not mean a download definitely occurred. A cached disk model still
requires initialization in a new process. Separate CLI invocations are new
processes. Use --session and compare its first and second successful results
to observe cold and warm timings on this laptop. No measured speedup is assumed.
Ctrl+C requests cancellation, but native model/download operations can delay it.
Model references are dropped at session exit; native libraries manage reclamation.

For strictly cached models:
```powershell
$env:VOICEPILOT_STT_LOCAL_FILES_ONLY = "true"
.\venv\Scripts\python.exe -m app.stt.cli microphone --session
```
This fails safely if the chosen model/tokenizer is not already cached.

## Audio formats, privacy and tests

The existing Phase 2 commands remain available:
```powershell
.\venv\Scripts\python.exe -m app.audio.cli devices
.\venv\Scripts\python.exe -m app.audio.cli record --seconds 3
.\venv\Scripts\python.exe -m app.audio.cli record --seconds 3 --save --filename phase2-test.wav
```
Only explicit Phase 2 --save enables WAV export; existing files require explicit
--overwrite. Exports stay within the ignored recordings tree.

Audio capture uses signed int16, default 16000 Hz mono, 1024-frame blocks.
Selected WAVs support PCM 8/16/24/32-bit, 8000-48000 Hz and 1-8 channels, within
the configured duration. Empty, corrupt, truncated and oversized files fail.
No folders are scanned. Input is downmixed and converted to mono float32 at
16000 Hz; other rates use an in-memory WAV buffer and Faster-Whisper's resampler.
No temporary recording file or extra dependency is needed.

Audio/transcripts are excluded from ordinary logs; text-capable backend logging
is suppressed. Explicit transcript display can remain in terminal scrollback.
Cancellation discards application references, not a guarantee of secure memory
erasure. OS/driver buffers are outside application control. Model files and
recordings remain ignored. No wake word, speaker verification, LLM, computer
control, history database, API or frontend is implemented. Phase 4 is not started.

```powershell
.\venv\Scripts\python.exe -m pytest
.\venv\Scripts\python.exe -m pytest tests/audio
.\venv\Scripts\python.exe -m pytest tests/stt
```
Tests use fake capture/model backends, synthetic audio and temporary WAVs.
STT tests block real model/hardware imports and socket connections. No real
microphone, download, model inference or performance benchmark is run by tests.

## Phase 3B: non-executing command resolution

The text-only command resolver proposes intent/entities without opening apps,
controlling media, reading personal files or executing commands. It preserves
raw_transcript unchanged, creates a separate matching-normalized transcript,
and exposes canonical_command as a proposal. Existing STT behavior is unchanged.

Run from the project root:
```powershell
.\venv\Scripts\python.exe -m app.commands.cli resolve "open Spotify"
.\venv\Scripts\python.exe -m app.commands.cli resolve "play Tharism Infer"
.\venv\Scripts\python.exe -m app.commands.cli validate-dataset
.\venv\Scripts\python.exe -m app.commands.cli evaluate
.\venv\Scripts\python.exe -m pytest tests/commands
```

Every result has execution_permitted=false. Resolved means interpreted only.
Scores are heuristic match scores, not probabilities, calibrated confidence or
STT confidence. Unknown, incomplete, negated, compound, fuzzy and ambiguous
requests cannot silently become accepted proposals. Tharism Infer is a
user-observed ASR error for Taare Zameen Par, not a pronunciation, and always
requires explicit confirmation. No confirmation-to-execution path exists.

The registry is independently defined in data/commands/aliases-v1.json and
intents-v1.json. --registry-dir selects an explicit alternate registry directory;
ResolverConfig controls bounded match thresholds. There is no seed lookup at
runtime, no model training, and no automatic transcript/history storage.

The 80-row seed is synthetic development/test text, not a research training
dataset or evidence of real-world accuracy. Evaluation reports exact counts,
denominators and percentages, including coverage and explicitly defined false
acceptance. Unsupported paraphrases are expected; the rules are not tuned to
make seed metrics perfect. Empty-entity/null labels can inflate exact-match
metrics, and these results say nothing about raw ASR WER or acoustic robustness.

See docs/datasets/command-dataset-v1.md for schema, score policy, metric
denominators, consent, pseudonymization, speaker-disjoint future audio splits
and limitations. No audio is collected in Phase 3B. No later phase is started.

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

## Final Phase 3B context and raw-text contract correction

Coordinated Spotify/play proposals now retain both application=Spotify and
media=<title>, with canonical command Play <title> on Spotify. Observed ASR
variants still require confirmation; missing media keeps the known application
but yields no complete canonical command. Only the corresponding workflow seed
annotation is updated. Ordinary media requests without app context are unchanged.

Controlled pre-edit tracing preserved the exact spaced input through PowerShell
argv reception, direct resolution, Pydantic round-trip, supplied CLI argument
list, and a Python subprocess CLI with byte-equal UTF-8 round trips. No loss
reproduced in address/workflow stripping or JSON serialization. Thus the earlier
manual discrepancy remains unlocated; it is not assumed to be copying. The
resolver preserves the exact Unicode string received (and its UTF-8 encoding);
JSON escaping is representation, not deletion of whitespace. Strict raw-string
typing and regressions cover this contract without normalizing raw text.

The registry already stored Phase 3B instructions with its space intact. A
regression locks that provenance formatting and observed_asr_error status.
Subprocess regression is restricted to the existing venv's non-executing CLI,
with shell disabled and child network/system-action entry points blocked.
No dependency, audio, model, automation or later-phase changes are made.

## Phase 3C: STT output safety

Every STT service result passes a shared local output gate. Empty, excessively
repetitive, implausibly long, jointly no-speech/low-logprob, or budget-exhausted
output becomes unusable_audio; no transcript is forwarded for command resolution.
Retry with a clean capture. Whole results are rejected; words are never removed
to salvage a command. Successful raw and normalized transcripts remain separate.
Short repetition such as "stop, stop" remains valid.

Rejected decoder text is retained only as a bounded private in-memory diagnostic
prefix, never in CLI output, logs, ordinary serialization, resolver output or files.
Cancellation discards diagnostics. Audio is not saved by STT. The text-only resolver
bypasses STT provenance; manually typed commands do not validate speech recognition.

See [decision 0005](docs/decisions/0005-stt-output-safety.md) for exact rules,
configuration names, privacy limits and evaluation methodology. Defaults are
unvalidated engineering thresholds; accuracy and hallucination detection are not
guaranteed, especially across languages. No microphone/model test or research
accuracy claim is implied. Existing manual STT commands are unchanged.
