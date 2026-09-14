import importlib
import pytest
from pydantic import ValidationError
from app.speaker.models import EnrollmentConsent, SpeakerConfiguration, SpeakerProfile

@pytest.mark.parametrize("module", ["models","contracts","quality","embedding","enrollment","verification",
    "profiles","protection","thresholds","antispoof","pipeline","evaluate","cli"])
def test_imports_no_hardware(module):
    assert importlib.import_module("app.speaker."+module)

@pytest.mark.parametrize("changes", [
    {"min_samples":2},{"max_samples":6},{"enrollment_samples":6},{"min_samples":5},
    {"min_duration":3,"max_duration":2},{"min_rms":0},{"max_clipping":2},
    {"embedding_dimension":0},{"secure_profiles_required":False},{"local_files_only":False},
    {"acceptance_threshold":float("nan")},{"rejection_threshold":.9},
    {"acceptance_threshold":.5,"rejection_threshold":.9},{"schema_version":2}])
def test_bad_configuration(changes):
    with pytest.raises(ValidationError):
        SpeakerConfiguration(**changes)

def test_consent_strict():
    with pytest.raises(ValidationError): EnrollmentConsent(enrollment="yes")

def test_profile_private(profile):
    assert "template" not in profile.model_dump()
    assert "template" not in profile.model_dump_json()
    assert "template" not in repr(profile)
    assert not profile.template.flags.writeable
    with pytest.raises(ValueError): profile.template.flags.writeable = True

def test_settings_safe(tmp_path, monkeypatch):
    from app.core.config import Settings
    monkeypatch.setenv("VOICEPILOT_SPEAKER__MIN_DURATION","4")
    monkeypatch.setenv("VOICEPILOT_SPEAKER__PROFILE_ROOT",str(tmp_path/"not-created"))
    settings=Settings()
    assert settings.speaker.min_duration == 4
    assert settings.speaker.acceptance_threshold is None
    assert not settings.speaker_verification_enabled
    assert not (tmp_path/"not-created").exists()
    assert str(tmp_path) not in repr(settings)
    assert str(tmp_path) not in settings.model_dump_json()

def test_example_environment():
    from app.core.config import Settings
    settings=Settings(_env_file=".env.example")
    assert settings.speaker.sample_rate==16000
    assert settings.speaker.enrollment_samples==4
    assert settings.speaker.local_files_only is True
    assert settings.speaker.secure_profiles_required is True
    assert settings.speaker.acceptance_threshold is None

@pytest.mark.parametrize("changes",[
    {"sample_rate":True},{"embedding_dimension":True},{"min_duration":True},
    {"local_files_only":"false"},{"secure_profiles_required":1},
    {"acceptance_threshold":True}])
def test_unsafe_environment_configuration(changes):
    with pytest.raises(ValidationError): SpeakerConfiguration(**changes)

@pytest.mark.parametrize("template",["PRIVATE_TEMPLATE",[float("nan"),0,0],[0,0,0],[2,0,0]])
def test_private_validation_errors(profile,template):
    from app.speaker.contracts import SpeakerError
    values=profile.model_dump() | {"template":template}
    for constructor in (lambda: SpeakerProfile(**values),lambda: SpeakerProfile.model_validate(values)):
        with pytest.raises(SpeakerError,match="^invalid_profile$") as error:
            constructor()
        assert not hasattr(error.value,"errors")
        assert "PRIVATE" not in repr(error.value)

def test_schema_has_no_private_defaults():
    import json
    schema=json.dumps(SpeakerProfile.model_json_schema())
    assert "PRIVATE" not in schema
