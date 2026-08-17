from __future__ import annotations

import argparse
import json

import httpx


def run(url: str) -> dict[str, object]:
    with httpx.Client(base_url=url, timeout=10, verify=False) as client:
        unauth = client.get("/api/schedules")
        oversized = client.post("/api/chat/stream", content=b"x" * 1_100_000, headers={"content-type": "application/json"})
        traversal = client.get("/../../.env")
    checks = {"unauthenticated_rejected": unauth.status_code == 401, "oversized_rejected": oversized.status_code == 413, "traversal_not_exposed": traversal.status_code in {400, 404}}
    return {"checks": checks, "passed": all(checks.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://planning.local")
    args = parser.parse_args()
    print(json.dumps(run(args.url), indent=2))
