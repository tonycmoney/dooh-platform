"""Push agent.json + prompt.md to the ElevenLabs receptionist agent.

Usage:
    ELEVENLABS_API_KEY=... python receptionist/sync_agent.py

Edit prompt.md (pricing, launch cities, rules), then run this to update the
live agent. Standard library only.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
API = "https://api.elevenlabs.io/v1/convai/agents/{agent_id}"


def main() -> int:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        print("Set ELEVENLABS_API_KEY first.", file=sys.stderr)
        return 1

    cfg = json.loads((HERE / "agent.json").read_text())
    prompt = (HERE / cfg["prompt_file"]).read_text()

    body = {
        "name": cfg["name"],
        "conversation_config": {
            "agent": {
                "first_message": cfg["first_message"],
                "language": cfg["language"],
                "prompt": {"prompt": prompt},
            }
        },
    }

    req = urllib.request.Request(
        API.format(agent_id=cfg["agent_id"]),
        data=json.dumps(body).encode(),
        method="PATCH",
        headers={"xi-api-key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        print(f"Updated {cfg['agent_id']} (HTTP {resp.status})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
