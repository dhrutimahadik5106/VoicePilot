# 0012: Controlled Windows basic operations

Status: accepted for Phase 6B; real hardware mutation has not been manually validated.

## Boundaries and policy

The closed `6b-v1` operations registry contains volume read, mute read, increase,
decrease, exact set, mute, unmute; brightness read, increase, decrease, exact set;
screenshot capture and selected deletion; cancel, emergency stop and session history.
One typed action is allowed per request. Basic plans remain non-executable data;
Phase 5A diagnostic plans and Phase 5B simulated plans cannot enter this controller.
The separate operations driver reuses the Phase 5B state machine and adapter boundary,
with a closed capability policy, single-use manual authority and filtered audit events.
It does not widen the application-launch registry or the simulated execution controller.

Reads are informational, volume/brightness mutations low risk, screenshot capture
and deletion privacy-sensitive, and stop/cancel safety operations. Every manual
mutation requires exact typed consent, including low-risk mutations. Real controls
and screenshots default off. Manual testing is a separate gate, not authentication.
Authorization binds the action, version, step, capability and exact typed arguments;
it expires after 30 seconds and is consumed once. Changed plans and replay fail closed.
A SHA-256 binding is an integrity identifier, not encryption or proof of identity.
No confirmation flags, piped approval, arbitrary paths, adapter names or compound
commands are accepted. The registry declares zero retries and no automatic rollback.

## Windows APIs and verification

Standard-library ctypes calls fixed Windows APIs; no new dependencies are required.
DLL loading uses the Windows system directory search flag. No shell, subprocess,
keyboard simulation, network, user-selected COM class or input-driven WMI query exists.
Windows Core Audio IAudioEndpointVolume controls only the default multimedia render
endpoint. The endpoint identity is checked again before writing. An independent read
must observe the same endpoint, requested percentage within 0.5 percentage points,
and expected mute state. Fixed steps default to 5 percentage points and clamp to
0..100. Exact requested percentages are integers only. Setting/stepping volume
preserves mute state; mute/unmute preserves volume. Concurrent changes or endpoint
replacement prevent a verified success. Previous state is retained only in memory
for recovery reporting; restoration is never claimed without observation.

Brightness uses only the fixed ROOT\WMI query:
`SELECT CurrentBrightness FROM WmiMonitorBrightness WHERE Active = TRUE`.
Exactly one active interface is required; none, ambiguity or an unavailable probe
fails closed. External monitor support is not assumed. Native brightness mutation
always returns unsupported. Fake adapters exercise mutation, clamping and independent
verification without changing a display. No DDC/CI, legacy IOCTL or shell fallback.

Screenshot capture targets only the primary display using fixed GDI calls. Consent
explicitly covers both capture and saving. No OCR, image recognition or pixel-content
inspection occurs. Structural BMP validation checks encoding, dimensions and bounded
length. Independent storage observation is required before success. Files are UUID
named `*.vp-screen.bmp`, under Windows Known Folder LocalAppData at
`VoicePilot/diagnostics/screenshots`. The directory is fixed internally, outside the
repository and sync roots; network paths, junctions/symlinks and hardlinked artifacts
are rejected. Current-user/SYSTEM restrictive ACLs precede writing private bytes.
Temporary files are flushed and atomically published without overwriting. Git ignores
both final artifacts and temporary screenshot files. Results expose an artifact UUID,
not personal paths. No listing, arbitrary file access or full-path command is added.

Screenshots persist until the operator confirms deletion of one exact artifact UUID.
Deletion can remove a corrupt artifact in this controlled namespace. It is ordinary
filesystem deletion, not secure erasure. Cancellation after publication may leave an
artifact; the result retains its ID for explicit cleanup and does not claim reversal.
ACLs are access control, not encryption; the current user, administrators and malware
running as that user remain outside this process's protection boundary.

## Cancellation and history

The process-local hub registers operations, launch work, simulated execution,
recording, STT and diagnostic processing. Cancel signals current work; emergency stop
also latches denial of subsequent work in that process. It never kills processes,
closes applications or reverses completed effects. Nested cancellation registrations
remain active until the outer operation exits. Existing caller cancellation signals
remain supported. STT results are discarded after global cancellation; engines without
an original cancellation token may finish their current inference first.
Checks surround mutation and observation; deadlines are cooperative, not hard OS-call
preemption. A blocking native call may return after its deadline, then fail validation.
No automatic retry can repeat a screenshot or a step operation.

