import json
import logging
from datetime import UTC, datetime

from apps.core.correlation import current_correlation_id


class JsonFormatter(logging.Formatter):
    """Format de log sobre et exploitable, sans ajouter les données de requête."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": current_correlation_id() or None,
        }
        if hasattr(record, "event"):
            payload["event"] = record.event
        return json.dumps(payload, ensure_ascii=False, default=str)
