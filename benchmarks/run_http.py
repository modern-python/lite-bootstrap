"""Same comparison as `run.py`, but over real sockets: uvicorn plus `ab -k`.

    python run_http.py sentry async off,errors_only,traces_1
    python run_http.py stack async bare,full,full_all_tuned

Needs `ab` (Apache Bench) on PATH. Check the load generator is not the ceiling before
trusting a run: raise `--concurrency` on the baseline scenario until the number stops moving.
"""

import argparse
import pathlib
import re
import statistics
import subprocess
import sys
import time
import typing
import urllib.error
import urllib.request

from inprocess import load_suite


HERE = pathlib.Path(__file__).resolve().parent
PORT = 8137
STUB_OTLP_PORT = "8139"
RPS_RE = re.compile(r"Requests per second:\s+([0-9.]+)")
WARMUP_REQUESTS = 2000
HTTP_OK = 200


class Load(typing.NamedTuple):
    requests: int
    concurrency: int
    rounds: int


def _probe(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1) as response:
            return response.status == HTTP_OK
    except (urllib.error.URLError, OSError):
        return False


def wait_ready(port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _probe(port):
            return
        time.sleep(0.1)
    msg = f"server on port {port} did not become ready"
    raise RuntimeError(msg)


def ab(port: int, requests: int, concurrency: int) -> float:
    result = subprocess.run(  # noqa: S603
        ["ab", "-k", "-q", "-n", str(requests), "-c", str(concurrency), f"http://127.0.0.1:{port}/ping"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    match = RPS_RE.search(result.stdout)
    if match is None:
        msg = f"could not parse ab output:\n{result.stdout}{result.stderr}"
        raise RuntimeError(msg)
    return float(match.group(1))


def bench(suite: str, scenario: str, app: str, load: Load) -> list[float]:
    server = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            str(HERE / "serve.py"),
            "--suite",
            suite,
            "--scenario",
            scenario,
            "--app",
            app,
            "--port",
            str(PORT),
        ],
        cwd=HERE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_ready(PORT)
        ab(PORT, WARMUP_REQUESTS, load.concurrency)
        return [ab(PORT, load.requests, load.concurrency) for _ in range(load.rounds)]
    finally:
        server.terminate()
        server.wait(timeout=10)
        time.sleep(0.5)


def report(suite: str, app: str, load: Load, scenarios: list[str]) -> None:
    print(f"uvicorn + ab -k  {suite} suite  app={app} n={load.requests} c={load.concurrency} rounds={load.rounds}\n")
    print(f"{'scenario':<38} {'rps(med)':>10} {'us/req':>9} {'vs base':>8} {'+us':>8}")
    baseline = None
    for scenario in scenarios:
        median = statistics.median(bench(suite, scenario, app, load))
        micros = 1e6 / median
        if baseline is None:
            baseline = micros
        print(f"{scenario:<38} {median:>10.0f} {micros:>9.1f} {baseline / micros:>7.2f}x {micros - baseline:>+8.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=["sentry", "stack"])
    parser.add_argument("app")
    parser.add_argument("scenarios", help="comma-separated; the first one is the baseline")
    parser.add_argument("--requests", type=int, default=20000)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()

    scenarios = args.scenarios.split(",")
    unknown = sorted(set(scenarios) - set(load_suite(args.suite).SCENARIOS))
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
        report(args.suite, args.app, Load(args.requests, args.concurrency, args.rounds), scenarios)
    finally:
        if stub is not None:
            stub.terminate()
            stub.wait(timeout=10)


if __name__ == "__main__":
    main()
