# Migration guide for lite-bootstrap 2.x

## CORS methods on FastAPI and Litestar

In 2.x, `cors_allowed_methods` defaults to `["*"]`. If you configure allowed
origins and omit the method list, preflight requests can now succeed for all
standard HTTP methods, including POST.

Set `cors_allowed_methods` explicitly to restrict cross-origin requests to the
methods your application supports, such as `["GET", "POST"]`.

`cors_allowed_headers` defaults to `[]`. Both frameworks allow their built-in
CORS headers, including `Content-Type`. Add headers such as `Authorization`
explicitly if your application needs them.
