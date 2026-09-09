# 0002: Explicit audio input

Status: accepted for Phase 2; verified through fake-backend automated tests.
Real microphone hardware remains unverified.

Use existing sounddevice 0.5.6 and numpy 2.5.2 without package changes.
Declare both as direct dependencies. Preserve Python 3.12.10 and the existing
venv. WAV export uses standard-library wave; scipy is unnecessary.

Expose AudioRecorder as a protocol and inject the backend for testing.
Defer sounddevice import (and PortAudio initialization) until explicit device
discovery or capture. Configuration and module imports have no hardware effects.
Device discovery lists input-capable devices without opening an input stream.

Use bounded signed-int16 PCM callbacks with monotonic stop deadlines and sample
count limits. Default to 16000 Hz mono, 1024-frame blocks and a 30-second maximum;
hard limits cap rate at 48000 Hz, channels at two and duration at 120 seconds.
Cancellation and failure discard application-held samples. Abort and close are
attempted before reporting completion. Driver calls cannot be forcibly bounded
by this synchronous adapter, and OS buffers are outside application control.

Use explicit terminal start/stop push-to-talk, not global keyboard hooks.
Enter deliberately starts; Enter stops; c or Ctrl+C cancels during capture.
Only the foreground terminal is polled during the requested capture.
No continuous listening or startup capture exists.

Persistence is disabled by default. --save provides explicit per-invocation
permission and export intent; configuration alone never starts export.
Constrain exports to the ignored recordings tree, reject path traversal and
linked destinations, generate safe filenames, and require explicit overwrite.
Concurrent hostile filesystem replacement and secure memory erasure are outside
this phase's guarantees; disk errors can leave partial output files.

Error results contain safe codes, not native exception details. Device names
are displayed only on explicit listing; audio code does not log recordings or
sensitive paths. Unclassified native permission failures remain stream_failed.

Mock tests cover input filtering, state changes, bounded capture, cancellation,
cleanup, validation, CLI intent and WAV headers. Manual device listing and
three-second capture/export commands are documented but not executed by the agent.
No speaker enrollment is allowed without separate future consent. Wake word,
speaker verification, STT and every later pipeline stage remain deferred.
