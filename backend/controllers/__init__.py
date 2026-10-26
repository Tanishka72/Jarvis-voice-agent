"""Controllers (FastAPI calls them routers): one file per resource.

A controller only does HTTP work: read the validated input, call ONE service method,
and choose the status code and response shape. No SQL, no business rules.
"""
