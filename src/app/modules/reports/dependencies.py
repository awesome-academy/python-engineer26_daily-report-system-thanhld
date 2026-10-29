from typing import Annotated

from fastapi import Depends

from app.api.deps import DbSession
from app.modules.reports.service import ReportService


def get_report_service(session: DbSession) -> ReportService:
    return ReportService(session)


ReportServiceDep = Annotated[ReportService, Depends(get_report_service)]
