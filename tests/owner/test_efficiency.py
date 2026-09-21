"""Fake-only reuse, bounded timing and terminal-path resource checks."""
import gc
import json
from threading import Event
from types import SimpleNamespace
from uuid import uuid4
import weakref

import numpy as np
import pytest

from app.core import timing
from app.owner.cli import main
from app.owner.models import OwnerError, State
from app.owner.runtime import Runtime
from app.owner.timing_evaluation import evaluate
from tests.speaker.conftest import FakeProtector
from tests.audio.test_recorder import FakeBackend as AudioBackend


def test_numerical_report_closed_bounded_and_optional():
    report = timing.Report(clock=lambda: 1.)
    with timing.span("capture"):
        pass
    assert report.document()["samples"] == []
    report.add("PRIVATE_TRANSCRIPT", .1)
    report.add("capture", "PRIVATE_PATH")
    report.add("capture", float("nan"))
    report.add("capture", .1, "PRIVATE_SCORE")
    token = timing.activate(report)
    try:
        for _ in range(140):
            with timing.span("capture"):
                pass
        timing.begin("capture")
    finally:
        timing.deactivate(token)
    assert len(report.document()["samples"]) == timing.LIMIT == 128
    assert not report._starts
    assert "PRIVATE" not in json.dumps(report.document())
    assert report.document()["unit"] == "seconds"
    report.add("total_after_consent", 2.)
    assert len(report.document()["samples"]) == 128
    assert report.document()["samples"][-1]["stage"] == "total_after_consent"


def test_broken_diagnostic_clock_does_not_change_control_flow():
    def broken():
        raise RuntimeError("PRIVATE_CLOCK")
    report = timing.Report(clock=broken)
    token = timing.activate(report)
    try:
        with timing.span("capture"):
            result = 123
    finally:
        timing.deactivate(token)
    assert result == 123 and report.document()["samples"] == []


def test_fake_timing_evaluation_denominators_and_cold_warm():
    result = evaluate()
    assert result["sessions"] == result["verified_sessions"] == 2
    assert result["captures"] == result["speaker_calls"] == result["stt_calls"] == 6
    assert result["speaker_initializations"] == result["stt_initializations"] == 1
    assert result["volume_reads"] == 4  # One baseline, one independent read-back.
    rows = result["timings"]["samples"]
    for stage in ("speaker_inference", "stt_inference"):
        assert [row["temperature"] for row in rows if row["stage"] == stage] == ["cold"] + ["warm"] * 5
    assert all(set(row) == {"stage", "seconds", "temperature", "completed"} for row in rows)
    assert {row["stage"] for row in rows} >= {"consent_to_phrase_display", "phrase_display_to_enter",
        "recorder_setup", "capture", "command_capture", "phrase_stt", "command_stt",
        "planning", "execution", "observation", "verification", "total_after_consent"}


def test_timing_cli_is_safe_and_opt_in(harness):
    output = []
    def forbidden(*args, **kwargs):
        pytest.fail("runtime_created")
    assert main(["evaluate-timings"], factory=forbidden, write=output.append) == 0
    assert json.loads(output[-1])["verified_sessions"] == 2
    assert main(["owner", "--profile", str(harness.profile.profile_id), "--environment", "quiet", "--timings"],
                factory=forbidden, interactive=lambda: False, write=output.append) == 2
    assert json.loads(output[-1])["reason"] == "consent_required"


def test_cli_timing_cleanup_and_default_no_report(harness):
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    runtime = SimpleNamespace(calibration=lambda: harness.calibration)
    for enabled in (False, True):
        output = []
        args = ["owner", "--profile", str(key), "--environment", "quiet"] + (["--timings"] if enabled else [])
        assert main(args, settings=harness.settings, factory=lambda *a, **k: runtime,
                    read=lambda _: "CONSENT OWNER", write=output.append, interactive=lambda: True) == 0
        reports = [json.loads(line) for line in output if line.startswith('{') and 'opt_in_numerical_timings' in line]
        assert len(reports) == int(enabled)
        if enabled:
            assert all(set(row) == {"stage", "seconds", "temperature", "completed"} for row in reports[0]["samples"])
        assert timing._ACTIVE.get() is None


