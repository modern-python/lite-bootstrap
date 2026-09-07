"""Run a set of in-process scenarios, one subprocess each, and print the comparison table.

    python run.py sentry async off,errors_only,errors_only_no_txn
    python run.py stack async bare,otel,prom,sentry,full,full_all_tuned

The first scenario in the list is the baseline the rest are compared against.
"""

import argparse
import json
import pathlib
import statistics
import subprocess
import sys
import tempfile
import time

from inprocess import load_suite


HERE = pathlib.Path(__file__).resolve().parent
STUB_OTLP_PORT = "8139"


def bench(suite: str, scenario: str, app: str, requests: int, rounds: int) -> list[float]:
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "result.json"
        subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(HERE / "inprocess.py"),
                "--suite",
                suite,
                "--scenario",
                scenario,
                "--app",
                app,
                "--requests",
                str(requests),
                "--rounds",
                str(rounds),
                "--out",
                str(out),
            ],
            check=True,
            cwd=HERE,
            stdout=subprocess.DEVNULL,
        )
        return json.loads(out.read_text())["rps"]


def report(suite: str, app: str, requests: int, rounds: int, scenarios: list[str]) -> None:
    print(f"{suite} suite  app={app} requests={requests} rounds={rounds}\n")
    print(f"{'scenario':<38} {'rps(med)':>10} {'us/req':>9} {'vs base':>8} {'+us':>8}")
    baseline = None
    for scenario in scenarios:
        median = statistics.median(bench(suite, scenario, app, requests, rounds))
        micros = 1e6 / median
        if baseline is None:
            baseline = micros
        print(f"{scenario:<38} {median:>10.0f} {micros:>9.1f} {baseline / micros:>7.2f}x {micros - baseline:>+8.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=["sentry", "stack"])
    parser.add_argument("app", nargs="?", default="async")
    parser.add_argument("scenarios", nargs="?", help="comma-separated; the first one is the baseline")
    parser.add_argument("--list", action="store_true", help="print this suite's scenario names and exit")
    parser.add_argument("--requests", type=int, default=4000)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()

    suite = load_suite(args.suite)
    if args.list:
        print("\n".join(sorted(suite.SCENARIOS)))
        return
    if not args.scenarios:
        parser.error("give a comma-separated scenario list, or --list to see the names")

    scenarios = args.scenarios.split(",")
    unknown = sorted(set(scenarios) - set(suite.SCENARIOS))
    if unknown:
        parser.error(f"unknown {args.suite} scenarios: {', '.join(unknown)}")

    stub = None
    if args.suite == "stack":
        stub = subprocess.Popen(  # noqa: S603
            [sys.executable, str(HERE / "stub_otlp.py"), STUB_OTLP_PORT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.0)
    try:
        report(args.suite, args.app, args.requests, args.rounds, scenarios)
    finally:
        if stub is not None:
            stub.terminate()
            stub.wait(timeout=10)


if __name__ == "__main__":
    main()
