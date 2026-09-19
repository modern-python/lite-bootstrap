# Core declares `typing-extensions`

A genuinely zero-dependency core was implemented, tested and abandoned. `HealthCheckTypedDict` is a
FastAPI response model, and pydantic refuses a stdlib `typing.TypedDict` model on Python < 3.12
(`PydanticUserError`) — a constraint that lives in pydantic's behaviour on an old interpreter, not in
a `TypedDict` you can build in isolation, so the attempt passed locally on 3.12 and failed the CI
matrix on 3.10 and 3.11. `1.3.0` had already shipped claiming a zero-dependency core and raised
`ModuleNotFoundError` on a bare install, masked everywhere because every extra pulls
`typing_extensions` transitively.

It is pure Python, so core stays free-threading-friendly, and the dependency can be dropped once the
floor reaches 3.12 — where `typing.TypedDict` is acceptable to pydantic and `Self` is in `typing`.
