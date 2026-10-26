"""Errors the services raise. main.py turns each into an HTTP response with the right status
code, so services never need to know about HTTP.

Every error the API sends has the same shape:
    {"error": {"code": "not_found", "message": "...", "request_id": "..."}}
"""
from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class BadRequestError(AppError):
    pass


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"


def error_response(request: Request, status_code: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}
    if details:
        body["details"] = details
    return JSONResponse(status_code=status_code, content={"error": body})
