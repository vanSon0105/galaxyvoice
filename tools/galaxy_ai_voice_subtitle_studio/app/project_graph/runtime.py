from __future__ import annotations

from pathlib import Path

from ..common.config import default_config_path
from .service import ProjectGraphService


def project_graph_service(settings_path: Path | None = None) -> ProjectGraphService:
    settings = Path(settings_path) if settings_path is not None else default_config_path()
    return ProjectGraphService(settings.with_name("project_graph.json"))