def test_runtime_reuses_stt_service_and_model_for_distinct_captures(harness, monkeypatch):
    import app.stt.faster_whisper_engine as module
    from tests.stt import segment
    original = module.FasterWhisperEngine
    initialized = []
    prepared = []
    closed = []
    class Model:
        supported_languages = ["en"]
        def transcribe(self, samples, **kwargs):
            prepared.append(weakref.ref(samples))
            def stream():
                try:
                    yield segment("A blue notebook rests beside the quiet garden window.")
                finally:
                    closed.append(True)
            return stream(), SimpleNamespace(language="en", language_probability=.9)
    def factory(*args, **kwargs):
        initialized.append(True)
        return Model()
    monkeypatch.setattr(module, "FasterWhisperEngine", lambda cfg: original(cfg, model_factory=factory))
    runtime = Runtime(harness.settings)
    assert runtime._stt is None and initialized == []
    results = []
    for _ in range(2):
        audio = harness.capture("synthetic", uuid4(), uuid4(), guard=lambda: None)
        results.append(runtime.transcribe_audio(audio, audio_id=uuid4()))
    assert all(result.status == "succeeded" for result in results)
    assert results[0].cold_start is True and results[1].cold_start is False
    assert results[0].audio_id != results[1].audio_id
    assert len(initialized) == 1 and len(closed) == 2
    gc.collect()
    assert all(reference() is None for reference in prepared)


def test_speaker_one_initialization_fresh_streams_and_no_retained_buffers(harness):
    from app.speaker.sherpa_backend import SherpaEmbeddingEngine
    from app.speaker.models import SpeakerConfiguration
    streams, buffers, calls = [], [], []
    class Stream:
        def accept_waveform(self, *, sample_rate, waveform):
            buffers.append(weakref.ref(waveform))
        def input_finished(self):
            pass
    class Extractor:
        dim = 256
        def create_stream(self):
            stream = Stream()
            streams.append(weakref.ref(stream))
            return stream
        def is_ready(self, stream):
            return True
        def compute(self, stream):
            return np.ones(256)
    def factory(path):
        calls.append(True)
        return Extractor()
    engine = SherpaEmbeddingEngine("synthetic.onnx", SpeakerConfiguration(),
                                  factory=factory, inspector=lambda _: None)
    report = timing.Report()
    token = timing.activate(report)
    try:
        for _ in range(2):
            audio = harness.capture("synthetic", uuid4(), uuid4(), guard=lambda: None)
            engine.extract(audio)
    finally:
        timing.deactivate(token)
    gc.collect()
    assert len(calls) == 1 and len(streams) == 2
    assert all(reference() is None for reference in [*streams, *buffers])
    rows = report.document()["samples"]
    assert [r["temperature"] for r in rows if r["stage"] == "speaker_inference"] == ["cold", "warm"]
    assert sum(r["stage"] == "speaker_model_load" for r in rows) == 1


@pytest.mark.parametrize("fault", ["success", "phrase", "speaker", "uncertain", "expiry", "cancel", "model", "stt", "backend"])
def test_pilot_terminal_cleanup(calibrated, fault):
    h = calibrated
    if fault == "phrase":
        h.phrase_wrong = True
    elif fault == "speaker":
        h.score = .2
    elif fault == "uncertain":
        h.score = .88
    elif fault == "expiry":
        h.before_capture = lambda: setattr(h, "now", 100.)
    elif fault == "cancel":
        h.before_capture = h.pilot.cancel.set
    elif fault == "model":
        def failed(*args, **kwargs):
            raise RuntimeError("PRIVATE_MODEL")
        h.calibration.engine.extract = failed
    elif fault == "stt":
        def failed(*args, **kwargs):
            raise RuntimeError("PRIVATE_STT")
        h.calibration.stt = SimpleNamespace(transcribe_audio=failed)
    elif fault == "backend":
        h.backend.fail_write = True
    report = timing.Report(clock=lambda: h.now)
    token = timing.activate(report)
    try:
        result = h.pilot.run(h.profile.profile_id)
    finally:
        timing.deactivate(token)
    assert (result.status == "completed") == (fault == "success")
    assert not h.challenges.pending and not h.pilot._evidence and h.pilot._admission is None
    assert not h.hub._active and not h.pilot._lock.locked() and not h.pilot.operations.lock.locked()
    if fault not in {"success", "backend"}:
        assert h.stt_calls <= 1 and h.backend.mutations == 0
    assert "PRIVATE" not in json.dumps(report.document()) + result.model_dump_json()


