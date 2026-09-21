# 0015: Review-ready unified session and local API

Status: approved Phase 6D; no frontend or real server/hardware testing in this phase.
Checkpoint: 9b647f2. Complete baseline: 1862 passing tests. No dependency changes.

## Application boundary and state machine

SessionService owns bounded VoicePilotSession instances and current-process history.
The explicit transition table contains 21 public states. Normal progression is:

idle -> ready -> awaiting_activation -> listening -> authenticating -> understanding
-> [needs_clarification] -> planning -> risk_checking -> [awaiting_confirmation]
-> authorized -> executing -> observing -> verifying -> responding -> completed.

Every nonterminal state can fail closed to blocked, cancelled, timed_out, failed or
emergency_stopped. Terminal states have no outgoing transitions. One command per
session, serialized service operations, strict request IDs and bounded retention
prevent reuse. No frontend request supplies risk, a plan, adapter or biometric evidence.
Transitions emit ordered bounded events; clients detect dropped older events using
first_sequence/last_sequence. Full transition-matrix tests cover all 441 state pairs.

The API is a demo and metadata foundation. Creating production sessions always returns
calibration_blocked, without inspecting a profile. Status reports
calibration_inspected=false and production_available=false; it is not an assertion
that a protected record was read. Approval/configuration/quality requirements from
Phase 6B.1 remain unchanged. Even enabling the HTTP server cannot enable production.
A future reviewed production adapter is still required after eligible calibration.

## Explicit activation and synthetic pipeline

Creating a demo session does not capture. Activate enters listening; capture/stop ends
that explicit interval and runs only generated audio. Capture/cancel and task cancel
terminate the session. No import/startup/status capture, browser microphone, background
listener, wake word or keyboard hook exists. These frontend control contracts use the
existing owner capture/speaker/STT boundary with the synthetic Harness, not a second
biometric algorithm. Real frontend microphone routing is deliberately unavailable.

The demo adapter creates an in-memory synthetic calibration fixture, calls existing
owner authentication once, and uses Phase 6C speaker-before-command-STT and distinct
confirmation capture checks. Each command has one fresh challenge. UI confirmation
selects a synthetic response only, labelled synthetic_ui_demo; it cannot substitute
for speaker_verified_voice in production. The fake fixture setup is not user calibration,
model initialization or evidence about real speech accuracy.

Owner evidence never enters native launch/operations controllers. Launch effects use
the existing Phase 5B FakeAuthority/Controller.run_fake and independent synthetic
observation. Its fake-only application set now also includes Notepad and Calculator,
which were already typed supported applications; native allowlists are unchanged.
Volume-read demonstrations use independent reads of the existing FakeBackend. Every
public demo view, event, history entry, error and acknowledgement carries synthetic_demo,
simulation=true, execution_permitted=false, real_actions=0 and the DEMO banner.

Synthetic view stages project progress; synchronous stop/confirm requests can finish
several stages before the next poll. This is not a real streaming capture implementation.
The generated waveform is exactly eight coarse normalized levels, refreshed no faster
than four times per second while explicitly listening. It is unrelated to PCM and cannot
reconstruct audio. It clears at capture end/cancellation and is absent from history/events.
No browser or native audio data is returned or saved.

## Clarification, policy and display

Existing resolver data classifies `open browser` as needs_confirmation and includes
Chrome/Chrome Beta. Filtering to the existing owner-approved app IDs leaves Chrome
only; explicit selection is still needed because the original alias was ambiguous.
Never invent other candidates. Unknown requests with no safe candidates are blocked.
A clarification record binds original command digest, session, displayed candidates,
once-only request ID and expiry (default 30 seconds, capped by session deadline).
Substitution/replay/expiry denies. Selection regenerates the exact typed plan and
reruns policy and confirmation. No arbitrary application/path/URL/argument/value is
accepted, and no song-title or LLM correction is implemented.

Risk displays use existing operation registry and launch policy: informational reads,
low reversible launches/volume actions, sensitive manual screenshots, safe cancellation,
and unsupported future functions. The browser cannot assign risk. Cards show safe
codes and closed IDs, not raw recognizer evidence. Transcripts are hidden unless both
server policy and session request allow them; only fixed synthetic command text can
be displayed. Terminal cleanup removes it. Challenge and confirmation speech, scores,
embeddings, profile/participant IDs and personal paths never enter API projections.

TTS is unavailable; speaking and speech preference remain false. Safe response text and
classification are provided for a later Phase 14A contract. Duration is monotonic elapsed
session time including user waits and synthetic fixture work, not model performance.
No timing database or permanent history exists. History contains only public session ID,
UTC time, closed capability/state/risk, confirmation flags, verification, duration and
safe reason. Delete-one and clear affect only the current process history.

## HTTP boundary

The thin standard-library HTTP adapter is disabled by default. It binds exactly
127.0.0.1, default port 8765 (1024..65535). Allowed frontend origins are explicit,
maximum four, default http://127.0.0.1:5173; no wildcard/hostname/remote origins.
Host must match the configured numeric loopback address and port. Browser mutations
require that Origin plus X-VoicePilot-Request: 1 and exactly application/json. This
requires a successful allowlisted CORS preflight. GET may omit Origin but rejects a
foreign supplied Origin. This is a same-user loopback boundary, not authentication
against malicious local processes; no internet exposure or authentication server exists.

