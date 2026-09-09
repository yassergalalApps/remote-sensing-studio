"""
Analysis Engine Module.
"""
import logging
from typing import Dict, Any, Optional
from .analysis_registry import AnalysisRegistry
from .analysis_context import AnalysisContext
from .analysis_result import AnalysisResult
from ..utils.logger import get_logger

class AnalysisEngine:
    """
    Core engine to orchestrate and execute analysis modules.
    Ensures UI never calls algorithms directly. Uses dependency injection.
    """
    def __init__(self, registry: Optional[AnalysisRegistry] = None) -> None:
        self.logger = get_logger(__name__)
        self.registry = registry or AnalysisRegistry
        self.registry.discover_modules()
        self.logger.debug("AnalysisEngine initialized.")
        
    def run(self, module_name: str, context: AnalysisContext) -> AnalysisResult:
        """Execute a specific analysis by name."""
        self.logger.info(f"AnalysisEngine initiating execution for: {module_name}")
        
        module_class = self.registry.get_module(module_name)
        if not module_class:
            msg = f"Analysis module '{module_name}' is not registered in the engine."
            self.logger.error(msg)
            return AnalysisResult(success=False, error_message=msg)
            
        try:
            module_instance = module_class()
            self.logger.info(f"Running {module_name} algorithm...")
            result = module_instance.run(context)
            
            if result.success:
                self.logger.info(f"{module_name} executed successfully in {result.processing_time_sec:.2f}s.")
            else:
                self.logger.warning(f"{module_name} failed: {result.error_message}")
                
            return result
        except Exception as e:
            self.logger.error(f"Error during {module_name} execution: {e}", exc_info=True)
            return AnalysisResult(success=False, error_message=str(e))

    def run_and_visualize(self, module_name: str, context: AnalysisContext, layer_name: str, iface: Any, zoom: bool = True) -> AnalysisResult:
        """
        Executes analysis and automatically injects the result into the QGIS canvas.
        Ensures the UI maintains single-point-of-contact with the Analysis Engine without
        violating provider independence.
        """
        # Delegate core computation cleanly
        result = self.run(module_name, context)
        
        # Intercept success state and push to QGIS Canvas
        if result.success:
            from ..services.visualization_service import VisualizationService
            vis_service = VisualizationService(iface)
            vis_service.visualize_result(result, layer_name, zoom, context.aoi_geojson)
            
        return result
