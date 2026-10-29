"""Per-operation costs of the pieces sentry-sdk runs on every request.

Attributes the per-request total from `run.py` to individual calls, which is what makes the
upstream issues actionable: `Transaction(...)` and the Mersenne Twister seed inside it are the
two largest items, and neither is reachable from a configuration knob.
"""

import statistics
import timeit
import typing
import uuid
from random import Random

import sentry_scenarios
import sentry_sdk
from sentry_sdk.scope import Scope
from sentry_sdk.tracing import Transaction
from sentry_sdk.tracing_utils import Baggage, PropagationContext, _generate_sample_rand


HEADERS: typing.Final = {
    "host": "testserver",
    "user-agent": "bench/1.0",
    "accept": "*/*",
    "connection": "keep-alive",
}
TRACE_ID: typing.Final = uuid.uuid4().hex


def timed(label: str, stmt: typing.Callable[[], object], number: int = 20000, repeat: int = 5) -> None:
    times = timeit.repeat(stmt, number=number, repeat=repeat)
    best = min(times) / number * 1e6
    median = statistics.median(times) / number * 1e6
    print(f"{label:<46} {best:>8.2f} us (best) {median:>8.2f} us (med)")


def main() -> None:
    sentry_sdk.init(**sentry_scenarios.base_kwargs(max_breadcrumbs=15, attach_stacktrace=True))
    scope = Scope.get_isolation_scope()

    def start_and_finish() -> None:
        transaction = Transaction(op="http.server", name="GET /ping", source="route")
        with sentry_sdk.start_transaction(transaction, custom_sampling_context={"asgi_scope": {}}):
            pass

    def isolation() -> None:
        with sentry_sdk.isolation_scope():
            pass

    timed("uuid4().hex", lambda: uuid.uuid4().hex)
    timed("Random(trace_id)", lambda: Random(TRACE_ID))  # noqa: S311
    timed("_generate_sample_rand(trace_id)", lambda: _generate_sample_rand(TRACE_ID))
    timed("PropagationContext()", PropagationContext)
    timed("PropagationContext.from_incoming_data(headers)", lambda: PropagationContext.from_incoming_data(HEADERS))
    timed("Baggage.from_incoming_header(None)", lambda: Baggage.from_incoming_header(None))
    timed("scope.generate_propagation_context(headers)", lambda: scope.generate_propagation_context(HEADERS))
    timed(
        "scope.continue_trace(headers)",
        lambda: scope.continue_trace(HEADERS, op="http.server", name="GET /ping", source="route"),
    )
    timed("Transaction(op, name, source)", lambda: Transaction(op="http.server", name="GET /ping", source="route"))
    timed("start_transaction(txn) + exit  (tracing off)", start_and_finish, number=5000)
    timed("isolation_scope() enter/exit", isolation)
    timed("scope.fork()", scope.fork)
    timed("get_client()", sentry_sdk.get_client)


if __name__ == "__main__":
    main()
