# No Django bootstrapper

Every bootstrapper keeps one contract: it takes the user's application, or builds one from config,
instruments it and returns it. FastAPI, FastStream and FastMCP accept an application and build a
default one when none is passed. Litestar always builds its own with `Litestar.from_config` from the
user's `application_config`, because its plugins and middleware must be in the `AppConfig` before the
app exists. Django's observability is conventionally owned by `settings.py` (`MIDDLEWARE` ordering,
installed apps), which runs before any object a bootstrapper could be handed or build.
ADR-0001 is the calibration: FastMCP was the hardest framework to fit and still had an application
object to attach to. Attaching to a constructed `ASGIHandler` is the shape that would fit, and today
that means middleware outside `MIDDLEWARE`, diverging from every Django deployment guide and from
what a Django user would debug against.
