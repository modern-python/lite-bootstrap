"""Run one scenario of one suite in this process and report ops per second per round, or a cProfile.

A suite module `<suite>_suite.py` exposes SCENARIOS and `async def make(name) -> (op, cleanup)`.
`bench.py` runs this once per scenario; run it directly to profile one:

    python one.py --suite litestar --scenario full --ops 3000 --profile
"""

import argparse
import asyncio
import contextlib
import cProfile
import gc
import importlib
import io
import json
import logging
import pathlib
import pstats
import time

from common import Op


class _Sink(io.TextIOBase):
    def write(self, s: str) -> int:
        return len(s)


async def _profile(op: Op, ops: int, rows: int) -> str:
    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(ops):
        await op()
    profiler.disable()
    out = io.StringIO()
    pstats.Stats(profiler, stream=out).sort_stats("tottime").print_stats(rows)
    return out.getvalue()


async def _rounds(op: Op, ops: int, rounds: int) -> list[float]:
    results = []
    for _ in range(rounds):
        gc.collect()
        start = time.perf_counter()
        for _ in range(ops):
            await op()
        results.append(ops / (time.perf_counter() - start))
    return results


async def _main(args: argparse.Namespace) -> dict[str, object]:
    suite = importlib.import_module(f"{args.suite}_suite")
    op, cleanup = await suite.make(args.scenario)
    try:
        for _ in range(args.warmup):
            await op()
        if args.profile:
            return {"profile": await _profile(op, args.ops, args.rows)}
        return {"rps": await _rounds(op, args.ops, args.rounds)}
    finally:
        await cleanup()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--ops", type=int, default=4000)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--rows", type=int, default=40)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, stream=_Sink())
    logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)
    with contextlib.redirect_stdout(_Sink()):
        result = asyncio.run(_main(args))
    if "profile" in result:
        print(result["profile"])
        return
    payload = json.dumps({"suite": args.suite, "scenario": args.scenario, **result})
    if args.out:
        args.out.write_text(payload)
    else:
        print(payload)


if __name__ == "__main__":
    main()
