# Project working rules

- Preserve Python 3.12.10 and the existing venv. Explicitly use
  venv\Scripts\python.exe for every Python or pip command; do not rely on activation.
- Never install, remove or upgrade packages without authorization.
- Phases 1-3 are approved: foundation, explicit audio input and local STT.
  Never implement Phase 4 or later without separate approval.
- No wake word, speaker verification, LLM reasoning, LangGraph, computer control,
  command execution, browser/screen automation, history database, API or frontend.
- Treat recognized speech as text only. It must never execute commands.
- Microphone capture requires deliberate action. No continuous listening,
  startup recording or hardware/model access during imports/settings loading.
- Keep audio/transcripts in memory by default. STT must not persist recordings.
  Cancellation discards results; future speaker enrollment needs separate consent.
- Never log raw audio, transcripts, embeddings, credentials, sensitive paths or
  internal exception text. Use safe codes and suppress backend transcript logging.
- Recognition runs locally. Only an explicit real transcription may download model
  assets. Document first-use downloads and the cached-files-only setting.
- Do not automatically perform manual microphone, download or transcription tests.
- Automated STT tests must use fakes/mocks; no real model load, download, network,
  hardware, applications, personal-file access or system-setting changes.
- Generate WAV fixtures only in pytest temporary directories.
- Preserve ignored recordings/models and never create a real .env or credentials.
- Declare only direct dependencies; do not use pip freeze for project metadata.
- Run complete and phase-specific pytest, import/settings smoke tests, diff and
  ignore checks. Stop on failed baseline or repository/authentication safeguards.
- Phase 2 hardware and initial Phase 3 transcription are user-tested; accuracy
  mistakes and a slow first run were reported. Refinement hardware tests are pending.
  Never fabricate accuracy, WER, benchmarks or hardware/model verification.

- Phase 3 refinements permit optional fixed duration, Enter-to-stop capture,
  optional silence stop, a configurable 120s safety maximum, and explicit sessions.
- Never remove the finite recording cap or save audio automatically.
- Keep small/cpu/int8 as the default for this 16 GB laptop; no medium/large or GPU
  migration is authorized.
- Vocabulary is a decoding hint, not permission to rewrite arbitrary speech.
  Preserve raw and normalized transcript forms; normalization only joins/strips
  segment-boundary whitespace and never substitutes recognized words.
- Separate model-load/download time from inference. Label cold/warm only by
  whether the engine constructed/reused its model. Do not claim measured speedups
  from fake-clock tests.
- Reuse the model within a session; request fresh capture consent for each turn.
- Document silence/VAD cutoff risks, multilingual limitations and uncertain
  accuracy. Do not automatically run real microphone/model/performance tests.

- Phase 3B is approved only for text-domain interpretation and dataset foundation.
  It must never execute proposals, open applications, control media or read
  personal files. No speaker verification, LLM, history or frontend work.
- Preserve raw transcript exactly. Command matching normalization is separate
  from STT normalization; canonical command is a third, proposed value.
- Resolver scores are heuristic match scores, never probabilities, calibrated
  confidence, STT confidence or authorization.
- Tharism Infer is a user-observed ASR error for Taare Zameen Par, not a
  pronunciation. It always requires confirmation; fuzzy/ambiguous/unknown,
  negated, incomplete or compound requests must not be silently accepted.
- Keep vocabulary independently defined. Do not derive aliases from every seed
  sentence or repeatedly tune rules to perfect development scores.
- Label the seed synthetic development/test text, not research training data.
  Report metric numerators, denominators and percentages, coverage and false
  acceptance. No fabricated recording, result or publication claim.
- Future audio collection requires separate consent, restricted identity mapping
  and speaker-disjoint train/validation/test splits. Collect no audio in 3B.

- Phase 3C permits only centralized STT output safety in app/stt/output_safety.py.
  Apply the same policy to all service engines; engine code may collect metadata
  and enforce output budgets. Never duplicate independent rejection rules.
- Reject whole unusable outputs with empty public transcripts and status
  unusable_audio. Never remove repetitions to salvage a command.
- Discard rejected decoder text, including private diagnostics. Retain only bounded
  numerical evidence; no rejected text in repr, serialization, CLI, logs or resolver output.
  Cancellation discards diagnostics; never save rejected audio or text.
- Block every non-successful STT status from resolution. Explicit text input
  bypasses STT provenance. No command execution or Phase 4 is authorized.
- Safety thresholds are unvalidated engineering defaults. Use synthetic/fake
  tests only; document false rejection/acceptance risks and never fabricate
  research performance. See docs/decisions/0005-stt-output-safety.md.

- Phase 3C numerical diagnostics are approved without changing acceptance rules.
  --safety-diagnostics may show only the allowlisted SafetySummary on rejection.
  Preserve reason codes and bounded numerical evidence before sanitization.
  Never display, log or serialize private decoder text. Cancellation clears both
  numerical and private diagnostics. Wait for manual evidence before policy changes.

