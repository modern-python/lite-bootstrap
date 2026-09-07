# No Django bootstrapper

**Decision:** `lite-bootstrap` will not ship a Django bootstrapper. Django's size makes it the
framework most likely to be proposed by someone who has not hit the contract below.

Every bootstrapper keeps one contract: the user constructs the application, passes it in, and gets
the same object back. Django's observability is conventionally owned by `settings.py` — `MIDDLEWARE`
ordering, installed apps — which runs before any object a bootstrapper could be handed, so the
contract has no natural expression there. ADR-0001 is the calibration: FastMCP was the hardest
framework to fit and still had an application object to attach to.

Rejected: **attach to a constructed `ASGIHandler` instead.** This is the shape that would fit, and
today it means putting middleware outside `MIDDLEWARE`, diverging from every Django deployment guide
and from what a Django user would debug against.

**Revisit trigger:** a released, maintained path that attaches instrumentation to a constructed
`ASGIHandler` (or equivalent) without going through `settings.py`.
