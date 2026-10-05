import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts import AuditEvent, ErrorOccurrenceEvent


FIXTURES = Path(__file__).parent / "fixtures"


def test_checked_in_error_occurrence_schema_is_generated_from_central_contract() -> None:
    schema = json.loads((Path(__file__).parents[1] / "contracts" / "error-occurrence-event.v1.schema.json").read_text())
    assert schema == ErrorOccurrenceEvent.model_json_schema()


@pytest.mark.parametrize("fixture", ["explicit_cl_client_error.json", "explicit_pa_error.json", "explicit_br_runtime_error.json"])
def test_explicit_error_fixtures_are_accepted_as_occurrences(fixture: str) -> None:
    payload = json.loads((FIXTURES / fixture).read_text())
    occurrence = ErrorOccurrenceEvent.model_validate(payload)
    assert occurrence.as_audit_event() == AuditEvent.model_validate(payload)


def test_error_occurrence_requires_distinct_definition_and_occurrence_identity() -> None:
    payload = json.loads((FIXTURES / "explicit_pa_error.json").read_text())
    payload["metadata"]["reference"] = payload["metadata"]["error_code"]
    with pytest.raises(ValidationError):
        ErrorOccurrenceEvent.model_validate(payload)
