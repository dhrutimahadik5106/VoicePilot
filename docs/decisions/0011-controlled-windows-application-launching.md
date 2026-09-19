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


## Phase 6A correction: modern Notepad observation

The user manually confirmed that Notepad opened but returned identity_mismatch /
unverified; Calculator and Chrome returned launched_and_verified. No application
was launched by the agent while diagnosing or validating this correction.

Read-only inspection reproduced an identity-validation defect for the installed
Microsoft.WindowsNotepad package: opening the WindowsApps container fails with
access denied, the old DACL parser rejects a conditional read/execute ACE, and the
final packaged executable does not satisfy the launcher's version-resource query.
The packaged executable's Microsoft signature does validate. After correction,
read-only installed-package validation passes. No Notepad process was running at
diagnosis time, so the historical launcher/replacement PIDs, parent relationship,
reuse behavior and timing cannot be reconstructed from the earlier result alone.

The previous observer discarded CreateProcessW's PID and accepted package path
patterns without querying process package identity or tying the process to a launch.
This correction replaces that behavior for Notepad only. Calculator/Chrome/Spotify
keep their existing observation paths; the general launch allowlist is unchanged.

Accepted final identities are:

- Legacy: the exact approved system notepad.exe, matching the confirmed image
  identity and returned PID/start time, when no modern Notepad package is registered.
- Modern: executable Notepad/Notepad.exe beneath the Windows-registered package
  root in the OS Program Files/WindowsApps location; exact family
  Microsoft.WindowsNotepad_8wekyb3d8bbwe; exact application user model identity
  Microsoft.WindowsNotepad_8wekyb3d8bbwe!App; full package name matching
  Microsoft.WindowsNotepad_<four-part numeric version>_<x64|x86|arm64>__8wekyb3d8bbwe.
  The full process package name must resolve through GetPackagePathByFullName to
  exactly that root. Partial/similar names, resource packages, alternate publishers,
  user/network locations and arbitrary registrations are rejected.

Modern observation holds and verifies the protected Program Files anchor, registered
package root, Notepad directory and executable. It checks canonical paths, reparse
flags, write permissions and the executable's exact Microsoft signing organization.
It does not require opening the intentionally restricted WindowsApps container.
Windows package registration supplies that container relationship; held canonical
package handles and package ACLs/signature supply independent protection evidence.
Only conditional READ/EXECUTE ACEs may be skipped when checking these Notepad package
objects for writes. Conditional write or unknown ACEs still fail closed. Other
application ACL validation is unchanged. The package identity and signature replace
legacy version-resource metadata for final observation only. The system launch
identity remains exactly notepad.exe; metadata allows exactly NOTEPAD.EXE.MUI;
.mui files are never executable targets.

Before creation, capture a bounded Notepad-only PID/start-time baseline and whether
a modern package is registered. Keep the actual returned process handle and its
GetProcessTimes creation timestamp through observation, preventing launcher PID
reuse while proving correlation. Accept only that PID with that exact timestamp,
or a new directly parent-correlated replacement PID created no earlier than it.
Reject baseline instances, unrelated new processes, impossible future timestamps,
identity mismatches and observations outside the bounded deadline. The launcher
may exit before its child is observed; its retained handle remains correlation
evidence, not success evidence. A registered modern package prevents a transient
system broker from being mistaken for the final application. Recheck final process
liveness, PID/start time, parent and package/path identity after signature validation.
Release handles on every controller exit; never kill/close the application.

Notepad no longer treats a pre-existing process as an already-running success for
this request. If Windows reuses an existing Notepad instance, or a broker creates a
new process with no provable direct relationship, this conservative implementation
returns unverified. Time proximity or matching window titles are not sufficient.
It does not implement ETW activation tracing, arbitrary ancestry inference or a
window/document-based reuse detector. The exact handoff on this machine still
requires the user's manual retest; no real post-fix launch success is claimed.

A narrow diagnostic is available:

```powershell
.\venv\Scripts\python.exe -m app.launch.cli diagnose-notepad
```

It never launches or prompts. It queries only exact Notepad process entries and
reports PID, fixed executable name, safe location classification, aggregate identity
and publisher-validation status, exact approved family/AUMID or a closed placeholder,
creation timestamp and report time. It explicitly labels launch correlation as not
available in this independent read-only snapshot. It never reports unrelated process
identities, parent process details, command lines, titles, documents, usernames or
raw paths, and writes no artifact. A snapshot cannot retrospectively prove the
handoff of a completed earlier request.

Regression tests use native API fakes and generated process identities: legacy and
modern same-PID cases, correlated replacement after launcher exit, existing/unrelated
processes, PID reuse, wrong family/AUMID/package/name/publisher/signature/location,
write/reparse failures, delayed/no final observation, creation-only false success,
transient brokers, final process exit and diagnostic privacy. No dependencies change.

Relevant API contracts:
- https://learn.microsoft.com/en-us/windows/win32/api/appmodel/nf-appmodel-getpackagefamilyname
- https://learn.microsoft.com/en-us/windows/win32/api/appmodel/nf-appmodel-getapplicationusermodelid
- https://learn.microsoft.com/en-us/windows/win32/api/appmodel/nf-appmodel-getpackagepathbyfullname
- https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes
- https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-processentry32w
