"""Terminal result payload returned to callers on /poll success.

The legacy ``TTSBatchService`` already returns dict payloads for each action
(``create_batch`` / ``check_status`` / ``process_batch``). We simply pass them
through, tagged with the originating ``action`` so downstream consumers can
route on a single field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class JobResult:
    action: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, **self.payload}
