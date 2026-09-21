# 0014: Voice-pilot usability, security evaluation and confirmation

Status: approved Phase 6C. No new native capabilities, dependencies or calibration
migration. Starting checkpoint: 116a2ba. Baseline: 1786 passing fake-only tests.

## Confirmation and authentication

Extend the existing owner Pilot, authorities and launch/operations controllers. A
fresh challenge remains required for each command. Challenge speaker acceptance now
precedes challenge STT in the pilot; the calibration collector intentionally retains
its separate non-owner measurement protocol. Command and confirmation speaker
acceptance also precede their respective STT calls. Each uses fresh inference on a
separate capture, with quality, waveform-integrity and STT audio-ID checks.

Volume/mute/brightness reads skip second confirmation. Volume steps, exact percentage,
mute/unmute and existing Notepad/Calculator/Chrome launches require a third capture.
Only case-insensitive, outer-whitespace-trimmed `confirm` or `cancel` is accepted.
Punctuation, synonyms, extra words, repeated words and compounds fail closed. This
strict engineering policy can reject a decoder-produced `Confirm.`; it does not
silently repair uncertain speech. The displayed confirmation uses only closed typed
capability/application values and an optional exact integer percentage, never raw STT.

A private, process-local pending request binds a fresh nonce, authenticated nonce,
session, profile/provenance, calibration revision, model, policy, challenge/capture,
command capture/digest, normalized-command digest, complete typed plan and arguments,
capability/target and owner-confirmation-v1. Existing canonical plan binding functions
include private arguments and launch identity. Confirmation expires at the earliest
of 30 seconds, the authentication TTL and inactivity deadline. It never refreshes or
extends authentication. Guards recheck the unchanged plan/context and deadline during
controller admission and immediately before effects. Failed attempts consume the
command authorization; confirmation requests are removed on every terminal path.
Hashes are integrity identifiers, not encryption or authentication. A boolean, string,
configuration flag or simulator result cannot substitute for captured evidence.

For launching, safe read-only discovery supplies the exact executable identity before
confirmation; failed confirmation never reaches launch/controller execution. Existing
held pre-launch revalidation and independent observation remain mandatory. A discovery
result alone is not success. Operation reads/mutations start only after required
confirmation. Existing default-off flags and fake-engine/native-backend separation stay.

Runtime pins the same device metadata for challenge, command and confirmation, rechecks
it on capture and in authentication guards, then releases the session entry on exit.
This is environment continuity, not proof that a device is physical. Expired, reused,
substituted or uncertain evidence fails closed. One-use admission still feeds existing
controllers; no parallel execution pipeline or new action adapter exists.

Stop/cancel plans skip confirmation. Existing process-local cancellation may signal
active work immediately without obtaining new speech authentication. It cannot cancel
another CLI process, interrupt a blocking native call, close an application, or undo
an already completed effect. There is no background listening to hear a stop command.

## Quality and timing

Existing 3-second minimum buffer, 1.5-second active audio and other quality/STT gates
are unchanged. A brief `mute`, `confirm` or `cancel` may be rejected. Synthetic sine
buffers paired with fake transcripts demonstrate routing, not human speech recognition.
Silence and truncated generated buffers exercise the actual unchanged quality gate.
No threshold tuning, model change or fabricated real short-command accuracy is claimed.

Optional in-memory timing uses monotonic perf_counter and bounded closed stage names.
It covers runtime construction, model initialization, challenge preparation/capture/
speaker/STT, command and confirmation capture/speaker/STT, planning, authorization,
execution, observation/verification and total session. Existing `capture` and
`phrase_stt` names identify challenge capture and phrase STT. `authorization` includes
waiting for confirmation. Command/confirmation capture spans include user wait/setup;
`command_recording`/`confirmation_recording` isolate recorder activity. Spans nest and
must not be summed indiscriminately. Unreached stages are absent. `completed` means the
instrumented call returned, not that identity or execution was accepted.

Speaker/STT engines remain lazy, cached within one Runtime, local-only, with fresh
inference per capture. No model loads on import or early denial. The timing evaluator
runs two sessions through the same fake engines: one simulated cold initialization
and warm reuse, six captures/speaker calls/STT calls, and four volume reads. Durations
are injected seconds, not measurements or speed claims about any machine. Production
cold model and recorder setup latency can still exhaust the unchanged deadlines.
Timing reports contain only fixed labels, finite durations, temperatures and booleans;
no transcript, phrase, identity, score, embedding or path, and no persistent database.

## Evaluation and limitations

Typed source-defined cases use generated audio, in-memory synthetic profiles and fake
STT, engines, clocks and backends. Evaluation commands accept no real profile parameter
and construct no Runtime. Owner test guards deny native DLLs, process creation, devices,
models, network and filesystem access outside pytest temporary directories.

