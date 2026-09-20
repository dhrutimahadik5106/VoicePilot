# 0008: Real local speaker verification (Phase 4B)

Approved scope: local WeSpeaker inference, current-user DPAPI, deliberate enrollment,
verification, private calibration and the existing non-executing STT gateway.
No microphone or real-person evaluation was performed during implementation.

## Runtime and official artifact

Python 3.12.10 and the existing venv are preserved. The only new direct dependency
is `sherpa-onnx==1.13.8`; its required runtime is `sherpa-onnx-core==1.13.8`.
No Torch, torchaudio, SpeechBrain, extra ONNX package or build tools are required.
Runtime code is Apache-2.0; the model weights have separate attribution obligations.

- Filename: `wespeaker_en_voxceleb_resnet34.onnx`
- Model: WeSpeaker ResNet34, VoxCeleb, 256-dimensional embedding, 16 kHz.
- Size: **26,534,365 bytes**.
- SHA-256: `5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94`.
- [Official artifact](https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_en_voxceleb_resnet34.onnx).
- [Publisher checksums](https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/checksum.txt).
- WeSpeaker pretrained weights inherit the dataset licence; VoxCeleb weights are
  listed as **CC-BY-4.0** in the [upstream pretrained-model documentation](https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md).
  Attribute WeSpeaker/VoxCeleb and preserve the source and licence when redistributing.
- [Official sherpa example](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/python-api-examples/speaker-identification.py).

Provisioning is explicit. The default ignored location is `models/speaker/`.
`MODEL_PATH` may select another ONNX path. Existing artifacts must match the pinned
checksum; they are never silently replaced. Download uses the official HTTPS source,
a bounded temporary file (32 MB maximum), SHA-256 verification, native graph parsing
and dimension validation before activation. An ignored public receipt records the
source, licence, bytes, hash and retrieval date. There is no import-time download.
The artifact was provisioned and its native synthetic smoke check passed locally.

Quality checks precede inference. Shared STT preprocessing converts captured PCM16
to mono contiguous finite float32. The sherpa API receives normalized samples;
its model metadata requests internal PCM scaling, so this adapter must not scale
again. No gain adjustment, silence trimming, VAD threshold change or model swap
is introduced. CPU inference is lazy, one thread, debug disabled. Output must be
finite, dimension 256, nonzero and L2 normalized. No embedding is printed.

## Protection and lifecycle

Defaults remain disabled and calibration-pending. Enrollment requires separate
capture/enrollment and persistence consents, then deliberate Enter for every sample.
Four samples are requested by default, with a supported range of three to five.
Neutral prompts are not secrets. Each recording is bounded (8 seconds by default),
with at most two retries for unusable captures. Escape by declining a prompt, typing
anything instead of Enter, or using recording cancellation. No WAV is written.
Embedding/backend failures abort without replacing the profile.

Profiles default to `LOCALAPPDATA/VoicePilot/speaker-profiles`; calibration records
default to `LOCALAPPDATA/VoicePilot/speaker-calibration`. Roots must be absolute,
outside the repository and known OneDrive paths, with no junction/symlink ancestors.
Provisioning applies a protected DACL granting owner rights and SYSTEM full control
before storing data. Unknown synchronization software is not detectable automatically.

DPAPI protects the complete serialized profile/record using current-user scope,
UI forbidden and fixed application entropy (domain separation, not a secret key).
There is no plaintext fallback. Files and decrypted payloads are bounded to 128 KiB;
UUID filenames, schema checks and atomic protected writes fail closed. Temporary files
contain ciphertext only. Native temporary buffers are cleared and LocalFree is used.
Python objects and library copies cannot be guaranteed securely erased. DPAPI does not
protect against malware running as the same user, administrators with sufficient
access, or loss of the Windows account/key material. Deletion cannot erase copies or
backups. A separate-user decryption test has not been performed; mocked rejection is
covered. Actual current-user marker encryption and restricted-directory persistence
were tested without biometric data.

## Calibration provenance correction

The interrupted implementation checked model compatibility but did not bind evidence
to the current enrollment. An older enrollment's scores could approve a replacement
profile. That behavior is now rejected.

Every new private trial includes a SHA-256 binding of the exact profile UUID,
enrollment-session UUID, enrollment-audio digests, exact template bytes, model name,
revision, publisher checksum, preprocessing version, dimension, profile schema,
sample count and creation/update timestamps. Approval binds its resulting protected
profile revision separately, so later metadata changes also invalidate that policy. Trial target, session, enrollment
hashes and model are also compared explicitly during approval. Missing, stale,
mixed or incompatible evidence is not migrated or reinterpreted. All selected
frozen trials must refer to the nominated current enrollment.

Digests are non-secret provenance identifiers, not encryption, authentication,
identity evidence or replay protection. They remain in DPAPI-protected records,
excluded from normal trial serialization/repr. Validation errors become safe reason
codes. Template bytes remain exact across profile validation and protected round trips.

Successful consented enrollment writes a fresh session, resets calibration to pending
and resets the policy version. The approved policy stores the same private binding;
policy loading recomputes it, and verification reloads/checks profile-policy identity.
Old policy records remain inert, not deleted or reused. A failed/cancelled replacement
leaves the previous atomic profile and approval intact. The filesystem is not a
multi-process transaction manager: operators must not perform concurrent profile
mutation/review; same-user malicious file/process manipulation is outside DPAPI's
protection model.

## Private evaluation and authorization

Collection requires informed consent for private score persistence; an impostor must
give their own consent. Metadata uses UUID pseudonyms, sessions, recording groups,
language (en/hi/mr/mixed), and condition (quiet/noise/other). Audio is not retained.
Use the profile UUID as the genuine speaker UUID. Keep speaker pseudonyms stable;
use a new session UUID only for a genuinely separate session. Related variants share
a recording-group UUID. Enrollment recordings cannot be reused as probes. Exact
hash duplicates and cross-split speaker/session/group leakage are rejected.

