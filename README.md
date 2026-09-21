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
VoicePilot, Spotify, WhatsApp, Chrome, YouTube and. These are decoding hints,
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

Rejected decoder text is discarded. Only bounded numerical evidence is retained,
with no rejected text in CLI output, logs, serialization, resolver output or files.
Cancellation discards diagnostics. Audio is not saved by STT. The text-only resolver
bypasses STT provenance; manually typed commands do not validate speech recognition.

See [decision 0005](docs/decisions/0005-stt-output-safety.md) for exact rules,
configuration names, privacy limits and evaluation methodology. Defaults are
unvalidated engineering thresholds; accuracy and hallucination detection are not
guaranteed, especially across languages. No microphone/model test or research
accuracy claim is implied. Existing manual STT commands are unchanged.

### Safe rejection diagnostics

Rejected STT output now includes safe reason codes. To reproduce a rejection and
see numerical evidence, explicitly run in PowerShell:

    .\venv\Scripts\python.exe -m app.stt.cli microphone --seconds 10 --language en --safety-diagnostics

For session mode, replace --seconds 10 with --session. Enter stops capture;
c/Ctrl+C cancels. The diagnostics flag does not change recording consent, model
loading, decoding, thresholds or acceptance. Rejected transcript text is never
displayed. Successful output remains unchanged. No audio is saved.

The summary contains rejection reasons, actual PCM duration, original consumed
segment count, normalized token and character counts, applicable length limits,
bounded numerical per-segment no_speech_prob/avg_logprob values, optional backend
duration_after_vad, and output-budget status. Missing values are null.
At budget exhaustion, counts describe consumed output rather than unseen future
segments; token count is null to avoid further processing of oversized output.
Per-segment metadata is capped at 4096 entries. These are engineering diagnostics,
not calibrated confidence or proof that the audio contains no speech.

## Phase 3D: controlled audio-path parity

Earlier direct and saved-WAV results were separate captures (7.488s and 9.728s),
so they cannot prove path inequality. This experiment captures once and compares
that exact PCM through direct STT and a WAV round-trip entirely in BytesIO.
It never opens existing diagnostic recordings or saves the new capture.

Run explicitly from the repository in PowerShell:

```powershell
.\venv\Scripts\python.exe -m app.stt.parity --seconds 10 --language en
```

Press Enter to consent to one capture and two local transcriptions. During capture,
Enter stops and c/Ctrl+C cancels. A finite duration cap always applies. The runner
uses one frozen settings snapshot, one model instance, identical language/decoding/
VAD settings, and cached model files only, even if normal STT allows downloads.
A missing cache produces failed STT status; the runner never enables downloads.
It preserves the configured VAD state; use the normal VAD-enabled configuration
for this experiment (remove any earlier temporary VAD-disable override).

Successful transcripts are hidden unless explicitly requested:

```powershell
.\venv\Scripts\python.exe -m app.stt.parity --seconds 10 --language en --show-successful-transcripts
```

To run the WAV branch before the direct branch, add `--reverse-order` to either
command. Each invocation captures once; a later reversed invocation is a new
capture, while both branches within that invocation share exactly one recording.
The first call may include model loading; compare inference and total processing
separately. Timings are not transcription-accuracy measurements.

The JSON report contains only source rate/channels/frames/duration, dtype/shape,
RMS and peak, prepared dtype/shape/duration/RMS/peak, exact PCM-container preservation,
prepared-array equality and maximum absolute difference, both STT statuses/reason
codes/VAD durations/segment counts/timings, and successful-transcription equality.
RMS/peak use full-scale units (int16 divided by 32768); source statistics combine
channels, prepared statistics describe 16 kHz mono. Prepared arrays are snapshots
of the actual inputs immediately before the model call, not separately recomputed
approximations. No sample values or persistent audio hashes are printed.

`pcm16_preserved=true`, `prepared_equal=true`, and `max_absolute_difference=0`
establish exact input parity for that capture. They do not guarantee identical
model output if backend execution is nondeterministic. `transcription_equal` is
null unless both results succeed; two cleared rejected transcripts are not counted
as equal. Missing measurements are null; unequal prepared shapes have no maximum
difference. Rejected segment counts cover consumed output at budget cutoff.
Cancellation emits no report and releases audio/results; numerical array snapshots
are cleared. Python memory is not guaranteed securely erased. Rejected transcripts
remain inaccessible under every display option. Successful transcript display is
explicit and JSON-escaped. No resolver or command execution is involved.

