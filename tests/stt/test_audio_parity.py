"""Generated PCM only. Fake resampling/VAD prove routing, not speech accuracy."""
import gc
import io
import json
import wave
import weakref
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from app.audio.models import AudioFormat, RecordedAudio
from app.audio.wav import save_wav, write_pcm_wav
from app.core.config import Settings
from app.stt.audio_preprocessing import mono_pcm16, prepare_audio
from app.stt.contracts import TranscriptionError
from app.stt.models import TranscriptionStatus
from app.stt.output_safety import apply_output_safety
from app.stt.parity import ComparisonEngine, compare_capture, main, settings_snapshot
from app.stt.service import read_pcm_wav, read_pcm_wav_stream
from tests.stt import audio, isolated_stt, segment
from tests.stt.test_cli import FakeRecorder

SECRET = "UNIQUE_PARITY_SECRET_43D"


def waveform(kind, rate, channels):
    n = rate
    t = np.arange(n) / rate
    x = np.rint(3 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)
    if kind == "silence":
        x[:] = 0
    elif kind == "impulse":
        x[:] = 0
        x[n // 2] = 20000
    elif kind == "extrema":
        x[::2], x[1::2] = -32768, 32767
    elif kind == "padded":
        x[:n // 4] = x[-n // 4:] = 0
    y = x.copy()
    if kind == "half":
        y = (x + 1).astype(np.int16)
    elif kind == "opposite":
        y = -x
    elif kind == "asymmetric":
        y[:] = 0
    samples = x[:, None] if channels == 1 else np.column_stack((x, y))
    # Feed a non-contiguous view through the production capture-data validator.
    backing = np.zeros((n * 2, channels), dtype=np.int16)
    backing[::2] = samples
    return RecordedAudio(format=AudioFormat(sample_rate=rate, channels=channels), samples=backing[::2])


def deterministic_decoder(buffer):
    with wave.open(buffer, "rb") as wav:
        assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
        rate = wav.getframerate()
        values = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768
    count = round(len(values) * 16000 / rate)
    return np.interp(np.arange(count) * rate / 16000, np.arange(len(values)), values).astype(np.float32)


def roundtrip(source):
    with io.BytesIO() as buffer:
        write_pcm_wav(source, buffer)
        buffer.seek(0)
        with wave.open(buffer, "rb") as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getnframes(), wav.getsampwidth()) == (
                source.format.sample_rate, source.format.channels, len(source.samples), 2)
            assert wav.readframes(wav.getnframes()) == source.samples.astype("<i2").tobytes()
        buffer.seek(0)
        return read_pcm_wav_stream(buffer, 120)


@pytest.mark.parametrize("rate", [8000, 16000, 22050, 44100, 48000])
@pytest.mark.parametrize("channels", [1, 2])
@pytest.mark.parametrize("kind", ["sine", "silence", "impulse", "extrema", "padded", "half", "opposite", "asymmetric"])
def test_waveform_roundtrip_parity(rate, channels, kind):
    source = waveform(kind, rate, channels)
    loaded = roundtrip(source)
    assert source.samples.flags.c_contiguous and not source.samples.flags.writeable
    assert loaded.format.sample_rate == rate and loaded.format.channels == 1
    assert source.duration == loaded.duration == 1
    np.testing.assert_array_equal(mono_pcm16(source.samples), loaded.samples[:, 0])
    direct = prepare_audio(source, decoder=deterministic_decoder, max_duration=120)
    via_wav = prepare_audio(loaded, decoder=deterministic_decoder, max_duration=120)
    np.testing.assert_array_equal(direct, via_wav)
    assert direct.dtype == np.float32 and direct.shape == (16000,)
    assert direct.flags.c_contiguous and np.isfinite(direct).all()
    for metric in (np.min, np.max, lambda x: np.sqrt(np.mean(x.astype(np.float64) ** 2)), lambda x: np.max(np.abs(x))):
        assert metric(direct) == metric(via_wav)
    if rate == 16000 and channels == 1:
        np.testing.assert_array_equal(direct, source.samples[:, 0].astype(np.float32) / 32768)
    if kind == "padded" and rate == 16000:
        assert np.all(direct[:4000] == 0) and np.all(direct[-4000:] == 0)


def test_half_pcm_unit_bound_and_round_to_even():
    values = np.array([[0, 1], [1, 2], [-1, 0], [-2, -1]], dtype=np.int16)
    np.testing.assert_array_equal(mono_pcm16(values), [0, 2, 0, -2])
    assert np.max(np.abs(mono_pcm16(values) - values.astype(np.float32).mean(axis=1))) == .5


@pytest.mark.parametrize("invalid", [np.zeros(5, dtype=np.int16), np.zeros((5, 0), dtype=np.int16),
                                    np.zeros((5, 2), dtype=np.float64), np.full((5, 1), np.nan, dtype=np.float32)])
def test_invalid_pcm_shape_dtype_and_finiteness(invalid):
    with pytest.raises(TranscriptionError, match="unsupported_audio"):
        mono_pcm16(invalid)


@pytest.mark.parametrize("converted", [np.zeros((5, 1), dtype=np.float32), np.zeros(5, dtype=np.float64),
                                      np.array([np.nan], dtype=np.float32), np.array([], dtype=np.float32)])
def test_decoder_contract_rejected(converted):
    with pytest.raises(TranscriptionError, match="unsupported_audio"):
        prepare_audio(audio(rate=8000), decoder=lambda _: converted, max_duration=120)


def test_noncontiguous_decoder_output_is_made_contiguous():
    values = np.arange(32000, dtype=np.float32)[::2] / 32768
    backing = np.zeros(32000, dtype=np.float32)
    backing[::2] = values
    prepared = prepare_audio(audio(rate=8000), decoder=lambda _: backing[::2], max_duration=120)
    assert prepared.flags.c_contiguous
    np.testing.assert_array_equal(prepared, values)


def test_explicit_disk_export_uses_same_codec(tmp_path):
    source = waveform("half", 16000, 2)
    path = save_wav(source, persistence_enabled=True)
    with io.BytesIO() as buffer:
        write_pcm_wav(source, buffer)
        assert path.read_bytes() == buffer.getvalue()
    np.testing.assert_array_equal(read_pcm_wav(path, 120).samples, roundtrip(source).samples)


class FakeVADModel:
    supported_languages = ["en", "hi"]

    def __init__(self, reject=False, cancel=None):
        self.calls = []
        self.vad_inputs = []
        self.reject = reject
        self.cancel = cancel

    def transcribe(self, samples, **kwargs):
        self.calls.append((samples.copy(), kwargs))
        self.vad_inputs.append(samples.copy())
        # Synthetic deterministic VAD only; no real VAD/model is imported.
        has_signal = bool(np.any(samples))
        item = segment(SECRET)
        if self.reject:
            item.no_speech_prob, item.avg_logprob = .9, -2
        if self.cancel is not None:
            self.cancel.set()
        return iter([item] if has_signal else []), SimpleNamespace(
            language="en", language_probability=.9,
            duration_after_vad=len(samples) / 16000 if has_signal else 0.0)


def engine_for(model, **settings):
    return ComparisonEngine(settings_snapshot(Settings(**settings)),
                            model_factory=lambda *a, **kw: model, decoder=deterministic_decoder)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("kind,reject", [("half", False), ("half", True), ("silence", False)])
def test_actual_model_vad_arguments_and_statuses(reverse, kind, reject):
    model = FakeVADModel(reject=reject)
    engine = engine_for(model, stt_language="en")
    report = compare_capture(waveform(kind, 44100, 2), engine, reverse=reverse)
    assert list(report["stt"]) == (["wav", "direct"] if reverse else ["direct", "wav"])
    assert report["pcm16_preserved"] and report["prepared_equal"]
    assert report["max_absolute_difference"] == 0
    np.testing.assert_array_equal(*model.vad_inputs)
    np.testing.assert_array_equal(model.calls[0][0], model.calls[1][0])
    assert model.calls[0][1] == model.calls[1][1]
    assert model.calls[0][1]["vad_filter"] is True and model.calls[0][1]["language"] == "en"
    assert model.calls[0][1]["vad_parameters"] == {"min_silence_duration_ms": 1000, "speech_pad_ms": 400}
    a, b = report["stt"]["direct"], report["stt"]["wav"]
    assert a["status"] == b["status"]
    assert a["rejection_reasons"] == b["rejection_reasons"]
    assert a["duration_after_vad"] == b["duration_after_vad"]
    assert a["segment_count"] == b["segment_count"] == (0 if kind == "silence" else 1)
    assert report["transcription_equal"] is (None if reject or kind == "silence" else True)
    assert engine._prepared == {} and engine._path is None
    assert SECRET not in json.dumps(report)


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("reject", [False, True])
def test_cli_transcript_opt_in_and_privacy(show, reject, caplog, tmp_path):
    output = []
    model = FakeVADModel(reject=reject)
    engines = []
    def factory(settings):
        engine = ComparisonEngine(settings, model_factory=lambda *a, **kw: model)
        engines.append(engine)
        return engine
    recorder = FakeRecorder()
    args = ["--show-successful-transcripts"] if show else []
    code = main(args, settings=Settings(), recorder=recorder, engine_factory=factory,
                read=lambda _: "", write=output.append)
    assert code == (1 if reject else 0)
    assert recorder.calls == [10.0]
    assert (SECRET in str(output)) is (show and not reject)
    assert SECRET not in caplog.text and SECRET not in repr(engines[0])
    report = json.loads(output[-1])
    if show:
        assert len(report["successful_transcripts"]) == (0 if reject else 2)
    else:
        assert "successful_transcripts" not in report
    assert list(tmp_path.iterdir()) == []
    assert engines[0]._prepared == {} and engines[0]._model is None


def test_cached_only_immutable_snapshot():
    original = Settings(stt_local_files_only=False, stt_language="hi")
    snapshot = settings_snapshot(original)
    assert snapshot.stt_local_files_only is True and original.stt_local_files_only is False
    assert snapshot.model_dump() == original.model_dump() | {"stt_local_files_only": True}
    with pytest.raises(ValidationError):
        snapshot.stt_vad_filter = False
    kwargs_seen = []
    def factory(*args, **kwargs):
        kwargs_seen.append(kwargs)
        return FakeVADModel()
    compare_capture(audio(), ComparisonEngine(snapshot, model_factory=factory))
    assert len(kwargs_seen) == 1 and kwargs_seen[0]["local_files_only"] is True


def test_uncached_engine_refused():
    engine = ComparisonEngine(Settings(), model_factory=lambda *a, **kw: pytest.fail("model accessed"))
    with pytest.raises(ValueError, match="invalid_parity_settings"):
        compare_capture(audio(), engine)


@pytest.mark.parametrize("answer", ["c", " ", "no"])
def test_only_explicit_enter_captures(answer):
    recorder = FakeRecorder()
    assert main([], settings=Settings(), recorder=recorder, read=lambda _: answer, write=lambda _: None) == 0
    assert recorder.calls == []


@pytest.mark.parametrize("when", ["before", "first_model", "second_model"])
def test_cancellation_discards_arrays_and_reports(when):
    cancel = Event()
    model = FakeVADModel()
    engine = engine_for(model)
    original = model.transcribe
    refs = []
    def transcribe(*args, **kwargs):
        refs.extend(weakref.ref(array) for array in engine._prepared.values())
        result = original(*args, **kwargs)
        if len(model.calls) == (1 if when == "first_model" else 2):
            cancel.set()
        return result
    model.transcribe = transcribe
    if when == "before":
        cancel.set()
    assert compare_capture(audio(), engine, cancel=cancel, show_successful_transcripts=True) is None
    gc.collect()
    assert all(ref() is None for ref in refs)
    assert engine._prepared == {}
    assert len(model.calls) == {"before": 0, "first_model": 1, "second_model": 2}[when]


def test_cli_cancellation_releases_capture_and_closes_memory_wav(monkeypatch):
    from app.stt import parity
    cancel = Event()
    refs, buffers, output = [], [], []
    class Recorder(FakeRecorder):
        def record(self, *args, **kwargs):
            result = super().record(*args, **kwargs)
            refs.append(weakref.ref(result.audio.samples))
            return result
    real_buffer = io.BytesIO
    def tracked_buffer():
        buffer = real_buffer()
        buffers.append(buffer)
        return buffer
    monkeypatch.setattr(parity.io, "BytesIO", tracked_buffer)
    model = FakeVADModel(cancel=cancel)
    assert main([], settings=Settings(), recorder=Recorder(), cancel=cancel,
                engine_factory=lambda settings: ComparisonEngine(settings, model_factory=lambda *a, **kw: model),
                read=lambda _: "", write=output.append) == 0
    gc.collect()
    assert all(ref() is None for ref in refs)
    assert buffers and all(buffer.closed for buffer in buffers)
    assert not any(line.startswith("{") for line in output)
    assert SECRET not in str(output)


def test_safe_exception_and_missing_cache_no_download(caplog):
    output, kwargs_seen = [], []
    def unavailable(*args, **kwargs):
        kwargs_seen.append(kwargs)
        raise ValueError(SECRET)
    assert main([], settings=Settings(stt_local_files_only=False), recorder=FakeRecorder(),
                engine_factory=lambda settings: ComparisonEngine(settings, model_factory=unavailable),
                read=lambda _: "", write=output.append) == 1
    assert all(kwargs["local_files_only"] for kwargs in kwargs_seen)
    assert SECRET not in str(output) + caplog.text
    report = json.loads(output[-1])
    assert report["stt"]["direct"]["status"] == "failed"
    assert report["transcription_equal"] is None


def test_success_vad_metadata_is_cleared_on_cancel():
    from app.stt.models import TranscriptionRequest
    engine = engine_for(FakeVADModel())
    result = engine.transcribe(TranscriptionRequest(audio=audio()))
    assert result.duration_after_vad == 1
    cancel = Event()
    cancel.set()
    cancelled = apply_output_safety(result, engine.settings, cancel)
    assert cancelled.status == TranscriptionStatus.CANCELLED
    assert cancelled.duration_after_vad is None and cancelled.safety_summary is None


def test_cli_reverse_and_allowlisted_report():
    output = []
    model = FakeVADModel()
    assert main(["--reverse-order"], settings=Settings(), recorder=FakeRecorder(),
                engine_factory=lambda settings: ComparisonEngine(settings, model_factory=lambda *a, **kw: model),
                read=lambda _: "", write=output.append) == 0
    report = json.loads(output[-1])
    assert list(report["stt"]) == ["wav", "direct"]
    assert set(report) == {"source", "pcm16_preserved", "prepared", "prepared_equal",
                           "max_absolute_difference", "stt", "transcription_equal"}
    assert report["source"] == {"sample_rate": 16000, "channel_count": 1, "frame_count": 16000,
                                "dtype": "int16", "shape": [16000, 1], "duration": 1.0,
                                "rms": 1 / 32768, "peak": 1 / 32768}


@pytest.mark.parametrize("reverse", [False, True])
def test_equal_audio_can_have_different_backend_transcripts(reverse):
    class Stateful(FakeVADModel):
        def transcribe(self, samples, **kwargs):
            _, info = super().transcribe(samples, **kwargs)
            return iter([segment("first" if len(self.calls) == 1 else "second")]), info
    report = compare_capture(audio(), engine_for(Stateful()), reverse=reverse,
                             show_successful_transcripts=True)
    assert report["prepared_equal"] and not report["transcription_equal"]
    assert report["successful_transcripts"]["wav" if reverse else "direct"] == "first"


@pytest.mark.parametrize("status", ["cancelled", "failed"])
def test_unsuccessful_capture_never_constructs_model(status):
    def forbidden(*args):
        pytest.fail("Engine must not be constructed")
    output = []
    code = main([], settings=Settings(), recorder=FakeRecorder(status), engine_factory=forbidden,
                read=lambda _: "", write=output.append)
    assert code == (0 if status == "cancelled" else 1)
    assert not any(line.startswith("{") for line in output)


def test_cancel_during_resampling_never_loads_model():
    cancel = Event()
    def decoder(buffer):
        cancel.set()
        return deterministic_decoder(buffer)
    engine = ComparisonEngine(settings_snapshot(Settings()), decoder=decoder,
                              model_factory=lambda *a, **kw: pytest.fail("Model accessed after cancellation"))
    assert compare_capture(audio(rate=8000), engine, cancel=cancel) is None
    assert engine._prepared == {}


def test_invalid_stream_is_safe_and_not_closed_by_reader():
    with io.BytesIO(b"not a valid WAV") as buffer:
        with pytest.raises(TranscriptionError, match="invalid_wav"):
            read_pcm_wav_stream(buffer, 120)
        assert not buffer.closed


def test_main_capture_exception_never_exposes_details(caplog):
    class Broken(FakeRecorder):
        def record(self, *args, **kwargs):
            raise ValueError(SECRET)
    output = []
    assert main([], settings=Settings(), recorder=Broken(), read=lambda _: "", write=output.append) == 1
    assert output[-1] == "Parity error: comparison_failed"
    assert SECRET not in str(output) + caplog.text


def test_stream_permission_failure_preserves_safe_error_code():
    class Unreadable(io.BytesIO):
        def read(self, *args):
            raise PermissionError(SECRET)
    with Unreadable(b"synthetic") as buffer:
        with pytest.raises(TranscriptionError, match="permission_denied") as caught:
            read_pcm_wav_stream(buffer, 120)
    assert SECRET not in str(caught.value)
