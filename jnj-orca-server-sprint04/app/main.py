from fastapi import FastAPI, status
from app.api import health
from app.api.v1.endpoints import source, compound, study, database_release, reporting_effort, user, distribution_list, output_detail, tag, download, dbr_tag,combined_tag, export_import_tags,audit_log
from app.core.exceptions import add_exception_handlers
from fastapi_pagination import add_pagination
from fastapi.middleware.cors import CORSMiddleware
from app.config.settings import settings
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.utils.audit_log_middleware import audit_middleware

def create_app() -> FastAPI:
    app = FastAPI(title="FastAPI App", version="0.1.0")

    

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins(),
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

 

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
        errors = []
        for err in exc.errors():
            msg = err['msg']
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, "):]
            errors.append({
                "field": ".".join(map(str, err["loc"][1:])),  # skip "body"
                "message": msg
            })
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": errors},
        )

    # Routers
    app.include_router(health.router)
    app.middleware("http")(audit_middleware)
    app.include_router(source.router, prefix="/api/v1/sources", tags=["Source"])
    app.include_router(compound.router, prefix="/api/v1/compounds", tags=["Compound"])
    app.include_router(study.router, prefix="/api/v1/studies", tags=["Study"])
    app.include_router(database_release.router, prefix="/api/v1/database-releases", tags=["Database Release"])
    app.include_router(reporting_effort.router, prefix="/api/v1/reporting-efforts", tags=["Reporting Effort"])
    app.include_router(user.router, prefix="/api/v1/users", tags=["User"])
    app.include_router(distribution_list.router, prefix="/api/v1/distribution-lists", tags=["Distribution List"])
    app.include_router(output_detail.router, prefix="/api/v1/output-details", tags=["OutputDetail"])
    app.include_router(tag.router, prefix="/api/v1/tags", tags=["ReportingEffortTag"])
    app.include_router(download.router, prefix="/api/v1/download", tags=["Download"])
    app.include_router(dbr_tag.router, prefix="/api/v1/dbrs/tags", tags=["DatabaseReleaseTag"])
    app.include_router(export_import_tags.router, prefix="/api/v1", tags=["Export/Import Tags"])
    app.include_router(combined_tag.router, prefix="/api/v1/combined/tags", tags=["CombinedTag"])
    app.include_router(audit_log.router, prefix="/api/v1/audit-logs", tags=["AuditLogs"])

    # Exception handlers
    add_exception_handlers(app)
    add_pagination(app)
    return app

app = create_app()
