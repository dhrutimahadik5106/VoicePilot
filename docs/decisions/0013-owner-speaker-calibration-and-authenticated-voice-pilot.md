# 0013: Owner speaker calibration and authenticated voice pilot

Status: Phase 6B.1 implementation; real owner calibration and voice execution are
USER-ONLY manual validation. No owner profile, microphone or real model was accessed
while implementing or automatically testing this phase.

## Existing-system audit and compatibility

The existing Phase 4B stack is WeSpeaker ResNet34 through pinned sherpa-onnx 1.13.8,
256-dimensional normalized embeddings, mono contiguous float32 prepared from 16 kHz
PCM16, and cosine similarity. Numerical quality defaults are 3..30 seconds, RMS at
least .005, clipping at most .01; enrollment takes four samples (range 3..5), requiring
pairwise similarity >= .7. Existing acceptance/review thresholds are unset until
protected approval. The model identity binds revision, publisher checksum,
preprocessing and dimension. Model construction/inference is lazy and local-only.

Schema-1 owner profiles contain exact template bytes, enrollment session and waveform
provenance, timestamps, model identity and policy version. Existing current-user DPAPI
protects the entire file with integrity checking and restrictive owner/SYSTEM ACLs.
The existing research workflow requires 20 genuine/20 impostor trials, three impostors
and separated cohorts. Its frozen-policy files, approval rules and profile format are
unchanged. Existing enrollment, profile deletion and synthetic speaker tests remain.

This phase adds a SEPARATE personal owner-pilot protocol in `app.owner`. It neither
migrates nor rewrites the existing profile, nor turns its historical calibration flag
into authorization. An old `pending` profile can support the new pilot only after the
new independently protected owner-calibration record meets all requirements. Old
speaker/diagnostic CLI paths retain their old policy requirements. The new authority
is not accepted by the fake execution controller, and diagnostic/simulator output is
not accepted as authentication evidence.

## Calibration protocol

Closed states: not_enrolled, enrolled_uncalibrated, collecting_owner_validation,
owner_validation_complete, collecting_impostor_validation, collecting_owner_holdout,
replay_challenge_pending, evaluating, calibration_failed, calibration_inconclusive,
calibrated, suspended, revoked. Missing enrollment/calibration are status projections;
collection requires a valid existing profile. Invalid transitions fail closed.

Minimum evidence for this personal pilot:

- 8 accepted fresh owner development samples, at least three distinct prompted phrases,
  and both quiet and different_environment groups.
- 20 accepted consenting non-owner trials, at least three stable UUID pseudonyms, both
  environment groups. These are consent declarations, not proof of different people.
- Freeze thresholds BEFORE collecting four fresh owner holdout samples. Holdouts must
  use both environments and all must be accepted by the frozen policy.
- Three simple wrong-phrase challenge tests, each with an owner speaker match and an
  expected phrase rejection. This exercises the phrase gate; it is not a replay-detector
  benchmark or a claim that prerecorded or cloned correct phrases are detected.
- Explicit evaluation and then approval. Typing consent cannot bypass evidence checks.

Each trial has a fresh session and capture ID. Enrollment waveform digests and all
accepted development/holdout/replay digests are rejected as duplicates. Holdouts never
retune thresholds. Quality failures, invalid/nonfinite/wrong-size embeddings, phrase
mismatches and cancelled acquisitions do not enter calibration distributions. Rejected
acquisitions have no persisted audio or per-trial score. A contradictory distribution
or failed holdout requires a new explicitly consented calibration, not a weaker retry
threshold. Repeatedly recollecting until favorable results introduces selection bias;
this workflow makes no population-security claim.

Threshold A is max(configured acceptance floor .80, rejection floor .70 + band .10,
minimum owner score minus .02, maximum non-owner score + band + .02).
Threshold R = A - band. If A exceeds 1 or any development owner lies below A or any
non-owner reaches R, calibration is inconclusive. Scores >= A are accepted; R <= score
< A yields retry_or_uncertain; lower scores are rejected. Similarity is NEVER probability,
calibrated confidence or STT confidence. Threshold settings are engineering floors,
not a substitute for evidence. Counts, min/max/sum and outcome totals are encrypted;
public results expose count/outcome denominators, not scores or exact thresholds.