## Phase 4A authorization

Phase 4A supersedes earlier blanket prohibitions on speaker foundation work only.
Fake-backed speaker contracts, enrollment/verification, protected-storage boundaries,
a fail-closed STT gateway and synthetic evaluation are approved. No runtime/model
installation, microphone/recordings access, real profiles, execution or Phase 4B.
Keep real inference/protection unavailable; never fall back to plaintext. All
speaker tests use generated PCM, fake engines/protectors and temporary directories.
No synthetic or pending policy authorizes the gateway. Preserve Phases 1-3E.


## Phase 4B authorization

Phase 4B supersedes prior runtime/protector prohibitions only for approved WeSpeaker
ResNet34 through sherpa-onnx 1.13.8 and Windows current-user DPAPI. Explicit pinned
model provisioning and non-biometric platform smoke checks are approved. No real
microphone/enrollment or existing recording inspection is permitted during automated
work. Preserve the venv and unrelated dependencies. Protect complete private records
outside Git/OneDrive; never fall back to plaintext. Calibration approval must bind
all selected evidence to the current profile/enrollment/template/model/schema. Missing
or stale provenance fails closed; re-enrollment revokes earlier authorization. Tests
use synthetic inputs/fakes. No later phase or execution is authorized. See decision
0008 for manual boundaries, privacy limits and validation requirements.


## Phase 5A authorization

Phase 5A permits deterministic typed task planning, a closed capability/risk registry,
expiring plan-bound simulation confirmations and non-executing observation/recovery.
It also permits explicitly named unauthenticated text/voice diagnostics and authenticated
inspection through the existing Phase 4B verifier and protected-policy boundary.
Missing/pending calibration blocks before STT; never imitate verification with a
computed-and-discarded score. No threshold/calibration or biometric profile changes.

No real browser/application/input control, live network search, LLM, generated shell/
Python execution, user-document access, permanent history or Phase 5B is authorized.
Every plan/step/result remains simulation-only with execution_permitted=false.
Search/research remains unsupported unless the existing resolver validates that intent.

Audio/trace persistence requires explicit invocation flags and per-operation consent.
Private text display requires --show-transcript; text-containing saves require explicit
approval. Only allowlisted diagnostic fields may be saved outside Git/known sync roots;
never embeddings, similarity, profile/provenance data, credentials or decoder segments.
Use UUID filenames, size/duration bounds, atomic writes and no overwrite. Never commit
or upload artifacts. No real microphone/model/profile/recording access during automated
Phase 5A work. Use synthetic/fake inputs and temporary directories; preserve all prior
phases and dependencies. See decision 0009 for exact CLI, privacy and testing limits.


## Phase 5B authorization

Phase 5B permits controlled-execution foundation using in-memory fake adapters only.
Production execution stays globally disabled. No dynamic imports from plans, arbitrary
paths/code/URLs, subprocess, browser/application/input control or network adapters.
Only exact synthetic fixture/evidence types enter the fake controller; diagnostic plans,
simulator results and plain booleans never grant authority. No real speaker issuer,
profile/model/microphone access or calibration changes are approved in this phase.

Preserve exact plan/step/argument/policy/evidence binding, expiry, single-use evidence,
prohibited-action blocking, independent observation/verification, bounded retries,
idempotency, cancellation and emergency stop. Never claim rollback without observing
restored state. Audits are private-field-free, in memory only. Tests actively block real
integrations and file access. No dependency installation or Phase 6A is approved.
See decision 0010 for the fake-only boundary and future production prerequisites.


## Phase 6A authorization

Phase 6A supersedes earlier launch prohibitions only for the closed Windows adapter:
Notepad, Calculator, safely discovered Chrome and Spotify; one app, no arguments,
elevation, shell, arbitrary paths, protocols, scripts or shortcuts. Require held
identity revalidation, exact expiring single-use consent and independent OS observation.
Manual operator tests must be labelled as not voice authentication. Production stays
default-off; pending calibration blocks before capture/STT/execution. Never perform
real launches, microphone/model/profile tests during automated work. Use fakes and
active side-effect guards. No close/kill, playback, browser/input automation or Phase
6C. Phase 6B now follows decision 0012 below. Preserve prior work and dependencies.


## Phase 6B maintenance boundaries

Follow decision 0012. `app.operations` is a separate closed typed manual operations
boundary; never route diagnostics or simulated plans to it. Keep controls/screenshots
default off, native brightness mutation unsupported, and pending-calibration voice
denied before capture/STT. Tests must use fakes and temporary storage; never perform
real mutation, capture, launch or device/model/profile access. Preserve exact consent,
single-use argument binding, independent observation, process-local cancellation and
bounded privacy-filtered history. No dependencies were added for this phase.
