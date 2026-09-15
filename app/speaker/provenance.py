"""Private enrollment binding; digests are identifiers, never authentication."""
import hashlib
import json
import re
import numpy as np
from app.speaker.contracts import SpeakerError

def binding(profile):
    try:
        if profile.enrollment_session is None or not profile.enrollment_hashes:
            raise ValueError()
        if any(re.fullmatch(r"[0-9a-f]{64}", h) is None for h in profile.enrollment_hashes):
            raise ValueError()
        document = dict(profile_id=str(profile.profile_id),
            enrollment_session=str(profile.enrollment_session),
            enrollment_hashes=profile.enrollment_hashes,
            schema_version=profile.schema_version, sample_count=profile.sample_count,
            created_at=profile.created_at.isoformat(), updated_at=profile.updated_at.isoformat(), model=profile.model.model_dump(mode="json"),
            template_sha256=hashlib.sha256(np.asarray(profile.template, dtype="<f8").tobytes()).hexdigest())
        return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    except Exception:
        raise SpeakerError("incompatible_profile") from None
