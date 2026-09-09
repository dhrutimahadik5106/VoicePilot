# VoicePilot

VoicePilot is a planned voice-driven assistant with authentication, risk checks,
verification and recovery. Phase 1 foundation and Phase 2 explicit audio input
are implemented and covered by automated tests using fake audio backends.
Microphone hardware has NOT been manually verified. This is not production-ready.

## Existing environment and tests

Preserve Python 3.12.10 and the existing venv. Do not recreate it or install or
upgrade packages. Run from the project root in PowerShell; activation is unnecessary.

```powershell
.\venv\Scripts\python.exe --version
.\venv\Scripts\python.exe -m pytest
.\venv\Scripts\python.exe -m pytest tests/audio
```

Runtime direct dependencies: pydantic, pydantic-settings, numpy and sounddevice.
pytest is the test dependency. All already existed; no packages were changed.
Project metadata is not a lockfile.

## Explicit audio input and manual checks

These commands are for the user to run manually. Automated tests never use a real
microphone. Listing queries device metadata without opening a capture stream.

```powershell
.\venv\Scripts\python.exe -m app.audio.cli devices
.\venv\Scripts\python.exe -m app.audio.cli record --seconds 3
.\venv\Scripts\python.exe -m app.audio.cli record --seconds 3 --save --filename phase2-test.wav
```

For recording, press Enter at the start prompt to deliberately permit microphone
capture. The terminal displays RECORDING requested and RECORDING STOPPED.
During capture, Enter stops and returns captured audio; c or Ctrl+C cancels and
discards it. The duration limit stops capture automatically. This is terminal
push-to-talk with explicit start/stop, not a global hotkey or a hold-to-talk hook.
The terminal must have focus. No background input reader or listener is started.

Without --save, audio stays in memory and is released when the CLI exits.
--save explicitly enables persistence for that invocation and requests export.
The persistence setting defaults to false; setting it true alone never causes a
save. Library callers must explicitly call save_wav with persistence_enabled=True
(or their approved configuration value). Filenames default to UTC timestamp plus
a random suffix; a provided name must be a simple .wav basename. Existing files
are rejected unless --overwrite is explicitly supplied together with --save.
All destinations are restricted to recordings/ or its subdirectories under the
current project root; traversal, absolute paths and linked destinations are rejected.
Run from the project root. Export creates only the requested directory tree.
WAV uses standard-library wave, signed 16-bit little-endian PCM; no scipy.

To select a device, use its numeric index or exact, unambiguous name:

```powershell
$env:VOICEPILOT_AUDIO_INPUT_DEVICE = "0"
.\venv\Scripts\python.exe -m app.audio.cli record --seconds 3
```

Use an index from your own device listing. With no override the operating system's
default input is used; a missing default fails instead of choosing another device.

## Configuration

.env.example lists VOICEPILOT_ variables. No .env is created or automatically read.
Settings neither query devices nor create directories. get_settings() caches one
instance; get_settings.cache_clear() intentionally reloads configuration.
Audio defaults: 16000 Hz, mono, int16, 1024-frame blocks, maximum 30 seconds,
default input device, recordings/ directory, persistence disabled.
Allowed bounds: 8000?48000 Hz, 1?2 channels, 64?4096-frame blocks, duration
0.1?120 seconds. Hardware support is checked only at explicit capture time.
The requested duration must be at least 0.1 seconds and within the configured maximum.

## Privacy and limitations

No continuous listening, hidden capture, automatic saving, playback, wake word,
speaker recognition, transcription, LLM calls, LangGraph, computer control,
browser automation, screen perception, memory, API or GUI is implemented.
Future speaker enrollment requires separate explicit consent.
Cancellation drops application-held sample references; this is not a promise of
cryptographic memory erasure. The OS/driver may retain its own buffers.

Audio code emits no logs containing samples, embeddings, exception details or
sensitive paths. The Phase 1 logger retains its fixed-event allowlist.
PermissionError maps to permission_denied; PortAudio missing/unavailable device
codes map to controlled errors. Native errors that do not expose a distinct
permission code are reported as stream_failed rather than guessed from text.
Native driver calls may block despite application deadlines; duration bounds cap
retained samples and stop requests, but cannot guarantee driver response time.

Automated tests verify mocks, state transitions, duration limits, cancellation,
cleanup attempts, model/configuration validation and temporary-file WAV output.
Actual device support, OS permission behavior, recording quality and physical
stream release require manual hardware verification. Symlink checks prevent
ordinary linked destinations; export does not defend against a concurrent local
attacker replacing filesystem entries. Failed disk writes may leave a partial WAV.