## Challenge, capture and authentication

Twelve closed neutral English phrases form owner-phrases-v1. A cryptographically random
selection is made immediately before each deliberate capture. The public phrase is
not a password. A one-use handle binds the exact phrase and session, expires after
45 seconds (including the Enter wait and STT), and cannot be substituted or replayed.
The same capture is quality-checked, embedded and transcribed, with audio-ID and waveform
integrity checks. Only punctuation/case/whitespace normalization is used for phrase
matching; fuzzy phrase acceptance is forbidden.

Mono 16 kHz PCM16, existing duration/RMS/clipping gates, at least 1.5 seconds of active
20 ms energy frames and >=40% active frames are required. Existing decoder VAD duration
must also meet 1.5 seconds when metadata is available. Energy activity is a conservative
proxy, not a speech, overlap or liveness classifier. Existing VAD/model thresholds are
unchanged. Brief commands such as a quickly spoken "Mute" can fail this gate; do not
weaken it just to obtain a successful manual test. Multilingual phrases, accent accuracy,
short-command usability and genuine acceptance require separate empirical validation.

The separately enabled pilot preflights protected calibration before capture or model
loading. It captures and verifies the challenge, issues an opaque private one-use nonce,
then prompts for a SEPARATE command capture. The command speaker is verified again
before command STT. The selected input device index and device metadata must match
within the capture session. This does not attest to physical hardware or defeat virtual
input. Challenge and command buffers/transcripts are never merged or saved.

Authentication ledger binds profile UUID/provenance, protected calibration revision,
policy/model versions, capture session and ID, challenge ID/result, timestamp, expiry,
nonce and the owner-pilot-v1 capability class. TTL is 60 seconds; inactivity deadline is
30 seconds from authentication. One command only, with no session extension. Admission
adds the exact command capture ID/digest and complete typed plan/arguments. Nonces are
consumed even on failed admission. Profile/calibration/model changes, expiry, cancellation
and emergency stop invalidate use. Current protected provenance is rechecked at controller
guards, including immediately before native effects. Already-completed effects are not
undone. Synthetic model identities require explicitly fake backends in both the pilot and
controller guard. Missing or non-boolean synthetic-authority metadata denies access;
backend identity is checked again at each guard. Denied Notepad requests do not invoke
backend cleanup. Regression tests cover both controller boundaries and zero capture/STT
after preflight mismatch. The production CLI uses only the pinned real engine. Python
interfaces are trusted process code, not a sandbox against malicious Python.

## Closed pilot policy and existing controllers

Allowed: Notepad, Calculator and safely discovered Chrome launch; volume read, fixed-step
increase/decrease, exact integer set, mute, unmute; brightness read; stop and cancel.
The resolver matches complete deterministic commands only. Compound/negated commands,
extra paths/arguments, ambiguous percentages and every other capability fail closed.
The built plans are existing LaunchPlan or operations.Plan; they do not dynamically choose
functions or adapters. The pilot permit constructors require a one-use admission produced
by the actual Pilot pipeline; booleans, diagnostics, synthetic authority and supplied plans
cannot mint a permit. Controller plan binding and independent observation remain mandatory.

Read-only commands need owner authentication. Allowlisted low-risk mutations use owner
authentication plus exact typed plan binding and existing policy. They do not require a
separate typed mutation confirmation in this pilot. Starting the CLI explicitly warns of
real authenticated execution. The launch real-execution flag and operations enabled flag
remain separate default-off gates. Screenshots stay manual and individually confirmed;
the pilot cannot capture/delete them. Brightness mutation stays unsupported. Spotify,
arbitrary apps, file/folder actions, closing/killing, browser automation, communication,
input simulation, Wi-Fi, lock/shutdown/restart, TTS and all later phases are excluded.

## Protection, consent and lifecycle

Before collection the CLI explains purpose, data, private locations, no audio saving,
cancellation and deletion. Enter starts EACH recording; other input, c during recording
or Ctrl+C cancels. Non-owners give an additional explicit consent for EACH trial. No
calibration or evaluation command executes a Windows action. Default calibration and
pilot flags are false. Raw audio saving is fixed false with no optional save path.

