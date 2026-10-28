"""Per-operation costs of the pieces sentry-sdk runs on every request.

Attributes the per-request total from `run.py` to individual calls, which is what makes the
upstream issues actionable: on sentry-sdk 2.x, `Transaction(...)` and the Mersenne Twister seed
inside it are the two largest items, and neither is reachable from a configuration knob. 3.x builds
no transaction while tracing is off, so there it times `continue_trace` and the root `start_span`
that the ASGI integration calls on every request instead.
"""

import importlib
import statistics
import timeit
import typing
import uuid
from random import Random

import sentry_scenarios
import sentry_sdk
from sentry_sdk.scope import Scope
from sentry_sdk.tracing_utils import Baggage, PropagationContext, _generate_sample_rand

from lite_bootstrap.instruments.sentry_instrument import IS_SENTRY_SDK_2


HEADERS: typing.Final = {
    "host": "testserver",
    "user-agent": "bench/1.0",
    "accept": "*/*",
    "connection": "keep-alive",
}
TRACE_ID: typing.Final = uuid.uuid4().hex
SDK2_TRACING: typing.Final[typing.Any] = importlib.import_module("sentry_sdk.tracing") if IS_SENTRY_SDK_2 else None


def timed(label: str, stmt: typing.Callable[[], object], number: int = 20000, repeat: int = 5) -> None:
    times = timeit.repeat(stmt, number=number, repeat=repeat)
    best = min(times) / number * 1e6
    median = statistics.median(times) / number * 1e6
    print(f"{label:<46} {best:>8.2f} us (best) {median:>8.2f} us (med)")


def time_sdk2_transaction(isolation_scope: typing.Any, current_scope: typing.Any) -> None:  # noqa: ANN401
    def new_transaction() -> object:
        return SDK2_TRACING.Transaction(op="http.server", name="GET /ping", source="route")

    def start_and_finish() -> None:
        with current_scope.start_transaction(new_transaction(), custom_sampling_context={"asgi_scope": {}}):
            pass

    timed(
        "scope.continue_trace(headers)",
        lambda: isolation_scope.continue_trace(HEADERS, op="http.server", name="GET /ping", source="route"),
    )
    timed("Transaction(op, name, source)", new_transaction)
    timed("start_transaction(txn) + exit  (tracing off)", start_and_finish, number=5000)


def time_sdk3_span() -> None:
    def start_and_end() -> None:
        with sentry_sdk.start_span(name="GET /ping", parent_span=None):
            pass

    timed("continue_trace(headers)", lambda: sentry_sdk.continue_trace(HEADERS))
    timed("start_span(root) + exit  (tracing off)", start_and_end, number=5000)


def main() -> None:
    sentry_sdk.init(**sentry_scenarios.base_kwargs(max_breadcrumbs=15, attach_stacktrace=True))
    scope = Scope.get_isolation_scope()

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
    if IS_SENTRY_SDK_2:
        time_sdk2_transaction(scope, sentry_sdk.get_current_scope())
    else:
        time_sdk3_span()
    timed("isolation_scope() enter/exit", isolation)
    timed("scope.fork()", scope.fork)
    timed("get_client()", sentry_sdk.get_client)


if __name__ == "__main__":
    main()
