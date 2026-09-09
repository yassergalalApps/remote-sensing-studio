import abc
from typing import Dict, Any, List

class ProviderInterface(abc.ABC):
    """
    Abstract Base Class for all data providers.
    Ensures that AnalysisEngine can orchestrate any backend (GEE, Rasterio, STAC) interchangeably.
    """
    
    @abc.abstractmethod
    def load_dataset(self, context: 'AnalysisContext') -> Any:
        """Loads the raw imagery collection/dataset based on the context."""
        pass
        
    @abc.abstractmethod
    def apply_cloud_mask(self, dataset: Any, context: 'AnalysisContext') -> Any:
        """Applies provider-specific cloud/QA masking."""
        pass
        
    @abc.abstractmethod
    def build_composite(self, dataset: Any, context: 'AnalysisContext') -> Any:
        """Reduces the dataset (e.g. temporal median) into a single analytical image."""
        pass
        
    @abc.abstractmethod
    def evaluate_formula(self, image: Any, context: 'AnalysisContext') -> Any:
        """Applies the mathematical formula via the FormulaEngine."""
        pass
        
    @abc.abstractmethod
    def export(self, image: Any, context: 'AnalysisContext') -> Any:
        """Prepares the final image for download/saving."""
        pass
        
    @abc.abstractmethod
    def download(self, export_task: Any, filepath: str, context: 'AnalysisContext') -> bool:
        """Executes the physical download to disk."""
        pass