New summaries are UUID-selected `.owner-calibration` files under
`LOCALAPPDATA/VoicePilot/owner-calibration`, outside repository/OneDrive, never user-selected
CLI paths. They use existing current-user DPAPI with no plaintext fallback, restrictive
ACL provisioning, bounded/schema-validated decryption, ciphertext-only temporary files,
fsync and atomic replacement. Revision checks reject stale updates. Failed atomic updates
preserve the previous valid record. Do not run concurrent calibration/review processes;
this is not a cross-process transaction database or anti-rollback secure counter.

Persisted data is limited to binding/configuration digests, model/profile identifiers,
version/state/timestamps, a consent ID, aggregate distributions/outcomes, environment and
phrase IDs, pseudonymous non-owner identifiers and capture/session/waveform reuse IDs.
No audio, transcript, raw phrase, embedding or non-owner template is persisted. Digests
are non-secret integrity/reuse identifiers, not encryption or identity proof. Private
record/result fields are excluded from ordinary repr and serialization. General CLI and
execution history expose no similarity scores, profile paths or biometric provenance.

Suspend denies immediately; reevaluation and explicit approval are required to resume.
Revoke denies and requires a new calibration. Explicit selected deletion first revokes,
then deletes the owner profile and its new calibration record; failure remains denied.
Legacy experimental trial/policy files are not silently erased; they cannot authorize a
missing profile. Old backups/copies cannot be erased by this command. Re-enrollment changes
profile provenance, invalidating old owner calibration without overwriting it. Failed
re-enrollment preserves the existing profile and matching approval. No silent migration.

DPAPI does not protect against compromised same-user processes, OS administrators or
restored old ciphertext under the same account. Temporary Python copies are not guaranteed
securely erased. Random phrases resist some simple wrong-phrase replay, not advanced replay,
voice cloning, virtual-device injection or compromised OS capture. Correct-phrase replay
may pass; repeated phrases remain possible. No population FAR/FRR is claimed. High-risk
future actions require separate approval and confirmation, not this owner identity alone.

## Tested manual command syntax (USER ONLY)

Run from the repo using the existing venv. Use your existing profile UUID; do not commit
it or any outputs. These command forms are tested with fakes; no real calibration was run.
No dependency or model download is performed; existing pinned local models must be present.
Do not change the old SPEAKER__CALIBRATION_STATE flag to bypass the new workflow.

```powershell
$vp = ".\venv\Scripts\python.exe"
& $vp -m app.owner.cli inspect-config
& $vp -m app.owner.cli privacy
& $vp -m app.owner.cli evaluate-synthetic
$profile = Read-Host "Existing owner profile UUID"
& $vp -m app.owner.cli status --profile $profile
$env:VOICEPILOT_OWNER__CALIBRATION_ENABLED = "true"
& $vp -m app.owner.cli begin --profile $profile
& $vp -m app.owner.cli resume --profile $profile
# Each invocation below captures ONE sample, only after consent and Enter.
& $vp -m app.owner.cli owner --profile $profile --environment quiet
& $vp -m app.owner.cli owner --profile $profile --environment different_environment
# Repeat individually to obtain >=8 samples and >=3 prompted phrases across both groups.
$participant = Read-Host "Consenting non-owner pseudonymous UUID"
& $vp -m app.owner.cli nonowner --profile $profile --participant $participant --environment quiet
& $vp -m app.owner.cli nonowner --profile $profile --participant $participant --environment different_environment
# >=20 trials total, >=3 consenting non-owners; preserve each participant's UUID.
& $vp -m app.owner.cli freeze --profile $profile
& $vp -m app.owner.cli holdout --profile $profile --environment quiet
& $vp -m app.owner.cli holdout --profile $profile --environment different_environment
# >=4 fresh holdouts across both groups; all must pass frozen policy.
& $vp -m app.owner.cli replay --profile $profile --environment quiet
# Repeat individually for >=3 wrong-phrase gate trials.
& $vp -m app.owner.cli evaluate --profile $profile
& $vp -m app.owner.cli results --profile $profile
& $vp -m app.owner.cli approve --profile $profile
```

