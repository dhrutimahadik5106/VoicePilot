# 0011: Controlled Windows application launching

Phase 6A adds one real effect: launching one explicitly approved application with
no arguments. It does not enable media playback, URLs, browser automation, input
control, closing applications, arbitrary processes, scripts or generated code.
Earlier phase decisions describe historical boundaries; this decision supersedes
only the prohibition on this narrow, separately approved launch adapter.

## Discovery and executable identity

The immutable 6a-v1 allowlist contains Notepad, Calculator, Chrome and Spotify.
Windows APIs supply the system directory and Program Files roots. Candidates are
fixed: system notepad.exe/calc.exe, Google/Chrome/Application/chrome.exe and
Spotify/Spotify.exe under Program Files. Per-user installations are unavailable.
No registry command strings, PATH lookup, environment expansion, shortcuts, URLs,
protocol activation, arbitrary working directories or fallback paths are accepted.

Validation rejects relative/network paths, alternate streams, traversal, reparse
points, canonical-path mismatch and writable locations. File and ancestor handles
remain held without write/delete sharing through launch. DACL checks reject write
permissions for principals other than SYSTEM, Administrators or TrustedInstaller;
AccessCheck also rejects effective current-token write/delete/ACL/owner access.
Elevated processes are denied. Authenticode embedded signatures or SHA-256 catalog
membership must validate through WinVerifyTrust using offline cached trust. The
verified signing organization and OriginalFilename must match the closed entry.
Only exact NOTEPAD.EXE.MUI is additionally accepted as Notepad version metadata;
the executable path still must end in notepad.exe. No .mui launch is permitted.

The confirmation binds a digest of validated path, file identity/size/write time and
publisher. Immediate revalidation must match it. This digest is an integrity label,
not encryption or proof of identity. Identity data and paths are excluded from
normal repr, output and serialization. Validation failures emit closed reason codes.

## Authorization and control

Manual CLI use is visibly labelled MANUAL OPERATOR TEST, not voice authentication.
It displays the application, requires typing its exact ID, discovers the candidate,
then requires LAUNCH followed by that exact ID. No confirmation flag exists.
An internally recorded, expiring, single-use permit binds the complete typed plan,
application, image identity, step, capability, policy version and authentication
handle where applicable. Changed/replayed/expired evidence and fake/simulation
objects cannot authorize this adapter. Issuer and controller ledgers are bounded.

The default production flag is false. The separate manual test flag is true but
never substitutes for typed consent. Pending speaker calibration denies the voice
CLI before capture, STT or execution. Future enabled voice use delegates to the
existing Phase 4B protected-policy/provenance and fresh verifier boundary through
SpeakerInspection and DiagnosticService, then STT safety, resolver, planner and
risk policy. Only resolved, ready, low-risk open_application plans can proceed;
all still require exact typed launch confirmation. Configuration alone is not a
protected policy approval. No calibration, thresholds or speaker artifacts change.

The adapter uses the Phase 5B generic adapter contract and state machine; a separate
LaunchController admits only this closed capability with real, privacy-safe events.
The original fake controller/registry and diagnostic plans remain non-executing.
Native CreateProcessW receives the fixed executable, NULL command line, no inherited
handles, no elevation and the trusted system working directory. No shell is used.
There is at most one creation attempt, never an automatic retry.

The controller ignores adapter success claims and independently observes OS process
image paths, applying identity validation again. Exact Microsoft WindowsCalculator
and WindowsNotepad package identities may be observed behind their signed system
brokers; no package/URI activation is implemented. An already observed matching app
returns already_running_and_verified without creation. A creation return alone
never means success. Foreground/window state is not measured or claimed.

Cancellation, emergency stop and expiry are checked around each stage. Emergency
stop latches for the controller lifetime. Discovery, launch and observation budgets
are bounded; WinAPI calls are synchronous and deadlines are cooperative, not hard
preemption. Cancellation/timeouts after creation may leave the program running.
No close, kill or rollback is attempted or claimed. In-process trusted dependencies
are not a sandbox against malicious Python code; no crash-safe durable idempotency
or isolated watchdog is supplied. This is a controlled foundation, not production
hardening equivalent to all future prerequisites listed in decision 0010.

## Privacy and configuration

Audit events remain in memory: event/plan/step IDs, capability, state transition,
safe reason, timing and permission flags. No transcript, audio, entity values,
executable paths, tokens, profile, embeddings, similarity or provenance is saved.
No new storage, dependencies, model downloads, microphone tests or real launches
are required for validation. Existing artifact ignore rules remain unchanged.

Settings.launch defaults: real_execution_enabled=false, windows_adapter_enabled=true,
manual_launch_testing_enabled=true, four approved IDs, discovery/launch/observation
budgets 5 seconds each, authorization_expiry=30 seconds, maximum_applications=1,
arguments_allowed=false, elevation_allowed=false. Immutable limits cannot be widened.
Imports and settings do not discover or launch anything.

## Commands and manual boundary

These commands are implemented; launch commands are tested only with fake components.
Run inspection first. Test Notepad or Calculator first only after available discovery.
Chrome/Spotify may be tried only when safely discovered. No command is run for you.

```powershell
.\venv\Scripts\python.exe -m app.launch.cli list
.\venv\Scripts\python.exe -m app.launch.cli status
.\venv\Scripts\python.exe -m app.launch.cli discover
.\venv\Scripts\python.exe -m app.launch.cli discover chrome
.\venv\Scripts\python.exe -m app.launch.cli discover spotify
.\venv\Scripts\python.exe -m app.launch.cli manual-launch-test notepad
.\venv\Scripts\python.exe -m app.launch.cli manual-launch-test calculator
.\venv\Scripts\python.exe -m app.launch.cli manual-launch-test chrome
.\venv\Scripts\python.exe -m app.launch.cli manual-launch-test spotify
.\venv\Scripts\python.exe -m app.launch.cli manual-launch-test unknown-app
.\venv\Scripts\python.exe -m app.launch.cli authenticated-voice-status
.\venv\Scripts\python.exe -m app.launch.cli authenticated-voice --profile 00000000-0000-0000-0000-000000000001
```

The last UUID is synthetic; with pending/default configuration it denies before any
profile read, recording or STT. For a manual Notepad test, type notepad then
LAUNCH notepad. Declining or interrupting cancels. A successful launch may cause the
application's own startup files/network behavior; VoicePilot does not automate it.

## Validation and limitations

Tests use fake discovery, creation, process observations, voices and clocks. Active
guards prohibit native DLL loading, process/network/device/model access and personal
filesystem access. Native glue tests replace API functions with in-memory mocks.
Coverage includes exact metadata/path separation, signature failure/cleanup,
elevation, aliases, unsafe paths/arguments, ACL failures, revalidation, expiry/replay,
false success, independent observation, cancellation, deadlines and private output.

Read-only discovery on the development machine found Notepad, Calculator and Chrome
available, and no Spotify candidate in approved locations. This is not evidence of
successful launch or real OS observation after launch. Offline trust does not obtain
fresh revocation information; strict checks can reject legitimate installations.
No hardware, real profile/model or application launch was tested.

Phase 6B would require separate approval for narrowly scoped Spotify controls,
new capability/risk rules, exact entity/side-effect confirmation, supported trusted
control interfaces, independent playback observation, cancellation and privacy tests.
It is not implemented or started here.

Windows API references:
- https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw
- https://learn.microsoft.com/en-us/windows/win32/api/wintrust/nf-wintrust-winverifytrust
- https://learn.microsoft.com/en-us/windows/win32/api/wintrust/ns-wintrust-wintrust_catalog_info
