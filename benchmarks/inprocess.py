"""Run one scenario in this process and write its requests-per-second rounds to a file.

One process per scenario is not tidiness: `sentry_sdk.init()` monkeypatches Starlette and the
stdlib logging module, `set_tracer_provider` is set-once, and the Prometheus registry is
global. Nothing here can be undone between scenarios.
"""

import argparse
import contextlib
import importlib
import io
import json
import logging
import pathlib
import types

import driver


class _Sink(io.TextIOBase):
    """Swallow the app's own stdout (structlog writes there) without buffering it."""

    def write(self, s: str) -> int:
        return len(s)


def load_suite(name: str) -> types.ModuleType:
    return importlib.import_module(f"{name}_scenarios")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["sentry", "stack"])
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--app", default="async")
    parser.add_argument("--requests", type=int, default=5000)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, stream=_Sink())
    logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)

    suite = load_suite(args.suite)
    with contextlib.redirect_stdout(_Sink()):
        app = suite.build(args.scenario, args.app)
        rps = driver.measure(app, args.requests, args.rounds, args.warmup)

    args.out.write_text(json.dumps({"suite": args.suite, "scenario": args.scenario, "app": args.app, "rps": rps}))


if __name__ == "__main__":
    main()
