import logging

try:
    from qgis.core import (
        QgsSingleBandPseudoColorRenderer,
        QgsRasterShader,
        QgsColorRampShader,
        QgsStyle
    )
    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False

logger = logging.getLogger("RemoteSensingStudio")

class VegetationRenderer:
    """
    Standardized renderer for the vegetation scientific family (NDVI, SAVI, EVI, etc).
    Ensures identical cartographic representation across all vegetation indices.
    """
    
    @staticmethod
    def create(provider, min_val: float, max_val: float) -> 'QgsSingleBandPseudoColorRenderer':
        if not HAS_QGIS:
            raise RuntimeError("QGIS core not available. Cannot create renderer.")
            
        ramp_name = "RdYlGn"
        default_style = QgsStyle.defaultStyle()
        ramp = default_style.colorRamp(ramp_name)
        
        logger.info(f"VegetationRenderer Diagnostics: QgsStyle.defaultStyle().colorRamp('{ramp_name}') returned: {type(ramp).__name__ if ramp else 'None'}")
        
        if not ramp:
            logger.error(f"VegetationRenderer: Failed to load '{ramp_name}' color ramp from default style.")
            return None
            
        shader = QgsRasterShader()
        color_ramp = QgsColorRampShader()
        
        try:
            color_ramp.setColorRampType(QgsColorRampShader.Interpolated)
            color_ramp.setClassificationMode(QgsColorRampShader.Continuous)
        except AttributeError:
            # Fallback for older QGIS versions/PyQt5
            color_ramp.setColorRampType(QgsColorRampShader.Type.Interpolated)
            color_ramp.setClassificationMode(QgsColorRampShader.ClassificationMode.Continuous)
        
        # Ensure pixels outside statistics bounds don't get colored
        color_ramp.setClip(True)
        color_ramp.setMinimumValue(min_val)
        color_ramp.setMaximumValue(max_val)
        
        # Use the native QGIS classification sequence
        color_ramp.setSourceColorRamp(ramp)
        color_ramp.classifyColorRamp()
        
        shader.setRasterShaderFunction(color_ramp)
        
        renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
        renderer.setClassificationMin(min_val)
        renderer.setClassificationMax(max_val)
        
        # CRITICAL FIX: Prevent PyQGIS garbage collection bugs.
        # When this function returns, Python will destroy the local variables.
        # If the SIP bindings fail to transfer ownership to C++, the renderer becomes invalid
        # and QGIS Core silently replaces it with a Gray renderer during addMapLayer.
        renderer._shader_ref = shader
        renderer._color_ramp_ref = color_ramp
        renderer._ramp_ref = ramp
        
        logger.info(f"VegetationRenderer Diagnostics: Returning renderer of type: {type(renderer).__name__}")
        
        return renderer