Fixed routes/methods, strict Pydantic bodies, unknown-field/duplicate-JSON-key rejection,
content-type/framing checks and bounded body reads reject text/code/path injection.
Default body limit 4096 bytes (maximum 16384), response hard limit 1 MiB, maximum
64 sessions, 256 retained events per session and 1000 history entries. Defaults are
16/64/100 respectively. No static-file handler, profile selector, calibration approval,
risk override or unsupported-capability enablement endpoint exists.

Transport rejects duplicate framing/security headers and transfer encoding; closes each
HTTP/1.0 connection; uses a four-connection listen backlog and two-second socket
inactivity timeout. It is intentionally single-threaded for the bounded local demo;
no worker thread or port starts during validation. A slow local client can delay other
requests until timeout, and this is not hardened against a hostile same-user denial of
service or designed for long-running production inference. Cancellation is cooperative;
the synchronous transport cannot preempt a currently executing handler. Do not expose
this development server to a network or describe it as a production deployment server.

Responses are JSON with no-store/nosniff and no request logging, stack traces or raw
exceptions. Server shutdown closes sessions/history and the socket. Tests use an
in-process dispatcher, byte-stream fake connection, and fake server factory only.
No real server was started and no port/thread was left running.

Emergency stop uses the existing latched CancellationHub and blocks subsequent work.
It never kills applications or rolls back completed effects. Reset returns
reset_unavailable; restart the process. There is no internal stopped.clear shortcut.
Cancellation registrations are released on completion/failure. Expiry is checked at
request/stage boundaries, not by a background polling thread; pending objects are bounded
and expire when next inspected or operated on. Public status/history/session polling
must not be interpreted as real device observation.

## Exact API routes

All paths begin `/api/v1`:

- GET /health, /status, /capabilities, /applications, /system, /calibration, /privacy
- POST /demo/sessions; POST /sessions (always calibration_blocked)
- GET /sessions/{id}; GET /sessions/{id}/events
- POST /sessions/{id}/activate, /sessions/{id}/capture/stop, /sessions/{id}/capture/cancel
- POST /sessions/{id}/clarify, /sessions/{id}/confirm, /sessions/{id}/cancel
- GET /history; DELETE /history/{id}; DELETE /history
- POST /emergency-stop; POST /emergency-stop/reset (unavailable)

POST/DELETE require JSON objects, including `{}` when there are no arguments.
Create: {"scenario":"calculator_confirm","show_transcript":false}.
Clarify: {"request_id":"CARD_UUID","candidate_id":"chrome"}.
Confirm: {"request_id":"CARD_UUID","decision":"confirm"} or decision `cancel`.
Session IDs are public opaque IDs, never owner profile IDs. No query parameters.
OPTIONS supports only the methods/headers of the matched route.
Applications/system routes report metadata and not_probed, not live discovery/readings.
Spotify and screenshots are manual-only catalog capabilities; no API action routes.

## CLI and review scenarios

Safe commands do not start a server or access hardware/models/profiles:

```powershell
.\venv\Scripts\python.exe -B -m app.api.cli inspect-config
.\venv\Scripts\python.exe -B -m app.api.cli routes
.\venv\Scripts\python.exe -B -m app.api.cli capabilities
.\venv\Scripts\python.exe -B -m app.api.cli evaluate-demo
```

User-only demo startup, after reviewing the loopback boundary:

```powershell
$env:VOICEPILOT_API__ENABLED = 'true'
.\venv\Scripts\python.exe -B -m app.api.cli serve
```

Stop with Ctrl+C. Nothing launches a browser or opens the microphone. Settings do not
implicitly load .env. Production sessions stay locked even if server/demo is enabled.

Ten scenario IDs: read_volume, calculator_confirm, chrome_cancel, ambiguous_application,
unknown_application, wrong_speaker, confirmation_expiry, emergency_stop,
verification_failure, history_entry. Evaluation drives the same in-process service and
uses a fake clock for expiry. It checks exact states and history, not real hardware or
population biometric accuracy. Failure to observe a synthetic effect is reported failed,
never successful because an adapter merely returned.

## Phase 15A integration requirements

Build the separately approved black-and-orange frontend against this versioned API.
Use the configured numeric-loopback origin, JSON and X-VoicePilot-Request header.
Render the demo banner persistently, authentication/mode separately, state-driven orb,
listening indicator and transient eight-level waveform. Never request browser audio.
Poll bounded session/events views; use sequence numbers to detect gaps. Render safe
risk/plan/clarification/confirmation cards exactly; submit only offered IDs and decisions.
Default transcripts hidden; honor server permission. Clear transient waveform/text on
capture end or terminal state. Display failed verification and calibration lock honestly.
Provide bounded history deletion, cancellation, stop and restart-required reset notice.
Do not add an authenticated/confirmed boolean, profile selector or production enable switch.
TTS/wake word/global shortcut remain unavailable. No frontend is implemented by Phase 6D.
