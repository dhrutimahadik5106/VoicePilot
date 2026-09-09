# Architecture

Implemented: Phase 1 foundation, Phase 2 explicit audio input, and Phase 3 local
speech-to-text. Phase 2 hardware checks succeeded per the user: device listing,
in-memory recording, WAV saving, cancellation and audio quality.
Phase 3 is automated-tested with fakes; real transcription remains unverified.

Planned full pipeline:

Perceive ? Authenticate ? Transcribe ? Understand ? Retrieve Context ? Plan ?
Risk Check ? Execute ? Observe ? Verify ? Recover ? Respond ? Update Memory

Only audio input within Perceive and local Transcribe are implemented.
Authenticate and all later reasoning/action/history components remain planned.
The STT CLI demonstrates transcription without an authenticated execution path;
recognized text is displayed only and never executed.

Foundation: app/core/config.py provides side-effect-free validated configuration;
errors.py shared exceptions; logging.py safe fixed operational events.

Audio: app/audio provides the AudioRecorder protocol, typed PCM/results,
explicit discovery, bounded sounddevice capture, foreground terminal controls,
and separately requested WAV export. Capture remains in memory by default.

STT:
- contracts.py: replaceable SpeechToTextEngine protocol.
- models.py: requests, segments, optional word timestamps, safe errors and results.
- service.py: validates one selected PCM WAV or accepts RecordedAudio; checks
  bounds and prepares file PCM without scanning folders or persisting audio.
- faster_whisper_engine.py: lazy model loading, mono/16 kHz conversion,
  VAD/language/word options, segment consumption, timing and controlled errors.
- cli.py: explicit file transcription or Phase 2 capture followed by in-memory STT.

Model construction, downloads and device access never occur during module import
or settings loading. An explicit transcription can download model assets into
models/whisper; recognition itself uses local computation and never uploads audio.
Offline mode uses cached files only and rejects incomplete tokenizer snapshots.
The model is reused within the engine lifetime and released by dropping its
reference on close. Segment generators and in-memory WAV buffers are closed.

Results include correlation-ready UUIDs and timestamps but create no history.
Audio and transcripts never enter ordinary logs. CLI transcript display is
intentional user-facing output, not a logging or command-execution channel.

Tests inject fake models and capture adapters and generate WAVs in temporary
directories. Actual resampling/model compatibility, accuracy and latency require
manual STT checks. All future pipeline work requires separate phase approval.
