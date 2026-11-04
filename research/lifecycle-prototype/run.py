"""THROWAWAY lifecycle contract experiment. Run with: uv run --no-sync python research/lifecycle-prototype/run.py."""

import asyncio
import contextlib
import functools
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, Request
from faststream.asgi import AsgiFastStream
from faststream.redis import RedisBroker
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import ProxyTracerProvider, get_tracer, get_tracer_provider, set_tracer_provider
from starlette.testclient import TestClient


class ProbeExporter(InMemorySpanExporter):
    def __init__(self, state, fail=False):
        super().__init__()
        self.state = state
        self.fail = fail
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1
        self.state["events"].append("exporter shutdown")
        super().shutdown()
        if self.fail:
            raise RuntimeError("cleanup failed")


def span(state, name):
    state["events"].append(name)
    with get_tracer("prototype").start_as_current_span(name):
        pass


@contextlib.contextmanager
def observability(state):
    """Proposed process-level ownership, shared by both designs; no production imports."""
    owned_provider = None
    primary_error = None
    try:
        provider = get_tracer_provider()
        if isinstance(provider, ProxyTracerProvider):
            provider = TracerProvider(shutdown_on_exit=False)
            owned_provider = provider
            provider.add_span_processor(SimpleSpanProcessor(state["exporter"]))
            set_tracer_provider(provider)
            state["events"].append("own provider")
        else:
            state["events"].append("borrow provider")
        if state["scenario"] == "setup-error":
            raise state["primary"]
        yield provider
    except BaseException as error:
        primary_error = error
        raise
    finally:
        if owned_provider is not None:
            try:
                owned_provider.shutdown()
            except Exception as error:
                if primary_error is None:
                    raise
                primary_error.add_note(f"Observability cleanup: {error}")


def managed_lifespan(user_lifespan, state):
    """Design A: constructor-supplied lifespan composition, with no application mutation."""

    @contextlib.asynccontextmanager
    @functools.wraps(user_lifespan)
    async def lifespan(*args, **kwargs):
        with observability(state):
            async with user_lifespan(*args, **kwargs) as result:
                yield result

    return lifespan


def make_application(framework, variant, state):
    scenario = state["scenario"]

    @contextlib.asynccontextmanager
    async def fastapi_lifespan(app):
        state["arguments_preserved"] = app is state["app"]
        span(state, "user startup")
        if scenario == "startup-error":
            raise state["primary"]
        try:
            yield {"service": "ready"}
        finally:
            span(state, "user shutdown")
            if scenario in ("shutdown-error", "combined-error"):
                raise state["primary"]

    @contextlib.asynccontextmanager
    async def faststream_lifespan(service: str = "default"):
        state["arguments_preserved"] = service == "configured"
        span(state, "user startup")
        if scenario == "startup-error":
            raise state["primary"]
        try:
            yield
        finally:
            span(state, "user shutdown")
            if scenario in ("shutdown-error", "combined-error"):
                raise state["primary"]

    user_lifespan = fastapi_lifespan if framework == "fastapi" else faststream_lifespan
    lifespan = managed_lifespan(user_lifespan, state) if variant == "lifespan" else user_lifespan
    if framework == "fastapi":
        app = FastAPI(lifespan=lifespan)

        @app.get("/work")
        async def work(request: Request):
            span(state, "work")
            return {"service": request.state.service}

        FastAPIInstrumentor.instrument_app(app, exclude_spans=["receive", "send"])
    else:

        async def shutdown_hook():
            span(state, "shutdown hook")
            if scenario == "hook-error":
                raise state["primary"]

        app = AsgiFastStream(RedisBroker(), lifespan=lifespan, on_shutdown=[shutdown_hook], logger=None)
    state["app"] = app
    return app


async def drive_faststream(app, state):
    async def stop_broker():
        span(state, "broker drain")
        if state["scenario"] == "broker-error":
            raise state["primary"]

    with (
        patch.object(app.broker, "start", new=AsyncMock()),
        patch.object(app.broker, "stop", new=AsyncMock(side_effect=stop_broker)),
    ):
        if state["scenario"] == "manual":
            await app.start()
            span(state, "work")
            await app.stop()
        else:
            async with app.start_lifespan_context(run_extra_options={"service": "configured"}):
                span(state, "work")


