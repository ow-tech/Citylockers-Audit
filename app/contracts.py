"""Canonical, source-agnostic contracts for central audit records."""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SystemCode = Literal["CL", "KH", "PA", "BR", "KS", "AU"]
SourceKind = Literal["business_activity", "operational_event", "explicit_error", "explicit_event"]
ADAPTER_SOURCE_KINDS = frozenset({"business_activity", "operational_event"})
EXPLICIT_RUNTIME_SOURCE_KINDS = frozenset({"explicit_error", "explicit_event"})
_ADAPTER_EVENT_NAMESPACE = UUID("56563ff2-c55e-52e6-9ed6-da808ed636c3")
PROHIBITED_METADATA_KEYS = frozenset({
    "authorization", "authorization_header", "cookie", "cookies", "password", "passwd",
    "otp", "verification_code", "access_code", "locker_access_code", "jwt", "access_token",
    "refresh_token", "api_key", "service_role_key", "pan", "card_number", "cvv", "cvc",
    "merchant_secure_key", "merchant_key", "provider_evidence", "raw_request", "raw_response",
})


def normalized_metadata_key(value: object) -> str:
    """Normalize spelling variants without applying unsafe substring matching."""
    return str(value).strip().casefold().replace("-", "_").replace(" ", "_")


def prohibited_metadata_path(value: object, path: str = "metadata") -> str | None:
    """Return a key path for a prohibited field without retaining its value."""
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            nested_path = f"{path}.{key_text}"
            if normalized_metadata_key(key) in PROHIBITED_METADATA_KEYS:
                return nested_path
            found = prohibited_metadata_path(nested, nested_path)
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = prohibited_metadata_path(nested, f"{path}[{index}]")
            if found:
                return found
    return None


def deterministic_adapter_event_id(source_system: SystemCode, source_stream: str, source_record_id: str, source_transition: str | None = None) -> str:
    """Return a stable identifier for one authoritative source activity."""
    return str(uuid5(_ADAPTER_EVENT_NAMESPACE, "\x1f".join((source_system, source_stream, source_record_id, source_transition or ""))))


class SafeContext(BaseModel):
    """The complete, bounded metadata vocabulary accepted from producers."""

    model_config = ConfigDict(extra="forbid")
    error_code: str | None = Field(default=None, min_length=1, max_length=100)
    reference: str | None = Field(default=None, min_length=1, max_length=100)
    fingerprint: str | None = Field(default=None, min_length=1, max_length=200)
    endpoint: str | None = Field(default=None, min_length=1, max_length=300)
    http_status: int | None = Field(default=None, ge=100, le=599)
    reason: str | None = Field(default=None, min_length=1, max_length=1000)
    partner_id: str | None = Field(default=None, min_length=1, max_length=300)
    booking_id: str | None = Field(default=None, min_length=1, max_length=300)
    booking_reference: str | None = Field(default=None, min_length=1, max_length=300)
    transaction_id: str | None = Field(default=None, min_length=1, max_length=300)
    payment_attempt_id: str | None = Field(default=None, min_length=1, max_length=300)
    device_id: str | None = Field(default=None, min_length=1, max_length=300)
    wall_id: str | None = Field(default=None, min_length=1, max_length=300)
    locker_id: str | None = Field(default=None, min_length=1, max_length=300)
    terminal_id: str | None = Field(default=None, min_length=1, max_length=300)
    partner_request_id: str | None = Field(default=None, min_length=1, max_length=300)
    result: str | None = Field(default=None, min_length=1, max_length=100)
    summary: str | None = Field(default=None, min_length=1, max_length=1000)
    service: str | None = Field(default=None, min_length=1, max_length=100)
    surface: str | None = Field(default=None, min_length=1, max_length=100)
    route: str | None = Field(default=None, min_length=1, max_length=300)
    app_version: str | None = Field(default=None, min_length=1, max_length=100)
    exception_type: str | None = Field(default=None, min_length=1, max_length=100)
    payment_status: str | None = Field(default=None, min_length=1, max_length=100)
    source_surface: Literal["citylockers_site"] | None = None

    @field_validator("*")
    @classmethod
    def reject_blank_context_strings(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="before")
    @classmethod
    def reject_prohibited_context(cls, value: object) -> object:
        if prohibited_metadata_path(value):
            # Never include the rejected key path or value in a client response or logs.
            raise ValueError("metadata contains a prohibited field")
        return value


