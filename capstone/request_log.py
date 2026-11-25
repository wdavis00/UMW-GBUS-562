"""The capstone's run log: one line of JSON for each request the tool handles.

Each line has exactly seven fields: timestamp, model, input, output, input_tokens, output_tokens,
and seconds. Tokens and seconds are totals across every Claude call made for the request, and time
spent outside those calls is not counted. `input` and `output` are recorded as given and never
interpreted.

The log is evidence. It is written only by the tool, only by appending, and never by hand. Tests
must point LOG_FILE somewhere else.
"""

import json
import os
from datetime import datetime
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent / "runs" / "log.jsonl"
PRODUCTION_LOG = LOG_FILE  # stays fixed when a test changes LOG_FILE


class RequestRecord:
    """Totals one handled request and appends its line."""

    def __init__(self, model: str, request_input: str):
        self.timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.model = model
        self.input = request_input
        self.calls = self.input_tokens = self.output_tokens = 0
        self.seconds = 0.0

    def add_call(self) -> None:
        """Count a Claude call that is about to be made."""
        self.calls += 1

    def add_seconds(self, seconds: float) -> None:
        """Add the elapsed time of one Claude call, whether or not it succeeded."""
        self.seconds += seconds

    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def append(self, output: str) -> None:
        """Append the request's line. Raises OSError if it cannot be written."""
        line = json.dumps({
            "timestamp": self.timestamp,
            "model": self.model,
            "input": self.input,
            "output": output,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "seconds": round(self.seconds, 2),
        })
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
            file.flush()
            os.fsync(file.fileno())
