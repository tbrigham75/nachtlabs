"""Safe server diagnostics: do not format exception strings or tracebacks with request material."""

import json
import logging


class ServerFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "service": "api-server",
                "logger": record.name,
                "level": record.levelname,
                "event": "server_diagnostic",
                "exception_type": record.exc_info[0].__name__
                if record.exc_info and record.exc_info[0]
                else None,
            }
        )