def test_storage_writes_only_when_selected_state_changes(calibrated, monkeypatch):
    h = calibrated
    calls = []
    save = h.store.save
    def written(*args, **kwargs):
        calls.append(True)
        return save(*args, **kwargs)
    monkeypatch.setattr(h.store, "save", written)
    key = h.profile.profile_id
    h.calibration.status(key)
    assert calls == []
    h.calibration.change(key, "suspend", consent=True)
    h.calibration.evaluate(key)
    before = h.store.load(key).document()
    count = len(calls)
    h.calibration.evaluate(key)
    assert len(calls) == count and h.store.load(key).document() == before
    h.calibration.change(key, "revoke", consent=True)
    before = h.store.load(key).document()
    count = len(calls)
    h.calibration.change(key, "revoke", consent=True)
    assert len(calls) == count and h.store.load(key).document() == before


def test_operation_single_readback_no_retry(calibrated):
    h = calibrated
    h.backend.false_success = True
    result = h.pilot.run(h.profile.profile_id)
    assert result.status == "blocked" and h.backend.reads == 2 and h.backend.mutations == 1
    assert len(h.pilot.operations.history_snapshot()) == 1


def test_launch_polling_bounded_without_second_launch(monkeypatch):
    from tests.launch.helpers import Backend, Clock, grant
    from app.launch.controller import LaunchController
    clock = Clock()
    backend = Backend(clock)
    backend.match = False
    monkeypatch.setattr(Event, "wait", lambda self, timeout=None: None)
    driver = LaunchController(backend=backend, clock=clock)
    result = driver.run(*grant())
    assert not result.process_observed and backend.created == 1
    assert backend.calls.count("observe") <= 302
    assert driver._active is None and not driver._lock.locked()



@pytest.mark.parametrize("stage", ["setup", "capture", "inference"])
def test_cancellation_during_work_releases_challenge_without_storage_change(harness, monkeypatch, stage):
    import app.audio.recorder as module
    h = harness
    key = h.profile.profile_id
    h.calibration.begin(key, consent=True)
    before = h.store.load(key).document()
    event = Event()
    h.calibration.cancel = event
    recordings = []
    def extract(audio, **kwargs):
        event.set()
        return [1., 0., 0.]
    class Recorder:
        def __init__(self, settings):
            if stage == "setup":
                event.set()
        def record(self, *args, **kwargs):
            recordings.append(True)
            audio = h.capture("synthetic", uuid4(), uuid4(), guard=lambda: None)
            if stage == "capture":
                event.set()
            return SimpleNamespace(status="succeeded", audio=audio,
                device=SimpleNamespace(index=1, name="synthetic", max_input_channels=1, default_sample_rate=16000))
    monkeypatch.setattr(module, "SoundDeviceRecorder", Recorder)
    runtime = Runtime(h.settings, read=lambda _: "", write=lambda _: None)
    h.calibration.present = runtime.present_challenge
    h.calibration.capture = runtime.capture
    if stage == "inference":
        h.calibration.engine.extract = extract
    with pytest.raises(OwnerError, match="cancelled"):
        h.calibration.collect(key, "owner", "quiet", consent=True)
    assert len(recordings) == (0 if stage == "setup" else 1)
    assert h.stt_calls == 0 and not h.challenges.pending
    assert h.store.load(key).document() == before


