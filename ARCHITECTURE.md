# Architecture

Implemented: Phase 1 foundation, Phase 2 explicit audio input, and Phase 3 local
speech-to-text. Phase 2 hardware checks succeeded per the user: device listing,
in-memory recording, WAV saving, cancellation and audio quality.
The user has manually tested Phase 3 and reported recognition mistakes and slow
first-run processing. These refinements are tested with fakes; real improvements
have not been measured.

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

## Phase 3 refinements

The STT microphone command defaults to record(None): the existing recorder uses
a configured safety maximum (120s default/hard cap) rather than a short CLI timer.
Enter stops; c/Ctrl+C discards; optional post-speech silence detection can stop.
RMS activity uses a configurable threshold and silence interval, counts frames,
resets on renewed activity, and retains captured trailing silence. It is off by
default. Capture remains explicit and in memory, with elapsed terminal display.

--seconds keeps an explicit bounded mode. --session keeps one service and lazy
engine alive across deliberate captures. The microphone is stopped while waiting
for a new start or while transcribing. No audio/history persistence is added.

The default model is small/cpu/int8. Configured beam size, temperature, VAD minimum
silence, word timestamps, initial prompt and hotwords pass to Faster-Whisper.
Vocabulary hints include VoicePilot, Spotify, WhatsApp, Chrome, YouTube and Dhruti;
there is no lexical replacement layer. Raw transcript is exact segment-string
concatenation; normalized transcript only formats segment-boundary whitespace.
Both are serialized in the structured result; segments preserve raw text.

Separate clocks measure model load (including download/cache resolution),
inference (including full generator consumption), and total engine processing.
RTF uses total engine processing divided by source duration. The cold_start flag
describes whether this engine constructed or reused a model; it does not infer
cache/download state. File reading/capture/final cleanup are outside those totals.
Cancellation remains cooperative around native operations.

Silence, VAD and vocabulary bias can affect endings and multilingual speech.
Accuracy and speed are not guaranteed. No GPU or larger-model assumption is made,
and no new benchmark or improvement is claimed. Phase 4 remains unimplemented.