Shared preprocessing returns finite, contiguous, one-dimensional float32 mono at
16 kHz. Source duration remains original frames/source rate. Mono PCM16 behavior
is unchanged. Stereo uses the existing WAV round-to-even convention; at 16 kHz the
maximum change from the old direct path is half an int16 PCM unit (1/65536 at full
scale). This tiny difference is not established as the cause of the reported failure.
No gain amplification, normalization, denoising, trimming, new VAD settings or
transcript correction is added. Existing explicit WAV saving remains available.

Synthetic tests with fake capture, deterministic resampling and fake STT/VAD prove
routing parity, not real Whisper/VAD accuracy or real resampling quality. No accuracy
improvement is claimed. Accuracy requires a separately consented evaluation dataset.

## Phase 3E: contextual STT and private evaluation foundation

Contextual hints are opt-in; normal transcription stays unchanged except removal of
personal vocabulary from public defaults. Add --contextual to an existing STT file,
microphone/session or parity command. Shadow refinement never replaces raw output
and never feeds command resolution. No real accuracy improvement is claimed.

The following commands validate or inspect public fictional material only. They do
not access audio hardware, existing recordings, models or the network:

```powershell
.\venv\Scripts\python.exe -m app.evaluation.cli validate-schema
.\venv\Scripts\python.exe -m app.evaluation.cli demo
.\venv\Scripts\python.exe -m app.evaluation.cli inspect-context --language hi
.\venv\Scripts\python.exe -m app.evaluation.cli inspect-refinement --language hi --text "कृ पया"
```

The demo uses fake recognition and generated in-memory PCM. Its scores are pipeline
checks, not accuracy evidence. Context inspection lists public forms; actual token
budgeting occurs only with the loaded cached tokenizer. Missing tokenizer information
fails safely to no hints. Refinement inspection explicitly displays supplied text and
its separately labelled proposal; ordinary reports hide text.

Preferred private storage is %LOCALAPPDATA%\VoicePilot\private-evaluation\, outside
this repository/OneDrive. No directory is created automatically. data/stt/private/
is an explicitly ignored alternative, but ignore rules do not encrypt data or prevent
cloud synchronization. Do not store identity maps, consent receipts or personal
transcripts in tracked files. Older commits may retain previously removed hints;
no Git history was rewritten.

Real manifest validation requires --private-root and --manifest. It checks metadata
and paths without reading audio. The run command additionally requires
--consent-evaluation before reading any selected audio. Optional --private-overlay
explicitly loads a vocabulary within that same private root; no overlay autoloads.
Optional --show-utterances authorizes local private display; aggregate-only is default.
There is no export writer. Use --split to select a previously validated split and
--language auto for a separate automatic-language condition. Real evaluation must
wait for separately consented data; existing personal recordings are not imported.

See [decision 0006](docs/decisions/0006-contextual-stt-private-evaluation.md) for the
manifest contract, scoring normalization, exact denominators, A/B/C/D comparisons,
privacy boundaries and limitations. Medium remains an unimplemented placeholder.

## Phase 4A speaker-verification foundation

Fake-backed enrollment, verification, protected-storage boundaries and synthetic
metrics are implemented. Real inference and secure profile persistence remain
unavailable. No new dependencies, runtime or model have been installed.

Safe commands (no microphone, recordings, model or profile access):

```powershell
.\venv\Scripts\python.exe -m app.speaker.cli inspect-status
.\venv\Scripts\python.exe -m app.speaker.cli inspect-policy
.\venv\Scripts\python.exe -m app.speaker.cli validate-schema
.\venv\Scripts\python.exe -m app.speaker.cli evaluate --synthetic
```

`profiles list`, `enroll` and `verify` return unavailable (exit code 2).
Synthetic scores are pipeline tests, not measured biometric performance. Existing
STT/resolver CLIs remain diagnostics, never authenticated execution paths.

Enrollment requires separate capture/enrollment and persistence consent. No raw
audio is saved. Profiles are biometric data; future storage belongs outside Git
and OneDrive, behind an audited protector and private ACLs. Phase 4A's default
protector fails closed. It implements no real DPAPI encryption.

The gateway verifies each buffer afresh and passes the same audio to the existing
STT safety service only under a validated policy. Pending/synthetic policies and
all nonverified outcomes block the gateway. No execution is implemented.

