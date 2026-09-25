"""Operator-run generation; never executed during Windows authoring."""
import json
from pathlib import Path

from nachtlabs_api.main import create_app

if __name__ == "__main__":
    target = Path("docs/api/openapi.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")
