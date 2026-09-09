from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class VisualizationResult:
    """
    Immutable representation of a visualization attempt.
    """
    success: bool
    layer_id: str
    layer_name: str
    extent: str
    crs: str
    pixel_size: str
    renderer: str
    error_message: Optional[str] = None
    statistics: Optional[dict] = None
