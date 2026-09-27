from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    """Error returned to the client as {"error": true, "message": ..., **extra}."""

    def __init__(self, status_code: int, message: str, **extra):
        self.status_code = status_code
        self.message = message
        self.extra = extra


def register_error_handlers(app: FastAPI) -> None:
    # The frontend reads `message` from error bodies
    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": True, "message": exc.message, **exc.extra},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": True, "message": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        return JSONResponse(
            status_code=422,
            content={
                "error": True,
                "message": f"{location}: {first.get('msg', 'Invalid request')}".strip(": "),
                "details": exc.errors(),
            },
        )
