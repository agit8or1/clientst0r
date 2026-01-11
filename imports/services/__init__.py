"""
Import services for IT Glue and Hudu
"""
from .base import BaseImportService
from .itglue import ITGlueImportService
from .hudu import HuduImportService


def get_import_service(import_job):
    """
    Get the appropriate import service for an import job.

    Args:
        import_job: ImportJob instance

    Returns:
        Service instance (ITGlueImportService or HuduImportService)

    Raises:
        ValueError: If source_type is unknown
    """
    if import_job.source_type == 'itglue':
        return ITGlueImportService(import_job)
    elif import_job.source_type == 'hudu':
        return HuduImportService(import_job)
    else:
        raise ValueError(f"Unknown source type: {import_job.source_type}")


__all__ = [
    'BaseImportService',
    'ITGlueImportService',
    'HuduImportService',
    'get_import_service',
]
