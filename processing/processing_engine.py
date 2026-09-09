"""
Processing Engine Module.
Orchestrates formula resolution, band mapping, and delegates actual computation
to the Provider Adapter.
"""
import logging
from typing import Any, Dict
from ..utils.logger import get_logger
from ..analysis.analysis_context import AnalysisContext
from .band_mapper import BandMapper
from .formula_registry import FormulaRegistry
from .provider_adapter import ProviderAdapter

class ProcessingEngine:
    """
    Engine responsible for processing remote sensing algorithms abstractly.
    """
    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self.logger.debug("ProcessingEngine initialized.")
        
    def execute(self, formula_name: str, context: AnalysisContext) -> Any:
        """
        Resolves Provider -> Resolves Formula -> Resolves Bands -> Dispatches execution.
        """
        self.logger.info(f"ProcessingEngine dispatching execution for {formula_name}")
        
        # 1. Resolve Formula
        formula = FormulaRegistry.get_formula(formula_name)
        if not formula:
            raise ValueError(f"Formula {formula_name} not registered in Processing Engine.")
            
        # 2. Resolve Bands
        satellite = context.input_image.satellite
        resolved_bands = {}
        for logical_band in formula.required_bands:
            provider_band = BandMapper.get_band(satellite, logical_band)
            if not provider_band:
                raise ValueError(f"Band mapping not found for {logical_band} on {satellite}")
            resolved_bands[logical_band] = provider_band
            
        self.logger.debug(f"Resolved bands for {satellite}: {resolved_bands}")
        
        # 3. Resolve Provider Adapter
        adapter = ProviderAdapter(context.provider)
        
        # 4. Dispatch Execution
        self.logger.info("Delegating generic math expression to Provider Adapter.")
        result_ref = adapter.execute_band_math(
            expression=formula.expression,
            band_mapping=resolved_bands,
            context=context
        )
        
        return result_ref
