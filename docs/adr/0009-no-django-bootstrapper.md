# No Django bootstrapper

Every bootstrapper keeps one contract — the user constructs the application, passes it in, and gets
the same object back — and Django's observability is conventionally owned by `settings.py`
(`MIDDLEWARE` ordering, installed apps), which runs before any object a bootstrapper could be handed.
ADR-0001 is the calibration: FastMCP was the hardest framework to fit and still had an application
object to attach to. Attaching to a constructed `ASGIHandler` is the shape that would fit, and today
that means middleware outside `MIDDLEWARE`, diverging from every Django deployment guide and from
what a Django user would debug against.
