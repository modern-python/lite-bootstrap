"""Real-server runs: one Granian (or uvicorn) worker per scenario, loaded with `ab -k`.

    python run_http.py litestar bare,otel,sentry --server granian

Needs `ab` (Apache Bench) on PATH, and granian in the interpreter's environment for `--server granian`.
The suite must expose `build(name) -> (app, scenario)`; `serve_target.py` is the module the server loads.
"""

import argparse
import importlib
import os
import pathlib
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

from common import HERE, OTLP_PORT, STUB_OTLP


BIN = pathlib.Path(sys.executable).parent
PORT = 8147
HTTP_OK = 200
WARMUP_REQUESTS = 3000
RPS_RE = re.compile(r"Requests per second:\s+([0-9.]+)")
NON_2XX_RE = re.compile(r"Non-2xx responses:\s+(\d+)")


def wait_ready(path: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=1) as response:
                if response.status == HTTP_OK:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.2)
    msg = "server not ready"
    raise RuntimeError(msg)


def ab(path: str, requests: int, concurrency: int) -> float:
    out = subprocess.run(  # noqa: S603
        ["ab", "-k", "-q", "-n", str(requests), "-c", str(concurrency), f"http://127.0.0.1:{PORT}{path}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    if (bad := NON_2XX_RE.search(out)) is not None:
        msg = f"{bad.group(1)} non-2xx responses"
        raise RuntimeError(msg)
    if (rps := RPS_RE.search(out)) is None:
        msg = f"no RPS in ab output:\n{out}"
        raise RuntimeError(msg)
    return float(rps.group(1))


def server_cmd(server: str) -> list[str]:
    if server == "granian":
        return [
            str(BIN / "granian"),
            "--interface",
            "asgi",
            "--workers",
            "1",
            "--runtime-threads",
            "1",
            "--no-access-log",
            "--log-level",
            "error",
            "--port",
            str(PORT),
            "serve_target:app",
        ]
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "--port",
        str(PORT),
        "--no-access-log",
        "--log-level",
        "error",
        "serve_target:app",
    ]


def bench(suite: str, scenario: str, args: argparse.Namespace) -> list[float]:
    env = {**os.environ, "BENCH_SUITE": suite, "BENCH_SCENARIO": scenario}
    path = importlib.import_module(f"{suite}_suite").SCENARIOS[scenario].path
    server = subprocess.Popen(  # noqa: S603
        server_cmd(args.server), cwd=HERE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        wait_ready(path)
        ab(path, WARMUP_REQUESTS, args.concurrency)
        return [ab(path, args.requests, args.concurrency) for _ in range(args.rounds)]
    finally:
        server.terminate()
        server.wait(timeout=15)
        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite")
    parser.add_argument("scenarios")
    parser.add_argument("--server", default="granian", choices=["granian", "uvicorn"])
    parser.add_argument("--requests", type=int, default=20000)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    scenarios = args.scenarios.split(",")

    stub = subprocess.Popen(  # noqa: S603
        [sys.executable, str(STUB_OTLP), str(OTLP_PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(0.8)
    results: dict[str, list[float]] = {name: [] for name in scenarios}
    spread: dict[str, float] = dict.fromkeys(scenarios, 0.0)
    try:
        for _ in range(args.repeat):
            for name in scenarios:
                rps = bench(args.suite, name, args)
                median = statistics.median(rps)
                results[name].append(median)
                spread[name] = max(spread[name], (max(rps) - min(rps)) / median * 100)
    finally:
        stub.terminate()
        stub.wait(timeout=10)

    print(
        f"{args.server} 1 worker, ab -k -n {args.requests} -c {args.concurrency}, "
        f"rounds={args.rounds} repeat={args.repeat}"
    )
    print(f"{'scenario':<28} {'rps':>8} {'us/req':>8} {'+us':>8} {'spread%':>8}  per-repeat rps")
    base_us = 1e6 / statistics.median(results[scenarios[0]])
    for name in scenarios:
        rps = statistics.median(results[name])
        micros = 1e6 / rps
        per_repeat = " ".join(f"{value:.0f}" for value in results[name])
        print(f"{name:<28} {rps:>8.0f} {micros:>8.1f} {micros - base_us:>+8.1f} {spread[name]:>8.1f}  {per_repeat}")


if __name__ == "__main__":
    main()
