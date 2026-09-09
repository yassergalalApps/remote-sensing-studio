from typing import Dict, Any, List

class FormulaEngine:
    """
    Pure mathematical evaluator for remote sensing indices.
    Strictly decoupled from Earth Engine, UI, and Providers.
    """
    
    @classmethod
    def evaluate(cls, image: Any, index_def: Dict[str, Any], satellite_def: Dict[str, Any], engine_type: str = "expression") -> Any:
        """
        Evaluates a formula on an image using the provided satellite and index definitions.
        
        Args:
            image: The image object (e.g. ee.Image, rasterio dataset)
            index_def: The JSON definition of the index
            satellite_def: The JSON definition of the target satellite
            engine_type: The engine to use (defaults to Google Earth Engine expression)
        """
        formula = index_def.get("formula", {})
        
        # Support both nested IndexRegistry and flat FormulaRegistry definitions
        if isinstance(formula, dict) and formula.get("expression"):
            expression = formula.get("expression", "")
            required_bands = formula.get("required_bands", [])
            formula_parameters = formula.get("parameters", {})
        else:
            expression = index_def.get("expression", "")
            required_bands = index_def.get("required_bands", [])
            formula_parameters = index_def.get("parameters", {})
            
        if not expression or not expression.strip():
            raise ValueError("Formula definition does not contain a valid non-empty expression.")
            
        band_mapping = satellite_def.get("band_mapping", {})
        
        expected_input = index_def.get("expected_input")
        if not expected_input:
            expected_input = index_def.get("input_semantics", {}).get("unit", "raw")
        bands_are_scaled = satellite_def.get("stored_as_scaled_integers", False)
        scale_factor = satellite_def.get("scale_factor", 1.0)
        additive_offset = satellite_def.get("additive_offset", 0.0)
        
        if engine_type == "expression":
            import ee
            import logging
            import sys
            from ..config import EVI_DEBUG
            
            if not isinstance(image, ee.Image):
                raise TypeError("FormulaEngine requires an ee.Image for the 'expression' engine.")
                
            expr_args = {}
            for generic_band in required_bands:
                if generic_band not in band_mapping:
                    raise ValueError(f"Satellite definition is missing band mapping for required band: {generic_band}")
                    
                native_band = band_mapping[generic_band]
                ee_band = image.select(native_band).toFloat()
                
                scaling_applied = False
                if bands_are_scaled and expected_input == "reflectance":
                    ee_band = ee_band.multiply(scale_factor)
                    if additive_offset != 0.0:
                        ee_band = ee_band.add(additive_offset)
                    scaling_applied = True
                        
                expr_args[generic_band] = ee_band
                
            if getattr(sys.modules.get('remote_sensing_studio.config', None), 'EVI_DEBUG', False) or EVI_DEBUG:
                scaling_info = {
                    "stored_as_scaled_integers": bands_are_scaled,
                    "scale_factor": scale_factor,
                    "input_unit": expected_input,
                    "scaling_applied": scaling_applied
                }
            # Inject mathematical parameters into the expression context
            for param_name, param_value in formula_parameters.items():
                expr_args[param_name] = ee.Number(param_value)
                
            from .safety_engine import SafetyEngine
            safety_def = index_def.get("safety", {})
            image = SafetyEngine.apply_pre_formula_safety(image, expr_args, safety_def)
                
            computed_img = image.expression(expression, expr_args).toFloat()
            
            computed_img = SafetyEngine.apply_post_formula_safety(computed_img, safety_def)
            
            return computed_img
            
        else:
            raise NotImplementedError(f"Formula Engine type '{engine_type}' is not yet supported.")
