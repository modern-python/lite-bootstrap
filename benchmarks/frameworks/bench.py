"""Run scenarios of a suite in process, one subprocess each, and print median µs/op and the delta to the first.

    python bench.py litestar bare,otel,prom
    python bench.py litestar bare,otel --ops 4000 --rounds 5 --repeat 2

`--repeat` runs the whole list that many times, interleaved, and reports the median of the repeat medians.
"""

import argparse
import json
import pathlib
import statistics
import subprocess
import sys
import tempfile
import time

from common import HERE, OTLP_PORT, STUB_OTLP


def bench(suite: str, scenario: str, args: argparse.Namespace) -> list[float]:
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "result.json"
        subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(HERE / "one.py"),
                "--suite",
                suite,
                "--scenario",
                scenario,
                "--ops",
                str(args.ops),
                "--rounds",
                str(args.rounds),
                "--warmup",
                str(args.warmup),
                "--out",
                str(out),
            ],
            check=True,
            cwd=HERE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return json.loads(out.read_text())["rps"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite")
    parser.add_argument("scenarios")
    parser.add_argument("--ops", type=int, default=4000)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    scenarios = args.scenarios.split(",")

    stub = subprocess.Popen(  # noqa: S603
        [sys.executable, str(STUB_OTLP), str(OTLP_PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(0.8)
    results: dict[str, list[float]] = {name: [] for name in scenarios}
    spreads: dict[str, list[float]] = {name: [] for name in scenarios}
    try:
        for _ in range(args.repeat):
            for name in scenarios:
                micros = [1e6 / rps for rps in bench(args.suite, name, args)]
                median = statistics.median(micros)
                results[name].append(median)
                spreads[name].append((max(micros) - min(micros)) / median * 100)
    finally:
        stub.terminate()
        stub.wait(timeout=10)

    print(f"suite={args.suite} ops={args.ops} rounds={args.rounds} repeat={args.repeat}")
    print(f"{'scenario':<34} {'us/op':>9} {'+us':>8} {'min':>8} {'+us min':>8} {'spread%':>8}  per-repeat medians")
    base = statistics.median(results[scenarios[0]])
    base_min = min(results[scenarios[0]])
    for name in scenarios:
        median = statistics.median(results[name])
        low = min(results[name])
        per_repeat = " ".join(f"{value:.1f}" for value in results[name])
        print(
            f"{name:<34} {median:>9.2f} {median - base:>+8.2f} {low:>8.2f} {low - base_min:>+8.2f} "
            f"{max(spreads[name]):>8.1f}  {per_repeat}"
        )


if __name__ == "__main__":
    main()
