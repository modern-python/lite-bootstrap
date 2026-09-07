"""Serve one scenario under uvicorn so it can be loaded over real sockets.

Paired with `run_http.py`, which starts this and points `ab` at it.
"""

import argparse
import logging

import uvicorn
from inprocess import load_suite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["sentry", "stack"])
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--app", default="async")
    parser.add_argument("--port", type=int, default=8137)
    args = parser.parse_args()

    app = load_suite(args.suite).build(args.scenario, args.app)
    logging.getLogger().setLevel(logging.CRITICAL)

    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="error")


if __name__ == "__main__":
    main()
