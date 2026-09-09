"""
Project Model Module.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from ..utils.logger import get_logger
from .image_model import ImageModel

@dataclass
class ProjectModel:
    """Data model representing an analysis project and its state."""
    
    name: str = "Untitled Project"
    workspace: str = "Custom"
    selected_image: Optional[ImageModel] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> bool:
        logger = get_logger(__name__)
        logger.debug(f"Validating ProjectModel: {self.name}")
        return True
