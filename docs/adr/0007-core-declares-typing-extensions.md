# Core declares `typing-extensions`; a genuinely zero-dependency core was tried and failed

**Decision:** `lite-bootstrap`'s core declares exactly one runtime dependency, `typing-extensions`.
The alternative — removing the two runtime uses so a bare install has no dependencies at all — was
implemented, tested, and abandoned.

`1.3.0` shipped claiming a zero-dependency core once `orjson` became opt-in (ADR-0005), but
`import lite_bootstrap` on a bare install raised `ModuleNotFoundError: No module named
'typing_extensions'`. Every install with any extra masked it, because every extra pulls
`typing_extensions` transitively.

## Rejected alternative: remove the usage

There are two runtime uses: `typing_extensions.Self` return annotations on `BaseConfig`'s
constructors, and `class HealthCheckTypedDict(typing_extensions.TypedDict, ...)` in the health-checks
instrument. The first is easy to drop (`from __future__ import annotations` plus `TYPE_CHECKING`).
The second is not, and that is what settles it: `HealthCheckTypedDict` is a FastAPI response model,
and pydantic refuses a stdlib `typing.TypedDict` model on Python < 3.12 —

```
PydanticUserError: Please use `typing_extensions.TypedDict` instead of
`typing.TypedDict` on Python < 3.12.
```

The attempt passed locally on 3.12 and against an isolated 3.10 `TypedDict` construction, and failed
the CI matrix on 3.10 and 3.11 — which is the shape of this whole class of mistake: the constraint
lives in pydantic's behaviour on an old interpreter, not in a `TypedDict` you can build in isolation.
So for as long as 3.10 and 3.11 are supported, core genuinely needs `typing_extensions` at runtime,
and declaring it is the honest fix. Dropping 3.10/3.11 to reclaim zero-dep was considered and is not
worth it on its own.

`typing-extensions` is pure Python, so core stays free-threading-friendly; this is the leanest core
available rather than a compromise on the ft story.

**Revisit trigger:** Python 3.11 goes out of support and the floor rises to 3.12, at which point
`typing.TypedDict` is acceptable to pydantic, `Self` is in `typing`, and the dependency can be
dropped for a genuinely zero-dependency core.
