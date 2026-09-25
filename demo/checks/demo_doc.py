"""Synthetic documentation Journey; installed read-only outside the target repository."""
from pathlib import Path

path = Path("/work/docs/greeting.md")
assert path.is_file(), "Expected documentation file missing"
assert path.read_text(encoding="utf-8").strip() == "Hello from NachtLabs.", "Unexpected documentation content"