History is a bounded in-memory deque (100 entries by default, maximum 1000). It stores
only IDs, timestamps, closed capabilities/result codes, durations, fake/real,
confirmation-required and execution-permitted flags. No transcripts, arguments,
percentages, artifact paths/IDs, endpoint identifiers, audio or biometrics enter it.
A fresh CLI invocation has fresh history. `session` keeps one controller alive;
`stop`/`cancel` in another process cannot cancel it. No IPC or background listener is
implemented. The interactive session is bounded to 100 commands.

## Voice and command understanding

The future production path is preflight calibration gate, capture, speaker verification,
approved calibration policy, STT safety, deterministic resolver, typed planner, risk
policy, fresh authorization, adapter, independent observation, verification, response.
Both authenticated voice commands currently deny before capture/STT. Pending calibration
reports calibration_pending. Even a validated setting cannot enable production execution:
production_issuer_unavailable remains a denial. Manual tests are never voice authentication.
No profile or model is consulted by these status paths.

The exact English grammar includes increase/decrease volume or brightness, set volume
or brightness to an integer percent, mute/unmute, take a screenshot, stop, cancel and
what did you do? Missing/negative/multiple percentages, negations, compound commands,
extra actions, paths and injection are rejected. Resolver/planner support is explicit
through resolve_basic/build_basic; existing diagnostic behavior is preserved.

## Validation and limitations

The operations tests use fake Windows backends and temporary artifact stores. Guards
block real DLL loading, process creation, network, devices/models and filesystem writes
outside test temporary storage. Native contract tests replace COM functions with fakes.
The synthetic evaluator contains 16 valid operations, 11 rejected grammar requests and
10 authorization/observation faults. Categories overlap: report their denominators,
not a combined accuracy estimate. This is deterministic safety regression evidence,
not an empirical hardware or multilingual benchmark.

No real volume/brightness change, screenshot, microphone, profile/model access or
application launch is part of Phase 6B automated validation. Windows hardware behavior,
DPI/multi-monitor behavior, permission differences and native call timing still require
separately approved manual validation. No closing, playback, browser automation, mouse/
keyboard control, permanent history, screen perception or later-phase features exist.
A separately approved Phase 6C could first validate these hardware boundaries and design
production authorization after approved calibration; it must not infer that calibration
or enabling configuration is itself authorization.

References: [Core Audio scalar setting](https://learn.microsoft.com/en-us/windows/win32/api/endpointvolume/nf-endpointvolume-iaudioendpointvolume-setmastervolumelevelscalar),
[GDI capture](https://learn.microsoft.com/en-us/windows/win32/gdi/capturing-an-image).


## Completion validation

Using the existing Python 3.12.10 venv, baseline: 1411 passed. Final validation:

- `python -B -m pytest tests/operations -q`: 160 passed.
- `python -B -m pytest tests/launch tests/execution tests/planning tests/pipeline -q`: 513 passed.
- `python -B -m pytest tests/speaker tests/stt tests/commands -q`: 706 passed.
- Privacy/import/config/guard selection: 186 passed (before final additional tests).
- `python -B -m pytest -q`: 1571 passed.
- `python -B -m pip check`: no broken requirements.
- Guarded import/AST/config smoke: 14 modules; native loading/process creation blocked.
- `git diff --check` and screenshot ignore-pattern checks passed.
- Config, typed-plan and authenticated-denial CLI checks passed.
- Native read-only volume, mute and brightness status returned state_read_and_verified;
  mutation/capture entry points were patched to reject during these checks.

Synthetic evaluation: valid 16/16; invalid blocked 11/11; authorization bypasses 0/4;
confirmation bypasses 0/3; replay rejected 2/2; false success 0/26; unsupported correct
1/1; privacy violations 0/26; fake-only enforcement 26/26. No real mutation or capture
was performed. Manual mutation commands were exercised only with injected fakes.
