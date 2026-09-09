"""
Analysis Result Module.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

@dataclass
class AnalysisResult:
    """Represents the output of a remote sensing analysis execution."""
    success: bool
    raster_reference: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    processing_time_sec: float = 0.0
    provider: str = "Unknown"
    projection: str = "Unknown"
    resolution: str = "Unknown"
    error_message: str = ""
