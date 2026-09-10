# 0004: Domain command resolution foundation

Phase: 3B only. The decision number is sequential, not Phase 4.
Status: accepted for a non-executing local text subsystem.

Build app/commands independently of audio capture and Whisper loading. It accepts
explicit text or an existing successful STT result's raw_transcript property.
Preserve raw, matching-normalized, and canonical proposal values separately.
No execution adapter, operating-system action, Spotify integration, history
database, LLM, speaker verification or frontend is introduced.

Use the standard library and existing Pydantic. Version schema, entity aliases,
intent patterns and the 80-row synthetic development/test seed as separate files.
Define vocabulary and grammar before the seed; never use seed rows for runtime
matching or create an alias per sentence. Cover twelve interpretation labels and
four illustrative language categories. Include hard negatives and paraphrases
outside the supported grammar; seed perfection is not a target.

Prefer full-command patterns and exact vocabulary. Limit fuzzy matching to entity
suggestions requiring confirmation. Preserve observed-error provenance, especially
Tharism Infer -> Taare Zameen Par; never call it a genuine pronunciation.
Ambiguity, negation, compounds, unknown/incomplete entities and low heuristic
scores cannot silently become accepted proposals. Heuristic scores are not
probabilities, calibrated confidence, ASR confidence or execution authorization.

Use typed data contracts and a matching exported JSON Schema. Reject duplicate
IDs, unsupported schema versions, inconsistent intent/entity/command labels and
invented recording metadata on synthetic rows. Future consented-recording
metadata requires a speaker pseudonym and consent reference; no audio is collected.

Evaluation reports exact metric counts, denominators and percentages, coverage
and explicitly defined false-accept rates. It is a local development sanity check,
not held-out research evidence. Distinguish interpretation metrics from ASR
accuracy. Do not tune repeatedly for perfect seed scores or fabricate results.

Automated tests block model/hardware imports, socket connections and system-action
entry points. Tests inspect only project data or temporary files. Import smoke
checks verify the text subsystem loads without audio/model backends. Existing
STT code remains unchanged. Publication, new collection, model integration and
all later phases require separate approval.