Voice matching does not establish liveness, defeat replay/deepfakes, or replace
Windows authentication. Hindi/Marathi/Indian-accent accuracy is unmeasured.
Python cannot guarantee memory erasure; deletion cannot erase backups or copies.
High-risk future actions require another factor.

See [decision 0007](docs/decisions/0007-speaker-verification-foundation.md) for
configuration defaults, enrollment/deletion behavior, threshold equations,
synthetic results, privacy limits and the separately approved Phase 4B boundary.


## Phase 4B local speaker verification

Phase 4B supersedes the Phase 4A unavailable runtime/protector descriptions above.
The pinned WeSpeaker model runs locally through sherpa-onnx 1.13.8. Explicit CLI
workflows provide enrollment, verification and private calibration; current-user
Windows DPAPI protects profiles and records outside Git/OneDrive, without plaintext
fallback. Calibration evidence and reviewed policies bind to the exact enrollment.
Successful re-enrollment resets authorization; failed replacements preserve it.
Defaults remain disabled/pending. No microphone testing or real enrollment was
performed during implementation, and no execution or anti-spoofing is implemented.

See [decision 0008](docs/decisions/0008-real-local-speaker-verification.md) for the
model source/licence/hash, configuration, security limits, evaluation and exact manual
commands. `inspect-status`, `inspect-model`, `smoke-backend` (generated sine wave),
`smoke-dpapi` (fixed marker), and `evaluate --synthetic` do not capture a microphone.


## Phase 5A: safe planning and diagnostics

VoicePilot now produces deterministic typed task plans, risk decisions and simulated
results. Every step has execution disabled. No application/browser control or live
search is implemented. Unknown research/cafe-comparison requests remain unsupported.

```powershell
.\venv\Scripts\python.exe -m app.pipeline.cli unauthenticated-text "open Spotify" --show-transcript
.\venv\Scripts\python.exe -m app.planning.cli evaluate
```

User-only microphone diagnostics: `-m app.pipeline.cli unauthenticated-voice --seconds 8
--show-transcript` using the same venv interpreter. Every capture requires Enter.
`--session` permits a bounded series of deliberate captures. Cached STT models only;
missing models fail without a download. This mode is explicitly unauthenticated and
cannot authorize execution. `authenticated --profile PROFILE_UUID` instead uses the
Phase 4B policy/verifier boundary and blocks before STT while calibration is pending.

No audio or trace is saved automatically. `--save-audio` and `--save-trace` ask separate
per-operation consent; `--show-transcript` controls text visibility and whether an
approved trace save includes text. Artifacts default outside Git/OneDrive under
LOCALAPPDATA/VoicePilot/diagnostics. `traces list`, `traces inspect --id TRACE_UUID`
and `traces delete --id TRACE_UUID` manage explicitly saved diagnostic traces only.
Add `--show-transcript` to selected inspection to display saved text. Saved WAVs are
separate, with their exact path printed for manual playback/removal. All traces can
reveal intentions; approved text/audio is sensitive plaintext, not encrypted profiles.

See [decision 0009](docs/decisions/0009-safe-task-planning-diagnostics.md) for complete
CLI commands, architecture, consent/privacy boundaries, configuration and evaluation.
No real microphone, speaker profile, model or application was used during Phase 5A
validation. Synthetic results are not real-world safety guarantees.


## Phase 5B: controlled execution foundation

The execution controller now has closed fake adapters, plan-bound expiring single-use
authorization/confirmation, a validated state machine, independent observation and
verification, emergency stop, bounded retry/timeouts, idempotency and observed rollback.
Production execution remains disabled. Existing diagnostic plans cannot authorize it.
All adapters change synthetic in-memory state only; no application is opened.

```powershell
.\venv\Scripts\python.exe -m app.execution.cli status
.\venv\Scripts\python.exe -m app.execution.cli registry
.\venv\Scripts\python.exe -m app.execution.cli evaluate
```

No audit database, profile access, microphone use, model loading or dependencies are
introduced. See [decision 0010](docs/decisions/0010-controlled-execution-foundation.md)
for the synthetic authorization boundary, privacy, evaluation and Phase 6A prerequisites.


## Phase 6A: controlled Windows application launching

