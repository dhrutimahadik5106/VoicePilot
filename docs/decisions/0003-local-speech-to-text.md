# 0003: Local speech-to-text

Status: accepted for Phase 3. Automated tests use fake engines/models.
The user manually tested STT, reporting recognition mistakes and a slow first
run. Refinement accuracy and performance remain unmeasured.

The user reports successful Phase 2 device listing, in-memory capture, WAV saving,
cancellation and audio-quality verification using recordings/phase2-test.wav.
That private file is not opened by automated tests or committed.

Use existing faster-whisper 1.2.1 without package changes. Preserve Python 3.12.10
and venv. Default to small, cpu and int8. Add a SpeechToTextEngine protocol,
validated request/segment/result models, a lazy FasterWhisperEngine adapter,
a file/in-memory validation service and an explicit terminal CLI.

Accept existing RecordedAudio or one explicitly selected regular PCM WAV.
Support 8000-48000 Hz, PCM 8/16/24/32-bit WAV and one through eight file channels.
Downmix file input to mono using a float intermediate, round/clip to int16,
and bound file size and source duration before reading samples.
Existing capture retains its Phase 2 mono/stereo contract. Maximum STT duration
defaults to 120 seconds and may only be lowered. Zero-frame/truncated WAVs fail.
Silence is not empty input; VAD can legitimately yield a successful empty transcript.

Convert to mono float32 at 16000 Hz. For other rates, use Faster-Whisper's PyAV
decoder/resampler on an in-memory WAV buffer, closed after conversion.
No temporary recording file or extra resampling dependency is needed.
The model is lazily cached for the engine lifetime; close drops that reference.
Consume the segment generator before completing timing, close it in finally,
sort segments stably by start/end time, and join stripped text with spaces.
Cancellation is cooperative around model loading and between yielded segments;
native inference/download calls may delay Ctrl+C or cancellation response.

VAD defaults on, word timestamps off, beam size five; language defaults to auto.
Language probability comes directly from detected-language metadata and is not
transcription confidence. Explicit language selection suppresses the backend's
placeholder probability of one. No overall confidence/accuracy score is invented.
Processing duration includes preparation, model loading and inference, but excludes
file reading, microphone capture and final resource cleanup. RTF divides this
duration by source duration, or is unavailable for zero-duration failures.

Recognition runs locally. Only model downloads may need network access. Cache
models under ignored models/whisper. The first explicit manual transcription may
download the selected model. stt_local_files_only disables model downloads.
Resolve the model snapshot and require tokenizer.json before construction, so
offline loading cannot fall back to a tokenizer network fetch.
The backend's text-capable logger is suppressed during loading/inference; errors
contain safe codes. CLI output intentionally displays the requested transcript,
but no transcript, history database or audio file is automatically saved.

Results carry UUID audio identity, optional execution correlation UUID, timestamp,
text, language, source duration, processing time and RTF for future association.
These are data fields only; recognized text is never executed.
No wake word, authentication, speaker verification, LLM reasoning, orchestration,
computer control, browser/screen integration, database, API or frontend is built.

Tests use mocked capture/model boundaries, blocked hardware/model imports and
blocked socket connections. WAV fixtures are generated in pytest temporary
directories. Resampler wiring and model loading are mock-tested; actual STT,
language accuracy, noisy/accented speech and laptop latency need manual checks.
No Word Error Rate, benchmark or accuracy claim is made.

## Refinement decision

Manual observations: base confused "Hey Voice Pilot" with "Play Voice Pilot" and
lost some ending words. Small improved VoicePilot/Spotify recognition for the
user, but a first run reported 262.431s total processing. That prior measurement
did not isolate initialization/download time and is not an inference benchmark.

Remove the STT CLI's implicit five-second limit. Use explicit Enter-to-stop with
a configurable 120s safety maximum; retain --seconds for intentional shorter
caps. Add optional silence stopping, disabled by default, using normalized block
RMS after speech activity and a configurable silence interval. Leading silence
waits for Enter/cancel/safety, renewed activity resets the counter, and captured
silence is retained. A heuristic can cut off quiet speech or pauses; no sentence
completion guarantee is claimed. Elapsed recording seconds are displayed.

Add --session to reuse one lazily loaded model for successive user-approved
captures. Waiting between requests does not open the microphone. No automatic
audio/transcript persistence is added; cancellation discards current data.

Use small on CPU/int8; no medium/large migration or GPU assumption. Pass beam
size, temperature (default zero), VAD minimum silence (1000ms, with 400ms speech
padding), word timestamps, initial prompt and hotwords to the installed backend.
Default vocabulary is VoicePilot, Spotify, WhatsApp, Chrome, YouTube and Dhruti.
Hints can be disabled with empty strings. They can bias multilingual decoding;
accuracy is not guaranteed.

Do not correct "Play" to "Hey" or substitute arbitrary words. raw_transcript
concatenates unmodified backend segment strings in chronological order.
normalized_transcript/text trim segment edges and join with a space only.
Both are available in result serialization; CLI output is not length-truncated.

Measure model_load_duration separately, including any download/cache lookup and
initialization. inference_duration spans the backend call and complete segment
consumption. processing_duration/total_processing_duration also include engine
preparation/orchestration, excluding capture, file reading and final cleanup.
RTF uses total processing divided by source duration. cold_start is true if this
engine attempted model construction, false when reusing its loaded model, unknown
for earlier rejections. It does not assert a model download or cold filesystem
cache. New CLI processes initialize again; --session enables warm comparisons.

Regression tests use fake callbacks/models/clocks to verify Enter/fixed/safety/
silence stops, cancellation, no saves, end-word preservation, raw/normalized
data, protected vocabulary, reuse and separated timing. These synthetic timings
are not performance results. Real improvement requires fresh manual measurements.