class ErrorOccurrence(SafeContext):
    """Required context for an ``explicit_error`` AuditEvent.

    ``reference`` is the per-occurrence support reference exposed to operators;
    it is deliberately distinct from the stable canonical ``error_code``.
    """

    error_code: str = Field(min_length=1, max_length=100)
    reference: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_code_and_reference(self) -> "ErrorOccurrence":
        if self.error_code == self.reference:
            raise ValueError("error code and support reference must differ")
        return self


class ErrorOccurrenceEvent(BaseModel):
    """Versioned producer contract for one explicit error occurrence.

    The API continues to accept the broader ``AuditEvent`` union.  Producers use
    this constrained form so their generated schema cannot accidentally describe
    an authoritative-source event or omit occurrence identity.
    """

    model_config = ConfigDict(extra="forbid")
    event_id: UUID | None = None
    system_code: SystemCode
    event_type: str = Field(min_length=1, max_length=200)
    occurred_at: datetime
    trace_id: UUID | None = None
    operation_id: UUID | None = None
    request_id: UUID | None = None
    metadata: ErrorOccurrence
    source_kind: Literal["explicit_error"] = "explicit_error"

    def as_audit_event(self) -> "AuditEvent":
        return AuditEvent.model_validate(self.model_dump(mode="json", exclude_none=True))


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str | None = None
    system_code: SystemCode
    event_type: str = Field(min_length=1, max_length=200)
    occurred_at: datetime
    trace_id: str | None = None
    operation_id: str | None = None
    request_id: str | None = None
    metadata: SafeContext = Field(default_factory=SafeContext)
    source_kind: SourceKind = "explicit_event"
    source_system: SystemCode | None = None
    source_stream: str | None = Field(default=None, max_length=200)
    source_record_id: str | None = Field(default=None, max_length=300)
    source_transition: str | None = Field(default=None, max_length=100)
    source_occurred_at: datetime | None = None

    @field_validator("event_id", "trace_id", "operation_id", "request_id", "source_stream", "source_record_id", "source_transition")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def normalize_identity(self) -> "AuditEvent":
        source_identity_values = (
            self.source_system,
            self.source_stream,
            self.source_record_id,
            self.source_transition,
            self.source_occurred_at,
        )
        if self.source_kind in ADAPTER_SOURCE_KINDS:
            if not all(source_identity_values):
                raise ValueError("authoritative source events require system, stream, record ID, transition, and occurred-at")
            generated = deterministic_adapter_event_id(self.source_system, self.source_stream, self.source_record_id, self.source_transition)
            if self.event_id is None:
                self.event_id = generated
        elif any(value is not None for value in source_identity_values):
            raise ValueError("explicit events must not declare an authoritative source identity")
        if self.source_kind == "explicit_error":
            ErrorOccurrence.model_validate(self.metadata.model_dump(exclude_none=True))
            ErrorOccurrenceEvent.model_validate(self.model_dump(exclude_none=True))
        if self.event_id is None:
            self.event_id = str(uuid4())
        return self

    @property
    def source_identity(self) -> tuple[str, str, str, str | None] | None:
        if self.source_kind not in ADAPTER_SOURCE_KINDS:
            return None
        return (self.source_system, self.source_stream, self.source_record_id, self.source_transition)


class SourceCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_name: str = Field(min_length=1, max_length=200)
    cursor_value: str | None = None
    cursor_type: str | None = Field(default=None, max_length=100)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)
