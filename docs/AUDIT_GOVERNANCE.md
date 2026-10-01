# Audit governance

Every feature records one Audit Impact decision. Existing authoritative activity is the happy path; this process must not create duplicate telemetry.

## Classification

Choose exactly one:

- `REUSE_AUTHORITATIVE_ACTIVITY` — an existing durable record is trustworthy. State its source, timestamp, stable ID, and available actor/correlation. Add no duplicate event.
- `ADD_AUTHORITATIVE_EVIDENCE` — meaningful state would otherwise be overwritten or unreconstructable. Add durable evidence at the owning system, not a compensating central runtime event.
- `EXPLICIT_EVENT_OR_ERROR` — evidence exists only at runtime, such as a browser-only failure, unexpected service exception, hardware evidence, or Bridge transport failure. It must be structured, bounded, privacy-allowlisted, correlated where available, and non-blocking.
- `NO_AUDIT_IMPACT` — a visual-only, refactor-only, test-only, or documentation-only change. Give a short rationale.
- `DEFERRED_AUDIT_GAP` — needed durable evidence is safely out of scope. Record the missing evidence, risk, owner, required follow-up, and issue/task reference where available. It must not become permanent by omission.

## Trigger checklist

Audit Impact is required if any answer is yes: durable business state is created, changed, or deleted; booking lifecycle changes; money, payment, refund, reversal, void, or manual financial action changes; authentication, authorization, or privileged action changes; device assignment/configuration, locker operation, OTA/update, Partner/external API operation, async work, retry/idempotency/deduplication, customer-visible failure, runtime-only failure, sensitive-data handling, or audit/event/error infrastructure changes.

## Decision flow

```text
New feature -> Audit Impact review
  -> authoritative durable evidence exists? -> reuse it
  -> otherwise durable source evidence appropriate? -> add it at the owner
  -> otherwise -> explicit bounded, non-blocking event/error
```

Never add an audit event automatically merely because a feature is new. Reviewers decide whether the selected classification is correct; automation only proves the decision was recorded.

## Codex feature rule

Before implementing a feature, Codex includes `AUDIT_IMPACT` in its completion report: classification, source/evidence, events or errors added, and any deferred gap. Use known context and focused validation; do not repeat a broad architecture review for a small change.
