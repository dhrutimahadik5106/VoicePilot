# VoicePilot

VoicePilot is a planned voice-driven assistant with authentication, risk checks,
verification and recovery. Phases 1-3 implement foundation, explicit audio input and local speech-to-text.
The user verified Phase 2 device listing, in-memory recording, WAV saving,
cancellation and audio quality. Phase 3 is fake-tested; manual STT verification
is pending. This is not production-ready.

## Existing environment and tests

Preserve Python 3.12.10 and the existing venv. Do not recreate it or install or
upgrade packages. Run from the project root in PowerShell; activation is unnecessary.

```powershell
.\venv\Scripts\python.exe --version
.\venv\Scripts\python.exe -m pytest
.\venv\Scripts\python.exe -m pytest tests/audio
```

Runtime direct dependencies: pydantic, pydantic-settings, numpy, sounddevice and faster-whisper.
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
speaker recognition, LLM calls, LangGraph, computer control,
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
The user has verified Phase 2 recording and cancellation on their microphone;
other devices and driver behavior are not covered by that verification. Symlink checks prevent
ordinary linked destinations; export does not defend against a concurrent local
attacker replacing filesystem entries. Failed disk writes may leave a partial WAV.

## Phase 3: local speech-to-text

Implemented with fake-based automated tests: one selected PCM WAV, existing
RecordedAudio and explicit microphone capture followed by in-memory transcription.
Real STT accuracy and latency have NOT been manually verified.

**Before the first manual transcription:** Faster-Whisper may download the
configured model once into models/whisper. Recognition runs locally; audio is
never uploaded. These commands are provided for the user and were not executed
by the agent. Run from the repository root:

```powershell
# Transcribe the existing user-verified microphone sample
.\venv\Scripts\python.exe -m app.stt.cli file recordings\phase2-test.wav

# Record up to five seconds and transcribe in memory
.\venv\Scripts\python.exe -m app.stt.cli microphone --seconds 5

# Explicit English
.\venv\Scripts\python.exe -m app.stt.cli microphone --seconds 5 --language en

# Automatic detection: speak one short Hindi or Marathi sentence
.\venv\Scripts\python.exe -m app.stt.cli microphone --seconds 5 --language auto
```

Example Hindi: "??????, ?? ???? ????? ???"
Example Marathi: "???????, ?? ?????? ??? ???."
Keep the default multilingual base model for these tests; .en models support
English only. No accuracy claim is made for any sentence.

Microphone mode requires Enter at the consent prompt. During capture, Enter
stops, c or Ctrl+C cancels and discards audio. The Phase 2 recorder is reused.
Capture is then transcribed in memory without saving a WAV. During inference,
Ctrl+C requests cancellation; native inference/model-download calls may delay it.
The CLI displays transcript, language and timing. It never executes the transcript,
and it stores no transcript, command history or recording.

STT defaults: base / cpu / int8; automatic language detection; VAD enabled;
word timestamps disabled; beam size 5; maximum input duration 120 seconds.
VOICEPILOT_STT_LANGUAGE accepts auto or a language code (en, hi, mr, etc.).
VOICEPILOT_STT_WORD_TIMESTAMPS enables word timing in structured results.
VOICEPILOT_STT_VAD_FILTER and VOICEPILOT_STT_BEAM_SIZE control inference.
Existing VOICEPILOT_WHISPER_MODEL, VOICEPILOT_WHISPER_DEVICE and
VOICEPILOT_WHISPER_COMPUTE_TYPE now configure the real local adapter.
The full set is listed in .env.example; settings load no models or devices.

For cached models only, explicitly set:

```powershell
$env:VOICEPILOT_STT_LOCAL_FILES_ONLY = "true"
.\venv\Scripts\python.exe -m app.stt.cli file recordings\phase2-test.wav
```

Offline mode fails safely if the model/tokenizer is not cached.
The cache is restricted lexically to models/ and remains ignored by Git.
An engine caches one model until close; CLI exit drops its model reference.

Supported WAVs: regular, uncompressed PCM files, 8/16/24/32-bit, 8000-48000 Hz,
one through eight channels. Input must be nonempty and at most the configured
duration (hard maximum 120 seconds). Corrupt/truncated/oversized files are rejected.
Only the explicitly selected file is read; folders are never scanned.
File channels are averaged and quantized to mono int16. For inference, conversion
uses mono float32 at 16000 Hz; other rates use Faster-Whisper's PyAV resampler
with an in-memory WAV buffer. No extra resampling or WAV-writing package is added.

Results include audio UUID, optional execution correlation UUID, timestamp,
transcript, language, segments, optional word timestamps, model/device/compute
settings, source duration, processing duration and real-time factor.
Language probability is detection metadata, **not transcription confidence**.
It is omitted for explicitly selected languages. Processing time includes
preparation, model loading and inference, but excludes file reading, microphone
capture and final cleanup. RTF is processing time divided by source duration;
it is unavailable when source duration is zero. Silence may yield an empty
successful transcript. UUIDs are compatibility fields, not a history database.

Ordinary logs contain no transcripts/audio; Faster-Whisper's text-capable logger
is suppressed during inference. Explicit CLI transcript output can still be
visible in terminal scrollback. Temporary buffers are closed, not securely wiped.
Native/model memory reclamation follows the underlying libraries.

Accuracy can vary with language, accent, noise, microphone quality and speech
length. VAD can omit quiet speech, channel averaging can cancel opposing signals,
and quantization can lose low-level detail. Whisper can hallucinate text during
silence/noise. Laptop latency, model downloads and memory usage vary by model.
No WER, benchmark, confidence score or accuracy result is claimed.

```powershell
.\venv\Scripts\python.exe -m pytest
.\venv\Scripts\python.exe -m pytest tests/stt
```

STT tests use fake models/recorders, blocked real-model/hardware imports and
blocked socket connections. WAV files exist only in pytest temporary directories.
Actual model loading, resampling and inference need the manual checks above.