The separate `app.launch.cli` supports explicit manual tests for Notepad, Calculator,
Chrome and Spotify, conditional on protected installation and verified identity.
Production voice execution remains disabled and calibration-pending denies before
capture/STT. No playback, browser/input automation, arguments or arbitrary paths.
Start with `python -m app.launch.cli list`, `status` and `discover`, using the existing
venv Python. Launching requires the exact application ID and typed `LAUNCH <id>`.
No real launch was performed during development or automated validation.
See [decision 0011](docs/decisions/0011-controlled-windows-application-launching.md)
for exact venv commands, security boundaries, configuration and honest limitations.


## Phase 6B: controlled basic operations

Real controls and screenshot capture default off. Brightness read/support detection is
available where the fixed Windows interface is supported; real brightness mutation is
unsupported. Authenticated voice remains denied before capture and STT. See
[decision 0012](docs/decisions/0012-controlled-windows-basic-operations.md) for boundaries,
verification, privacy and cooperative cancellation limitations.

Safe commands (PowerShell, existing venv):

```powershell
.\venv\Scripts\python.exe -m app.operations.cli status
.\venv\Scripts\python.exe -m app.operations.cli volume-status
.\venv\Scripts\python.exe -m app.operations.cli mute-status
.\venv\Scripts\python.exe -m app.operations.cli brightness-status
.\venv\Scripts\python.exe -m app.operations.cli authenticated-voice-status
.\venv\Scripts\python.exe -m app.operations.cli plan "Set volume to 40 percent"
.\venv\Scripts\python.exe -m app.operations.cli evaluate
```

The following commands are for the operator to run manually, not automated validation.
They require an interactive terminal and exact confirmation shown immediately before
execution. No `--confirmed` flag or piped approval is supported. For example, setting
volume requires `APPROVE system.volume.set 40`.

```powershell
$env:VOICEPILOT_OPERATIONS__ENABLED="true"
.\venv\Scripts\python.exe -m app.operations.cli manual-volume-test increase
.\venv\Scripts\python.exe -m app.operations.cli manual-volume-test decrease
.\venv\Scripts\python.exe -m app.operations.cli manual-volume-test set 40
.\venv\Scripts\python.exe -m app.operations.cli manual-volume-test mute
.\venv\Scripts\python.exe -m app.operations.cli manual-volume-test unmute
.\venv\Scripts\python.exe -m app.operations.cli manual-brightness-test set 60
$env:VOICEPILOT_OPERATIONS__SCREENSHOT_ENABLED="true"
.\venv\Scripts\python.exe -m app.operations.cli manual-screenshot-test
# Replace the UUID below with the exact safe artifact ID returned by capture:
.\venv\Scripts\python.exe -m app.operations.cli delete-screenshot 00000000-0000-0000-0000-000000000000
$env:VOICEPILOT_OPERATIONS__SCREENSHOT_ENABLED="false"
$env:VOICEPILOT_OPERATIONS__ENABLED="false"
```

Brightness mutation returns unsupported. Screenshot confirmation is
`APPROVE screen.screenshot.capture`, consenting to primary-display capture AND saving.
Selected deletion requires `APPROVE screen.screenshot.delete <artifact UUID>`.
Storage is fixed at the local Windows Known Folder LocalAppData under
`VoicePilot/diagnostics/screenshots`; UUID-named artifacts remain until selected deletion.
No screenshot content is inspected or uploaded. Deletion is not secure erasure.

```powershell
.\venv\Scripts\python.exe -m app.operations.cli session
# Inside the same interactive session: volume-status, history, cancel, stop, exit
.\venv\Scripts\python.exe -m app.operations.cli history
.\venv\Scripts\python.exe -m app.operations.cli cancel
.\venv\Scripts\python.exe -m app.operations.cli stop
.\venv\Scripts\python.exe -m app.operations.cli authenticated-voice
```

History and cancellation are process-local; a fresh command has no prior session history
and cannot stop another process. Stop latches within its process; it does not close apps.
The final authenticated-voice command intentionally returns denial (exit 2).


## Phase 6B.1: owner calibration and authenticated voice pilot

`app.owner.cli` provides separately enabled personal owner calibration and a one-command
authenticated pilot. Existing profiles are preserved; no configuration toggle alone
approves calibration. Raw audio/transcripts are never saved. Screenshot operations stay
manual; brightness mutation remains unsupported. No real owner calibration or voice test
was performed during implementation.

