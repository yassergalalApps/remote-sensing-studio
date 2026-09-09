from dataclasses import dataclass, field
from typing import Dict, Any, Optional

@dataclass(frozen=True)
class AnalysisContext:
    """
    Immutable object containing all metadata and configuration required for an analysis.
    Passed through the entire generic pipeline.
    """
    index_definition: Dict[str, Any]
    satellite_definition: Dict[str, Any]
    workspace_definition: Dict[str, Any]
    
    aoi: Dict[str, Any]
    date_range: Dict[str, str]  # e.g. {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
    dataset: str
    
    parameters: Dict[str, Any] = field(default_factory=dict)
    visualization: Dict[str, Any] = field(default_factory=dict)
    composite_settings: Dict[str, Any] = field(default_factory=dict)
    export_settings: Dict[str, Any] = field(default_factory=dict)
    statistics_settings: Dict[str, Any] = field(default_factory=dict)