Consent is exactly `CONSENT BEGIN`, `CONSENT OWNER`, `CONSENT NONOWNER`, etc. Non-owners
also type `I CONSENT TO THIS TRIAL`. `resume` reports committed progress; it does not
start capture or reactivate a suspended record. Successful samples survive cancellation.

Only after calibrated status, explicitly enable the pilot and the desired real adapter:

```powershell
$env:VOICEPILOT_OWNER__PILOT_ENABLED = "true"
$env:VOICEPILOT_SPEAKER_VERIFICATION_ENABLED = "true"
$env:VOICEPILOT_OPERATIONS__ENABLED = "true"
$env:VOICEPILOT_LAUNCH__REAL_EXECUTION_ENABLED = "true"
& $vp -m app.owner.cli voice-pilot --profile $profile
```

Type `CONSENT VOICE-PILOT`, then Enter for the challenge, speak the displayed phrase,
then Enter for one command. Start with "What is the volume?" or "What is the brightness?".
Test one volume step next, then an explicitly intended launch; each new command needs a
new challenge. Unsupported commands deny. Do not mistake synthetic tests for biometric
calibration success. Very short or noisy commands may correctly return quality failure.

```powershell
& $vp -m app.owner.cli suspend --profile $profile
# Explicit reevaluation and approval can reactivate a still-compatible suspended record.
& $vp -m app.owner.cli revoke --profile $profile
& $vp -m app.owner.cli delete --profile $profile
# Deletion requires exactly: CONSENT DELETE <profile UUID>
$env:VOICEPILOT_OWNER__PILOT_ENABLED = "false"
$env:VOICEPILOT_OWNER__CALIBRATION_ENABLED = "false"
$env:VOICEPILOT_OPERATIONS__ENABLED = "false"
$env:VOICEPILOT_LAUNCH__REAL_EXECUTION_ENABLED = "false"
```

## Validation and next-phase limits

Tests use generated PCM, fake embeddings/STT, in-memory repositories, fake protection
with temporary directories, fake Windows backends and active integration guards.
Synthetic evaluation deliberately includes a high-similarity impostor acceptance and
uncertain genuine/non-owner cases to expose matcher limitations; it is not population
biometric-security evidence. No real microphone, profile, DPAPI profile decryption,
model load/download or Windows effect is part of automated validation.

A separately approved Phase 6C could assess owner pilot usability, cold-model timing,
short-command quality, replay/cloning threats and stronger additional confirmation.
No Phase 6C implementation, speaker enrollment/calibration or real voice test was run.


## Completed automated validation

Existing Python 3.12.10 venv preserved; no dependencies changed. All pytest commands
below used `.\venv\Scripts\python.exe -B -m pytest`:

- Baseline `-q`: 1571 passed before edits.
- Final `tests/owner tests/launch tests/operations -q`: 491 passed (133 owner, 358 compatibility).
- Final combined `tests/speaker tests/owner/test_calibration.py tests/owner/test_storage_quality.py tests/execution tests/planning tests/pipeline tests/stt tests/commands -q`: 1060 passed.
- Pilot/challenge/replay/runtime tests are included in the final affected and complete suites.
- Final `-q -k "privacy or leakage or sensitive or guard or side_effect or import or config"`: 188 passed, 1516 deselected.
- Final complete `-q`: 1704 passed.
- Guarded import/AST/config smoke: 12 owner modules passed.
- `python -B -m pip check`: no broken requirements.
- `git diff --check`, private-summary ignore checks and config/evaluation CLI smoke passed.

Synthetic evaluation denominators: genuine accepted 2/4, uncertain 1/4, rejected 1/4;
non-owner accepted 1/4, uncertain 1/4, rejected 2/4; replay/challenge rejection 4/4;
expired evidence rejection 1/1; authorization bypasses 0/3; execution after failed
authentication 0/6; privacy violations 0/14; fake-only enforcement 14/14. The non-owner
acceptance is an intentional high-similarity stress case, not a measured person or a
claim of biometric safety. No real microphone/profile/model or Windows action was used.

