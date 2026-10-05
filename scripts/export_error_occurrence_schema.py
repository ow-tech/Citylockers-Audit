"""Write the checked-in, versioned JSON Schema for explicit error producers."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contracts import ErrorOccurrenceEvent


target = Path(__file__).resolve().parents[1] / "contracts" / "error-occurrence-event.v1.schema.json"
target.write_text(json.dumps(ErrorOccurrenceEvent.model_json_schema(), indent=2) + "\n")
