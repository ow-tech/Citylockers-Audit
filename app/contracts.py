"""Shared audit contract placeholders.

Event and error catalogues remain intentionally small until source-specific
recon establishes authoritative transition semantics.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


SystemCode = Literal["CL", "KH", "PA", "BR", "KS", "AU"]


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    system_code: SystemCode
    event_type: str
    occurred_at: datetime