Usability has 22 cases: 13 valid exact resolutions and nine rejected cases including
silence, truncation, repetition, unknown/ambiguous apps, compound/unsupported requests,
challenge text as command and speaker substitution. Report exact numerator/denominator
pairs; do not interpret these developer fixtures as WER, user success or population
accuracy. Threat evaluation has 14 labelled scenarios: 11 enforceable stale/replay/
substitution/speaker violations, plus three deliberate high-similarity/clone/virtual
stress acceptances. Four fabricated-authority and five missing/invalid confirmation
attempts are additional metrics with their own denominators.

Correct fresh phrases from high-similarity impostors or spoofed inputs may pass.
Cloned-voice/virtual-audio labels carry no detection authority. Exact waveform duplicate
rejection is bounded and process-local for pilot attempts; re-encoded replay, old
process replay, unobserved recordings and convincing synthetic voices remain risks.
This is not anti-spoofing certification. Private Python process internals are trusted;
these are not distributed signed tokens or a sandbox against arbitrary Python code.

Protected owner schema, configuration hash inputs, phrase corpus, evidence counts,
thresholds and storage remain unchanged. Real incomplete calibration was not accessed.
Pending/absent/revoked/incompatible approval blocks before capture/model/STT. No raw
audio, transcript, confirmation speech, embedding or new diagnostic artifact is saved.
Public reports exclude protected identifiers. Python memory cannot guarantee erasure.

## Safe commands

All commands below are read-only metadata or fake-only, without a profile argument:

```powershell
.\venv\Scripts\python.exe -B -m app.owner.cli inspect-config
.\venv\Scripts\python.exe -B -m app.owner.cli confirmation-policy
.\venv\Scripts\python.exe -B -m app.owner.cli evaluate-usability
.\venv\Scripts\python.exe -B -m app.owner.cli evaluate-threats
.\venv\Scripts\python.exe -B -m app.owner.cli evaluate-timings
.\venv\Scripts\python.exe -B -m app.owner.cli evaluate-all
```

The existing interactive voice-pilot --timings flag remains opt-in and requires completed
protected approval. No real voice testing is part of this implementation. User-only
Phase 6B.1 work remains: retain existing eight owner samples, collect 20 non-owner trials
from at least three consenting adults across both environments, freeze, four fresh
holdouts across both environments, three wrong-phrase tests, evaluate and explicitly
approve if eligible. Follow decision 0013; do not restart enrollment or bypass evidence.

A later separately approved phase may design a local frontend over these contracts,
with explicit capture/confirmation and observable denied states. Capability expansion
requires a new threat review, narrowly typed plans, independent observation, suitable
additional factors for higher risk and empirical user-led validation. No frontend,
Spotify control, browser automation, screen perception, TTS, wake word, permanent
history, LLM integration or new Windows operation is implemented here.


## Completed validation

Existing venv, no dependency changes. Commands used `venv\Scripts\python.exe -B`.

- Baseline `-m pytest -q`: 1786 passed.
- `-m pytest tests/owner/test_confirmation.py tests/owner/test_security_evaluation.py -q`: 76 passed.
- `-m pytest tests/owner tests/speaker tests/stt tests/commands -q`: 993 passed before four final expiry/replay regressions; all are included in the final full suite.
- `-m pytest tests/execution tests/planning tests/pipeline -q`: 315 passed.
- `-m pytest tests/launch tests/operations -q`: 358 passed.
- Privacy/leakage/sensitive/guard/side_effect/import/config selection: 196 passed, 1666 deselected.
- Final `-m pytest -q`: 1862 passed.
- `-m pip check`: no broken requirements.
- Guarded AST/import smoke: 16 modules; six inspection/evaluation CLI commands passed.
- Baseline AST comparison: Configuration, PrivateDocument, Record and policy_binding unchanged (4/4).
- Diff whitespace and four private-artifact ignore checks passed.

Usability: exact resolution 13/13, safe rejection 9/9, expected outcome 22/22, false
execution 0/22, privacy violations 0/22, fake-only 22/22. Threats: enforceable rejection
11/11, false execution for those cases 0/11, replay rejection 3/3, fabricated authority
bypass 0/4, confirmation bypass 0/5, confirmation enforcement 5/5. Challenge-before-STT,
command-speaker and confirmation-speaker rejection checks each passed 1/1. Privacy
violations 0/14 and fake-only 14/14. Deliberate spoof-labelled stress acceptance 3/3:
three of fourteen adversarial cases produced fake effects. Do not omit this limitation
when presenting the other zero-bypass numbers.

Timing: two verified fake sessions, six distinct captures and fresh speaker/STT calls,
one initialization per fake model, four volume reads. Injected session totals were
6.410 seconds cold and 4.910 seconds warm; these are not hardware performance results.
No real biometric, microphone, model, screenshot, application or Windows action occurred.
