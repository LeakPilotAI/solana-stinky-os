"""Print bounded live entity-readiness cohort coverage as JSON.

This operator command intentionally uses only the Python standard library. It asks
the already-running Genesis API to execute the read-only measurement inside the
managed API runtime, so host Python does not need FastAPI/SQLAlchemy/asyncpg.
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

DEFAULT_API_URL = "http://127.0.0.1:8010"


def _args():
    parser = argparse.ArgumentParser(description="Measure captured entity-readiness replay coverage")
    parser.add_argument("--entity-limit", type=int, default=100)
    parser.add_argument("--snapshot-limit", type=int, default=100)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--include-entities", action="store_true")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    return parser.parse_args()


def _url(args) -> str:
    params = {
        "entity_limit": max(1, min(500, int(args.entity_limit))),
        "snapshot_limit": max(2, min(200, int(args.snapshot_limit))),
        "include_entities": "true" if args.include_entities else "false",
    }
    if args.as_of:
        params["as_of"] = args.as_of
    base = str(args.api_url or DEFAULT_API_URL).rstrip("/")
    return f"{base}/v1/entity-graph/live-readiness-cohort?{urlencode(params)}"


def main() -> int:
    args = _args()
    target = _url(args)
    try:
        with urlopen(target, timeout=30) as response:
            raw = response.read().decode("utf-8")
            result = json.loads(raw)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"Genesis API returned HTTP {exc.code}: {body}", file=sys.stderr)
        return 3
    except URLError as exc:
        print(
            "Could not reach the running Genesis API at "
            f"{args.api_url}. Start Genesis (or restart it after pulling this fix) and retry. "
            f"Details: {exc.reason}",
            file=sys.stderr,
        )
        return 4
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"Genesis API returned an invalid JSON response: {exc}", file=sys.stderr)
        return 5

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 2 if result.get("status") == "TEMPORAL_VIOLATION" else 0


if __name__ == "__main__":
    raise SystemExit(main())
