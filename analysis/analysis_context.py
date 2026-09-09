"""
Analysis Context Module.
"""
from dataclasses import dataclass, field
from typing import Any, Dict
from ..models.image_model import ImageModel

@dataclass
class AnalysisContext:
    """Encapsulates the input data and parameters required for an analysis."""
    input_image: ImageModel
    aoi_geojson: Dict[str, Any]
    provider: Any
    parameters: Dict[str, Any] = field(default_factory=dict)