def test_early_denial_never_initializes_models(harness):
    def forbidden(*args, **kwargs):
        pytest.fail("model_or_stt_called_before_approval")
    harness.calibration.engine.extract = forbidden
    harness.calibration.stt = SimpleNamespace(transcribe_audio=forbidden)
    result = harness.pilot.run(harness.profile.profile_id)
    assert result.reason == "calibration_required"
    assert harness.capture_count == 0 and harness.backend.mutations == 0


def test_native_volume_resources_close_without_native_access(monkeypatch):
    from contextlib import contextmanager
    from app.operations import windows
    released = []
    initialized = []
    control = object()
    @contextmanager
    def com():
        initialized.append(True)
        try:
            yield object()
        finally:
            released.append("com")
    monkeypatch.setattr(windows, "com", com)
    monkeypatch.setattr(windows, "instantiate", lambda *a: control)
    monkeypatch.setattr(windows, "release", lambda obj: released.append("interface") if obj else None)
    def fail(*args):
        raise RuntimeError("synthetic_native_failure")
    monkeypatch.setattr(windows, "call", fail)
    with pytest.raises(RuntimeError):
        with windows.endpoint():
            pytest.fail("unavailable_endpoint")
    assert len(initialized) == 1 and released == ["interface", "com"]



@pytest.mark.parametrize("accepted", [True, False])
def test_protected_storage_operation_counts_without_real_dpapi(harness, tmp_path, accepted):
    from app.owner.storage import Store
    h = harness
    key = h.profile.profile_id
    h.calibration.begin(key, consent=True)
    class CountingProtector(FakeProtector):
        encryptions = 0
        decryptions = 0
        def protect(self, value):
            self.encryptions += 1
            return super().protect(value)
        def unprotect(self, value):
            self.decryptions += 1
            return super().unprotect(value)
    protector = CountingProtector()
    store = Store(tmp_path, protector=protector, provisioner=lambda root: None)
    store.save(key, h.store.load(key))
    protector.encryptions = protector.decryptions = 0
    h.calibration.store = store
    reads = []
    load = h.repository.load
    def profile(identifier):
        reads.append(True)
        return load(identifier)
    h.repository.load = profile
    h.phrase_wrong = not accepted
    if accepted:
        h.calibration.collect(key, "owner", "quiet", consent=True)
    else:
        with pytest.raises(OwnerError, match="phrase_mismatch"):
            h.calibration.collect(key, "owner", "quiet", consent=True)
    assert protector.encryptions == int(accepted)
    assert protector.decryptions == (5 if accepted else 1)
    assert len(reads) == (3 if accepted else 1)
    assert not list(tmp_path.glob(".owner-*.tmp"))



@pytest.mark.parametrize("delayed", ["discovery", "construction"])
def test_expiry_inside_recorder_never_opens_or_starts_late(harness, monkeypatch, delayed):
    import app.audio.recorder as module
    h = harness
    key = h.profile.profile_id
    h.calibration.begin(key, consent=True)
    before = h.store.load(key).document()
    backend = AudioBackend()
    query, construct = backend.query_devices, backend.RawInputStream
    def slow_query():
        h.now += 45
        return query()
    def slow_construct(**kwargs):
        value = construct(**kwargs)
        h.now += 45
        return value
    if delayed == "discovery":
        backend.query_devices = slow_query
    else:
        backend.RawInputStream = slow_construct
    monkeypatch.setattr(module, "load_backend", lambda: backend)
    runtime = Runtime(h.settings, read=lambda _: "", write=lambda _: None)
    h.calibration.capture, h.calibration.present = runtime.capture, runtime.present_challenge
    with pytest.raises(OwnerError, match="challenge_expired"):
        h.calibration.collect(key, "owner", "quiet", consent=True)
    assert "start" not in backend.calls
    if delayed == "discovery":
        assert "construct" not in backend.calls
    else:
        assert backend.calls[-2:] == ["abort", "close"]
    assert not h.challenges.pending and h.store.load(key).document() == before