Read [decision 0013](docs/decisions/0013-owner-speaker-calibration-and-authenticated-voice-pilot.md)
for the audited existing speaker stack, exact consent/capture commands, required 8 owner /
20 consenting non-owner / 4 holdout / 3 wrong-phrase trials, protection, revocation and
replay limitations. Start with `python -m app.owner.cli inspect-config` and `privacy`,
using the existing venv. Real manual calibration is explicitly user-operated.


Owner challenge verification uses the shared STT segment-boundary-normalized view,
then exact versioned Unicode/case/whitespace/terminal-punctuation normalization.
It never guesses missing words or splits fused words within a segment. The public phrase
corpus is validated, including `fresh apples`. Existing calibration summaries and accepted
samples remain compatible; use `app.owner.cli resume --profile <existing-profile-UUID>`
to inspect progress, then the existing consented `owner` command to continue. Do not reset
calibration for this correction. See decision 0013 for the reproduced defect and limits.


Calibration consent is completed before challenge issuance. The unchanged 45-second
challenge window starts after phrase display; waiting for Enter, capture and STT remain
bounded by it. Expiry is rechecked immediately before recording. An expired non-owner
attempt preserves accepted owner samples: retry `app.owner.cli nonowner` with the same
profile, participant pseudonym and environment, completing both consents again. Do not
restart calibration or extend expiry. See decision 0013 for timing limits and fake-clock
regressions; cold model/STT latency can still cause expiry.


For a safe fake-only timing/reuse report, run
`python -B -m app.owner.cli evaluate-timings` with the existing venv. For later deliberate
manual calibration or voice-pilot testing, append `--timings` to the existing command.
It prints numerical durations only, saves nothing and does not bypass consent or expiry.
Challenge/command share models within one process; separate CLI invocations start cold.
See decision 0013 for timing interpretation and the unchanged security boundaries.


## Phase 6C: confirmation and synthetic security evaluation

The owner pilot now requires a separate speaker-verified `confirm` capture for volume
changes and approved launches. Reads skip that capture; each new command still needs
a fresh challenge. `cancel` causes no effect. Calibration remains mandatory and all
real controls remain default-off. Very short speech may fail unchanged quality gates.

Safe commands (no real profile, microphone, model or Windows action):

```powershell
.\venv\Scripts\python.exe -B -m app.owner.cli inspect-config
.\venv\Scripts\python.exe -B -m app.owner.cli confirmation-policy
.\venv\Scripts\python.exe -B -m app.owner.cli evaluate-usability
.\venv\Scripts\python.exe -B -m app.owner.cli evaluate-threats
.\venv\Scripts\python.exe -B -m app.owner.cli evaluate-timings
.\venv\Scripts\python.exe -B -m app.owner.cli evaluate-all
```

Synthetic timings are injected seconds, not hardware benchmarks. Clone/virtual-input
labels do not imply detection: high-similarity stress inputs can pass. No thresholds
or protected calibration schema changed. Existing pending calibration remains blocked.
See [decision 0014](docs/decisions/0014-voice-pilot-usability-security-and-confirmation.md)
for evidence bindings, exact metrics, limitations and remaining user-only calibration.


## Phase 6D local session/API foundation

The local frontend boundary is disabled by default and supports labelled synthetic
demos only. Real voice session creation remains calibration-blocked without reading
a profile. No frontend, TTS, wake word or new native action is included.

```powershell
.\venv\Scripts\python.exe -B -m app.api.cli inspect-config
.\venv\Scripts\python.exe -B -m app.api.cli routes
.\venv\Scripts\python.exe -B -m app.api.cli capabilities
.\venv\Scripts\python.exe -B -m app.api.cli evaluate-demo
# User-only demo server; never starts capture or opens a browser:
$env:VOICEPILOT_API__ENABLED = 'true'
.\venv\Scripts\python.exe -B -m app.api.cli serve
```

Default API: http://127.0.0.1:8765/api/v1; frontend origin: http://127.0.0.1:5173.
Mutations require JSON, the allowed Origin and X-VoicePilot-Request: 1. Events/history
are bounded in memory; transcripts hidden by default. Emergency-stop reset requires
a process restart. This single-threaded development adapter is not a production server.
See [decision 0015](docs/decisions/0015-review-ready-unified-session-and-api.md) for exact
routes, request bodies, scenarios, privacy limits and the Phase 15A frontend contract.
