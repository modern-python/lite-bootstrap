"""cProfile one scenario's request loop.

The absolute numbers are inflated (the profiler roughly triples per-request cost); the call
counts and the relative ordering are what this is for. `ncalls` divided by the request count is
often the finding on its own.

    python profile_one.py sentry errors_only
    python profile_one.py stack otel --sort cumtime
"""

import argparse
import asyncio
import contextlib
import cProfile
import io
import logging
import pstats

import driver
from inprocess import load_suite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=["sentry", "stack"])
    parser.add_argument("scenario")
    parser.add_argument("--app", default="async")
    parser.add_argument("--requests", type=int, default=3000)
    parser.add_argument("--sort", default="tottime")
    parser.add_argument("--rows", type=int, default=30)
    parser.add_argument("--callers", help="regex; print what calls the matching functions instead")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, stream=io.StringIO())
    logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)

    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        app = load_suite(args.suite).build(args.scenario, args.app)
        driver.measure(app, 500, 1, 200)

        async def body() -> None:
            for _ in range(args.requests):
                await driver.one_request(app)

        profiler = cProfile.Profile()
        profiler.enable()
        asyncio.run(body())
        profiler.disable()

    stats = pstats.Stats(profiler).sort_stats(args.sort)
    print(f"{args.suite}/{args.scenario} app={args.app} requests={args.requests}\n")
    if args.callers:
        stats.print_callers(args.callers)
    else:
        stats.print_stats(args.rows)


if __name__ == "__main__":
    main()
