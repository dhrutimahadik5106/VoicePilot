# Architecture

Implemented: Phase 1 foundation and Phase 2 explicit audio input, verified using
mock-based automated tests. Hardware capture is not manually verified.

Planned full pipeline:

Perceive ? Authenticate ? Transcribe ? Understand ? Retrieve Context ? Plan ?
Risk Check ? Execute ? Observe ? Verify ? Recover ? Respond ? Update Memory

Only the audio-input portion of Perceive exists. All other pipeline stages remain
planned, not implemented.

Current foundation: app/core/config.py provides bounded environment configuration,
app/core/errors.py shared exceptions, and app/core/logging.py safe console events.

Current audio modules:
- models.py: validated format, owned in-memory PCM, device metadata and results.
- contracts.py: AudioRecorder protocol, control callback and safe error codes.
- devices.py: explicit input-only discovery and exact device selection.
- recorder.py: lazily loaded sounddevice adapter, bounded callback capture,
  state transitions, cancellation and abort/close cleanup.
- wav.py: explicitly enabled WAV export confined to the ignored recordings tree.
- cli.py: foreground terminal start, stop, cancel, device listing and optional export.

Importing audio modules or constructing the recorder does not load sounddevice,
enumerate devices or open streams. The synchronous record call opens one stream
only after a deliberate caller action. The PortAudio callback accumulates at most
the configured number of frames. The caller polls stop/cancel and a monotonic
deadline. Streams are aborted/closed before assembling the result. Cancellation
and failures return no samples. Capture never writes files.

WAV export is independent of capture and requires explicit persistence permission.
The CLI also requires --save; configuration alone never triggers saving.
Tests replace the backend or recorder and use pytest temporary directories for
exports. Future integrations require separate phase approval and security review.
Configuration flags alone never establish identity or authorize computer actions.
