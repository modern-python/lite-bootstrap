from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from taskiq import InMemoryBroker, TaskiqEvents, TaskiqState
from taskiq.instrumentation import TaskiqInstrumentor
from taskiq.middlewares.opentelemetry_middleware import OpenTelemetryMiddleware

from lite_bootstrap import FreeBootstrapper, FreeConfig


def _register_recipe(broker: InMemoryBroker, config: FreeConfig) -> None:
    @broker.on_event(TaskiqEvents.WORKER_STARTUP)
    async def bootstrap_observability(state: TaskiqState) -> None:
        state.bootstrapper = FreeBootstrapper(config)
        state.bootstrapper.bootstrap()
        TaskiqInstrumentor().instrument_broker(broker)

    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def teardown_observability(state: TaskiqState) -> None:
        state.bootstrapper.teardown()


async def test_taskiq_recipe_traces_tasks_and_tears_down() -> None:
    broker = InMemoryBroker()

    @broker.task
    async def add(left: int, right: int) -> int:
        return left + right

    _register_recipe(broker, FreeConfig(opentelemetry_log_traces=True, logging_buffer_capacity=0))

    await broker.startup()
    try:
        bootstrapper = broker.state.bootstrapper
        assert bootstrapper.is_bootstrapped
        assert any(isinstance(middleware, OpenTelemetryMiddleware) for middleware in broker.middlewares)

        tracer_provider = trace.get_tracer_provider()
        assert isinstance(tracer_provider, TracerProvider)
        exporter = InMemorySpanExporter()
        tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

        task = await add.kiq(1, 2)
        result = await task.wait_result()
        assert result.return_value == 1 + 2
        span_kinds = {span.kind for span in exporter.get_finished_spans() if span.name.endswith(add.task_name)}
        assert span_kinds == {trace.SpanKind.PRODUCER, trace.SpanKind.CONSUMER}
    finally:
        await broker.shutdown()

    assert not bootstrapper.is_bootstrapped
