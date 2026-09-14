# 0007: Speaker verification foundation

Status: Phase 4A only. Real inference and profile protection unavailable.

Decision: keep replaceable typed boundaries; perform no biometric provisioning.
The prototype cannot authorize actual commands. Future runtime is a separate decision.

## Phase 4A speaker-verification foundation

Phase 4A implements fake-backed enrollment, numerical quality/embedding checks,
protected-storage contracts, nominated-profile verification, a fail-closed gateway
and synthetic evaluation. Real speaker recognition is unavailable. Phase 4B
runtime/model provisioning requires separate approval; no dependency is added.

Safe inspection commands (no microphone, models, profiles or recordings are opened):

```powershell
.\venv\Scripts\python.exe -m app.speaker.cli inspect-status
.\venv\Scripts\python.exe -m app.speaker.cli inspect-policy
.\venv\Scripts\python.exe -m app.speaker.cli validate-schema
.\venv\Scripts\python.exe -m app.speaker.cli evaluate --synthetic
```

`profiles list`, `enroll` and `verify` report unavailable with exit code 2.
No CLI argument turns on real biometric capability. Existing standalone STT,
parity and text resolver commands remain diagnostic tools, not authorization.

Enrollment requires separate enrollment and persistence consent; 3-5 distinct
capture IDs/buffers; valid quality and embeddings; all-pair consistency; and an
equal-weight normalized aggregate. Failed or cancelled re-enrollment preserves
the previous profile. There is no automatic research audio retention. A future
retention path requires separate consent and implementation approval.

The gateway invokes fresh verification for each opaque audio ID and forwards the
same original buffer only after a verified result under a validated policy.
Synthetic/pending policies and every nonverified status block both STT and
resolution. Inject the existing safety-applying TranscriptionService and
non-executing CommandResolver. The gateway has no execution API. Dependencies
are trusted application code, not user plugins; Python interfaces are not a
sandbox against code executing in the same process.

Secure storage defaults to unavailable: no real DPAPI adapter or key is provided.
The repository abstraction writes only protector output, uses bounded private
decoding and same-directory atomic replacement, rejects unsafe identifiers and
symlink/junction paths, and never creates a root. Caller provisioning must supply
an audited protector and a directory with restrictive ACLs. Tests use opaque
in-memory tokens, NOT encryption. No insecure homemade cryptography is used.

Future profile root: `%LOCALAPPDATA%\VoicePilot\speaker-profiles\`, outside
the repository/OneDrive. Configuration imports create no directories. Explicit
private serialization is restricted to storage; normal dumps/repr omit templates.
Schemas include model revision/hash, preprocessing, dimension, count, timestamps
and policy/calibration state. Delete removes the profile; there is no template
cache. Failed atomic replacement retains the previous profile. Cancellation is
cooperative before the atomic commit; cancellation after commit is not rollback.
A failed temporary-file cleanup can leave protected bytes, never plaintext.

Voice matching protects VoicePilot actions only, not Windows authentication or
the complete laptop. It does not prove consent to a command, liveness, replay
resistance or authenticity. Default anti-spoof evidence is unavailable and results
say `spoof_assurance=not_assessed`. Similar voices, replay, generated/cloned speech,
noise and overlapping speakers remain threats. Numerical quality/consistency
checks cannot reliably detect those attacks. High-risk future actions need an
additional factor. Embeddings are biometric, not anonymous or guaranteed
irreversible. Git ignore is not access control. Python cannot guarantee memory
erasure; profile deletion cannot erase copies/backups. Future current-user DPAPI
does not defend against malware running as the same Windows user. Recovery,
ACL provisioning and DPAPI testing remain Phase 4B prerequisites.

Settings use `VOICEPILOT_SPEAKER__<FIELD>` nested overrides, alongside the existing
disabled `VOICEPILOT_SPEAKER_VERIFICATION_ENABLED` flag. Paths are excluded from
normal settings serialization. Defaults: 16 kHz; 256 dimensions; target 4 samples
within 3-5; 3-30 seconds; minimum RMS .005; maximum clipping fraction .01;
cross-sample cosine .7; schema 1; secure protection and local-files-only required.
These are unvalidated engineering starting points. Acceptance/review thresholds
are unset, policy version calibration-pending. Model/policy paths are unset.
Setting the enabled flag alone cannot provision or calibrate a backend.

Cosine score is similarity, never probability: score >= acceptance is verified;
review <= score < acceptance is uncertain; lower is rejected. Without a review
band, all scores below acceptance are rejected. Nonfinite, unordered or missing
policies fail closed. Thresholds are never weakened automatically. Synthetic
policies exercise services, but cannot authorize the gateway; production needs
a reviewed validated policy bound to the exact model and profile.

Future candidate: WeSpeaker ResNet34 ONNX through sherpa-onnx. Phase 4B must
separately approve binary-only Windows/Python 3.12 runtime provisioning, model
source/license/hash, exact audio preparation, private storage/DPAPI/ACL lifecycle
and consented calibration. Preserve Python 3.12.10 and this venv. There are no
measured Hindi, Marathi or Indian-accent results.

Synthetic evaluation defines genuine = enrolled target matches probe speaker;
impostor = different speakers. Uncertain means nonacceptance:
FAR = FA/(FA+TR), FRR = FR/(TA+FR), genuine acceptance = TA/(TA+FR),
impostor rejection = TR/(TR+FA). Denominators include scored trials only.
Coverage = scored/all trials; uncertainty = uncertain/scored; decisive coverage
= (scored-uncertain)/all. End-to-end genuine denial = (all genuine-TA)/all genuine.
Zero denominators return null. Failure-to-enroll, invalid audio (failure-to-acquire),
invalid profile, unavailable and cancelled outcomes remain separately counted.

EER is an estimate from an empirical acceptance-threshold sweep, including a
conceptual reject-all endpoint (null threshold), with linear interpolation between
adjacent FAR-FRR sign changes. Equal scores move together. It is not a recommended
operational threshold. The demo has TA=2, FR=2, FA=1, TR=3; FAR=1/4, FRR=2/4,
uncertainty=2/8, coverage=8/8, EER estimate=.5. These are deliberately synthetic
pipeline results, NOT biometric performance claims.

Research needs consented multiple speakers/sessions, English/Hindi/Marathi/mixed
speech, noise/device strata, separate replay trials, locked validation-only
calibration and held-out test trials. Development/calibration/test speaker cohorts
must be disjoint; within each cohort target enrollment/probes share identity but
not recording/session. Trial validation rejects duplicate IDs, cross-cohort
speaker/session/recording reuse and enrollment/probe recording reuse. Real corpus
ingestion, consent receipts, audio hashes/segment ancestry validation and identity
mapping are deferred, not implied by synthetic labels. Report per-language/overall
scores, curves, latency/resources and speaker-aware confidence intervals.
One-speaker results are personal development validation only.

See docs/decisions/0007-speaker-verification-foundation.md for the scoped decision.
