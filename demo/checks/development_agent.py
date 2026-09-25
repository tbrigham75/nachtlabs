"""Synthetic agent process for isolated harness acceptance, not a coding model."""
import json
from pathlib import Path
import sys

request = json.loads(sys.stdin.buffer.read(65537))
if request.get("fixture") != "greeting" or request.get("operation") not in {"implement", "verify"}:
    raise SystemExit("Only the synthetic greeting fixture is supported")
if request["operation"] == "implement":
    root = Path("/work/docs")
    root.mkdir(exist_ok=True)
    (root / "greeting.md").write_text("Hello from NachtLabs.\n")
    print(json.dumps({"type": "text", "synthetic": True, "message": "Fixture written; verification still required"}))
else:
    passed = (Path("/work/docs/greeting.md").read_text() == "Hello from NachtLabs.\n")
    print(json.dumps({"synthetic": True, "verdict": "pass" if passed else "failed",
                      "candidate": request["candidate"], "criteria": {"1": passed},
                      "summary": "Synthetic fixture observation", "concerns": [], "confidence": 1.0}))
