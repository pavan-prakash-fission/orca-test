from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

class AppException(Exception):
    def __init__(self, message: str):
        self.message = message

def add_exception_handlers(app: FastAPI):
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=400,
            content={"error": exc.message}
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"error": "Internal Server Error"}
        )