def child(framework, variant, scenario):
    state = {"scenario": scenario, "events": [], "primary": ValueError("primary failed")}
    exporter = ProbeExporter(state, fail=scenario in ("cleanup-error", "combined-error"))
    state["exporter"] = exporter
    external = scenario == "external"
    if external:
        external_provider = TracerProvider(shutdown_on_exit=False)
        external_provider.add_span_processor(SimpleSpanProcessor(exporter))
        set_tracer_provider(external_provider)
    app = make_application(framework, variant, state)
    error = None
    try:
        with observability(state) if variant == "explicit" else contextlib.nullcontext():
            if framework == "fastapi":
                with TestClient(app) as client:
                    response = client.get("/work")
                    state["result_preserved"] = response.json() == {"service": "ready"}
            else:
                asyncio.run(drive_faststream(app, state))
    except Exception as caught:
        error = caught
    if external:
        span(state, "external after cleanup")
    names = [item.name for item in exporter.get_finished_spans()]
    expected_error = scenario.endswith("error")
    owned_shutdowns = 0 if external or (scenario == "manual" and variant == "lifespan") else 1
    expected_names = {
        "setup-error": [],
        "startup-error": ["user startup"],
        "hook-error": ["user startup", "work", "shutdown hook", "user shutdown"],
        "broker-error": ["user startup", "work", "shutdown hook", "broker drain", "user shutdown"],
        "manual": ["work", "shutdown hook", "broker drain"] if variant == "explicit" else [],
    }.get(
        scenario,
        ["user startup", "work", "user shutdown"]
        if framework == "fastapi"
        else ["user startup", "work", "shutdown hook", "broker drain", "user shutdown"],
    )
    primary_expected = scenario in (
        "setup-error",
        "startup-error",
        "shutdown-error",
        "hook-error",
        "broker-error",
        "combined-error",
    )
    checks = {
        "expected_error": (error is not None) == expected_error,
        "primary_preserved": not primary_expected or error is state["primary"],
        "cleanup_note": scenario != "combined-error"
        or any("cleanup failed" in note for note in getattr(error, "__notes__", [])),
        "shutdown_ownership": exporter.shutdown_calls == owned_shutdowns,
        "shutdown_spans": all(name in names for name in expected_names),
        "arguments": scenario in ("setup-error", "manual") or state.get("arguments_preserved", False),
        "lifespan_result": framework != "fastapi" or expected_error or state.get("result_preserved", False),
        "external_survives": not external
        or (get_tracer_provider() is external_provider and "external after cleanup" in names),
    }
    result = {
        "framework": framework,
        "variant": variant,
        "scenario": scenario,
        "status": "unsupported"
        if scenario == "manual" and variant == "lifespan"
        else "pass"
        if all(checks.values())
        else "fail",
        "events": state["events"],
        "exported_spans": names,
        "shutdown_calls": exporter.shutdown_calls,
        "error": type(error).__name__ if error else None,
        "error_message": str(error) if error else None,
        "notes": getattr(error, "__notes__", []),
        "checks": checks,
    }
    if external:
        external_provider.shutdown()
    print(json.dumps(result))


def main():
    if len(sys.argv) == 4:
        child(*sys.argv[1:])
        return
    cases = ["happy", "setup-error", "startup-error", "shutdown-error", "cleanup-error", "combined-error", "external"]
    results = []
    for framework in ("fastapi", "faststream"):
        for variant in ("lifespan", "explicit"):
            for scenario in cases + (["hook-error", "broker-error", "manual"] if framework == "faststream" else []):
                process = subprocess.run(
                    [sys.executable, __file__, framework, variant, scenario], text=True, capture_output=True, check=True
                )
                result = json.loads(process.stdout)
                results.append(result)
                print(f"{framework:10} {variant:9} {scenario:15} {result['status']}")
    output = {
        "versions": {
            name: importlib.metadata.version(name)
            for name in (
                "fastapi",
                "faststream",
                "opentelemetry-sdk",
                "opentelemetry-instrumentation-fastapi",
                "starlette",
            )
        },
        "results": results,
    }
    path = Path(__file__).with_name("results.json")
    path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Recorded {len(results)} isolated runs in {path}")
    if any(row["status"] == "fail" for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
