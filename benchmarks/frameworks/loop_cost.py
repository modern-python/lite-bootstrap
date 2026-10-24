"""Cost of one event-loop iteration and of asyncio.gather on one coroutine, both bound by the selector.

Compare the output on macOS (KqueueSelector) and Linux (EpollSelector) before trusting a macOS run.
"""

import asyncio
import selectors
import time
import typing


CALLS = 20000


async def one() -> bool:
    return True


async def direct() -> None:
    await one()


async def sleep0() -> None:
    await asyncio.sleep(0)


async def gather() -> None:
    await asyncio.gather(one())


async def timed(label: str, fn: typing.Callable[[], typing.Awaitable[None]]) -> None:
    start = time.perf_counter()
    for _ in range(CALLS):
        await fn()
    print(f"{label:30} {(time.perf_counter() - start) / CALLS * 1e6:.2f} us")


async def main() -> None:
    await timed("await coroutine", direct)
    await timed("sleep(0)", sleep0)
    await timed("gather(one)", gather)


def select_cost() -> None:
    selector = selectors.DefaultSelector()
    start = time.perf_counter()
    for _ in range(CALLS):
        selector.select(0)
    print(f"{type(selector).__name__ + '.select(0)':30} {(time.perf_counter() - start) / CALLS * 1e6:.2f} us")


if __name__ == "__main__":
    asyncio.run(main())
    select_cost()