Normal pilot output includes independently verified volume/mute/brightness readings
and closed application IDs when applicable. Private command text, plan authorization
handles and biometric evidence remain excluded from normal output. Ctrl+C discards
outstanding evidence and returns cancelled.


## Phrase-verification correction

Code-level root cause reproduced with synthetic segmented STT: `raw_transcript`
concatenates segment text verbatim, whereas `normalized_transcript` trims and joins
segment boundaries with spaces. Owner verification previously compared the raw view.
Segments ending in `fresh` and beginning with `apples` therefore produced a false
`phrase_mismatch`; the normalized diagnostic view correctly retained `fresh apples`.
Both the flowers and apples regressions failed before the correction and pass after it.
Raw STT remains unchanged. Verification now consumes the same normalized STT view used
for diagnostic display, with no refinement, inferred spaces or semantic matching.
A fused word within a single segment still fails.

`owner-phrase-normalization-v1` applies the same function to expected and recognized
text: Unicode NFC, case folding followed by NFC, leading/trailing and repeated whitespace
normalization, and removal of terminal ASCII `. , ! ? ; :` punctuation only. Non-whitespace
control/format characters are rejected; interior punctuation is not deleted. Exact full
phrase equality remains required. Missing, extra, reordered, partial, homophone and
command text fail. Inputs remain bounded to 300 characters. No transcript diagnostic,
new display option, persistence or audit field was added.

The complete checked-in corpus already contains `fresh apples` with the correct space;
no malformed entry was found. Pure validation at import and challenge construction
checks syntax, spacing, uniqueness and the pinned public corpus digest/order, rejecting
`freshapples` or other unreviewed changes. This digest is a regression identifier, not
authentication. The reported malformed on-screen prompt cannot be reproduced from the
current corpus; its cause remains unconfirmed without a separately consented observation.

Read-only code comparison found identical owner/diagnostic Faster-Whisper settings when
started from the same Settings: both use TranscriptionService, local-only model access,
and the existing model, contextual hints, language, beam, temperature and VAD settings.
A fake constructor parity test verifies this. The engine completes segment iteration and
output-safety processing before phrase verification. Owner capture pins mono 16 kHz,
disables silence-stop, and uses speaker.capture_duration (default 8s, bounded by 30s);
diagnostics use audio settings and --seconds (default 8s). These capture differences can
still affect real recognition or truncate a long utterance; they were not changed.
A separate successful microphone capture cannot prove what the earlier failed capture
contained. The supplied single-string flowers transcript already passes the old case/
whitespace/ASCII-punctuation matcher. Segment joining is a confirmed code defect, not
proof that every reported real failure had that cause.

Same-audio ID/digest, session, one-use challenge, expiry (including after STT), speaker,
quality, configuration and enrollment provenance checks are unchanged. No protected
record, profile, audio or model was opened. Existing owner-phrases-v1, schema and policy
binding inputs remain unchanged: there is no migration, reset or invalidation. A synthetic
seven-sample schema round-trip/resume test proves that mismatch leaves the entire record
unchanged and a subsequent matching eighth sample preserves all prior evidence IDs.
Use the existing CLI `resume` to inspect progress and `owner` to collect one further
sample with consent. Do not run `begin`, revoke, delete or change policy settings to apply
this maintenance fix. Real recognition, timing and the reported display remain user-only
manual validation; no claim is made about unseen private recordings.


Correction validation (existing venv, `python -B -m pytest`):

- `tests/owner -q`: 169 passed, including 36 new regressions.
- `tests/speaker tests/stt tests/pipeline tests/commands tests/launch tests/operations -q`: 1133 passed.
- `-q -k "privacy or leakage or sensitive or guard or side_effect or import or config"`: 188 passed, 1552 deselected.
- Complete `-q`: 1740 passed.
- Guarded configuration/corpus/import smoke, `python -B -m pip check` and `git diff --check` passed.
- Dependencies unchanged. All tests used generated inputs/fakes; no real biometric,
  model, microphone, calibration record or Windows action was accessed.