Freeze an operator-selected threshold using validation evidence before collecting
held-out test trials. Frozen validation reports use only the frozen record IDs.
No default acceptance threshold is supplied. Approval requires explicit review and
at least 20 scored genuine and 20 scored impostor recording groups, three impostor
speakers and two probe sessions in each class, at least one genuine acceptance and
zero observed impostor acceptance. These are engineering eligibility floors, not
statistical security guarantees. All selected evidence must have current provenance.
Keep each approval dataset specific to one target; mixed target evidence cannot
approve a profile. Strict speaker-disjoint test cohorts need other consenting targets;
a single-person experiment must be labeled personal development only.

Reports include TA/TR/FA/FR, denominator-explicit FAR/FRR, uncertainty, acquisition
coverage, decisive coverage, genuine denial and an empirical threshold curve with
linear-interpolated EER. Undefined denominators produce null. Captured trials rejected
by the backend/quality path count as failures. Cancellations and failures before a
buffer exists are discarded, so coverage is explicitly scoped to retained consented
captured trials, not all attempts. Never claim measured population accuracy from these
engineering tests. A frozen test set must not guide later threshold selection.

Approved policies do not enable the global flag. `command` requires the explicit flag,
a selected approved policy, a fresh verification bound to the same buffer/audio ID,
and successful STT safety checks. Pending/synthetic policies, uncertain/rejected/error
results and cancellation block STT. Existing standalone STT commands remain diagnostic
and are not authenticated execution interfaces. No command execution exists.

## Manual procedure (user only)

Run from the repository with the existing venv. Replace symbolic UUID values below
with the opaque IDs returned by the CLI; do not commit those values or evaluation
outputs. The code does not load `.env` automatically.

```powershell
.\venv\Scripts\python.exe -m app.speaker.cli inspect-status
.\venv\Scripts\python.exe -m app.speaker.cli inspect-model
.\venv\Scripts\python.exe -m app.speaker.cli provision-model
.\venv\Scripts\python.exe -m app.speaker.cli smoke-backend
.\venv\Scripts\python.exe -m app.speaker.cli smoke-dpapi
.\venv\Scripts\python.exe -m app.speaker.cli enroll --interactive
.\venv\Scripts\python.exe -m app.speaker.cli profiles list --interactive
.\venv\Scripts\python.exe -m app.speaker.cli verify --interactive --profile PROFILE_UUID --diagnostics
.\venv\Scripts\python.exe -m app.speaker.cli profiles delete --interactive --profile PROFILE_UUID
.\venv\Scripts\python.exe -m app.speaker.cli calibration init --interactive
.\venv\Scripts\python.exe -m app.speaker.cli calibration record --interactive --profile PROFILE_UUID --speaker SPEAKER_UUID --session SESSION_UUID --group GROUP_UUID --split validation --language en --condition quiet
.\venv\Scripts\python.exe -m app.speaker.cli calibration freeze --interactive --acceptance CHOSEN_ACCEPTANCE --review CHOSEN_REVIEW
.\venv\Scripts\python.exe -m app.speaker.cli calibration evaluate --interactive --frozen FROZEN_UUID --split validation
.\venv\Scripts\python.exe -m app.speaker.cli calibration approve --interactive --frozen FROZEN_UUID --profile PROFILE_UUID
.\venv\Scripts\python.exe -m app.speaker.cli verify --interactive --profile PROFILE_UUID --policy APPROVED_POLICY_UUID
```

`provision-model` checks the existing artifact instead of downloading it again.
Without a reviewed policy, verification can display an explicitly requested similarity
but remains unavailable for authorization. Similarity is not probability/confidence.
Repeat enrollment with `--profile PROFILE_UUID` only to deliberately replace it; consent
is requested again. After freezing, collect disjoint test evidence with `--split test`
and evaluate using `calibration evaluate --split test`. Review cannot be automated.
Only after review may the user explicitly set
`$env:VOICEPILOT_SPEAKER_VERIFICATION_ENABLED='true'` and run
`command --interactive --profile PROFILE_UUID --policy APPROVED_POLICY_UUID` through
the same Python module. It interprets text without executing any action.

## Validation and research limits

Regression tests cover matching/missing/stale/mixed provenance, target/session/model/
template/hash mismatches, exact protected round trips, successful revocation and
failed/cancelled replacement preservation, safe errors, frozen rows and coverage.
The existing speaker suite covers consent, rollback, corruption, bounds, thresholds,
private paths, gateway freshness and same-buffer STT integration. Full project tests
use synthetic audio and fake integrations. Separate non-biometric platform smoke
checks validate the real approved model and Windows DPAPI without enrolling a person.

The research value is a reproducible integrity-bound enrollment/calibration protocol,
privacy-preserving collection, held-out evaluation and auditable fail-closed gating.
It is not evidence of Hindi/Marathi/accent robustness or replay/deepfake resistance.
Anti-spoofing remains unavailable. The next proposed activity is user-led, consented
manual enrollment/calibration and measured evaluation, requiring no execution feature.


## Phase 6B.1 compatibility note

The legacy research calibration workflow above remains unchanged. A separately enabled
personal owner-pilot protocol now uses the same schema-1 profile and DPAPI stack, with
fresh owner/non-owner/holdout evidence and prompted challenges. It does not migrate the
profile or turn its pending flag into approval. See [decision 0013](0013-owner-speaker-calibration-and-authenticated-voice-pilot.md)
for the new CLI, encrypted summaries, privacy, revocation and one-command execution boundary.
