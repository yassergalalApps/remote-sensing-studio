import logging
from typing import Optional, Dict, Any

try:
    from qgis.core import QgsSingleBandPseudoColorRenderer
    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False

from .vegetation_renderer import VegetationRenderer
from .water_detection_renderer import WaterDetectionRenderer
from .moisture_renderer import MoistureRenderer
from .moisture_stress_renderer import MoistureStressRenderer
from .urban_renderer import UrbanRenderer
from .bare_soil_renderer import BareSoilRenderer

logger = logging.getLogger("RemoteSensingStudio")

class RendererFactory:
    """
    Factory for creating domain-specific raster renderers natively in QGIS.
    Decouples rendering logic from the generic VisualizationService.
    """
    
    @classmethod
    def _create_custom_renderer(cls, provider, min_val: float, max_val: float, palette_data: Dict[str, Any]):
        from qgis.core import (
            QgsSingleBandPseudoColorRenderer,
            QgsRasterShader,
            QgsColorRampShader,
            QgsStyle
        )
        from qgis.PyQt.QtGui import QColor

        shader = QgsRasterShader()
        color_ramp = QgsColorRampShader()
        try:
            color_ramp.setColorRampType(QgsColorRampShader.Interpolated)
            color_ramp.setClassificationMode(QgsColorRampShader.Continuous)
        except AttributeError:
            color_ramp.setColorRampType(QgsColorRampShader.Type.Interpolated)
            color_ramp.setClassificationMode(QgsColorRampShader.ClassificationMode.Continuous)
            
        color_ramp.setClip(True)
        color_ramp.setMinimumValue(min_val)
        color_ramp.setMaximumValue(max_val)

        ramp_name = palette_data.get("name", "")
        color_stops = palette_data.get("color_stops", [])
        
        ramp_ref = None

        if not color_stops:
            # Native QGIS ramp
            default_style = QgsStyle.defaultStyle()
            ramp = default_style.colorRamp(ramp_name)
            if ramp:
                color_ramp.setSourceColorRamp(ramp)
                color_ramp.classifyColorRamp()
                ramp_ref = ramp
            else:
                logger.error(f"RendererFactory: Failed to load '{ramp_name}' color ramp from default style.")
                return None
        else:
            # Custom color stops
            from qgis.core import QgsGradientColorRamp, QgsGradientStop
            
            sorted_stops = sorted(color_stops, key=lambda s: s["value"])
            if not sorted_stops:
                logger.error(f"RendererFactory: Palette '{ramp_name}' has empty color_stops.")
                return None
                
            color1 = QColor(sorted_stops[0]["color"])
            color2 = QColor(sorted_stops[-1]["color"])
            
            orig_min = sorted_stops[0]["value"]
            orig_max = sorted_stops[-1]["value"]
            orig_range = orig_max - orig_min
            if orig_range == 0: orig_range = 1.0
            
            stops = []
            if len(sorted_stops) > 2:
                for stop in sorted_stops[1:-1]:
                    offset = (stop["value"] - orig_min) / orig_range
                    stops.append(QgsGradientStop(offset, QColor(stop["color"])))
                    
            ramp = QgsGradientColorRamp(color1, color2, False, stops)
            
            color_ramp.setSourceColorRamp(ramp)
            color_ramp.classifyColorRamp()
            ramp_ref = ramp

        shader.setRasterShaderFunction(color_ramp)
        renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
        renderer.setClassificationMin(min_val)
        renderer.setClassificationMax(max_val)

        renderer._shader_ref = shader
        renderer._color_ramp_ref = color_ramp
        if ramp_ref:
            renderer._ramp_ref = ramp_ref
            
        return renderer

    @classmethod
    def create_renderer(
        cls, 
        provider, 
        min_val: float, 
        max_val: float, 
        metadata: Dict[str, Any]
    ) -> Optional['QgsSingleBandPseudoColorRenderer']:
        
        if not HAS_QGIS:
            raise RuntimeError("QGIS core not available.")
            
        palette_override = metadata.get("palette_override")
        if palette_override:
            logger.info(f"RendererFactory: Intercepting custom palette override '{palette_override.get('name')}'")
            return cls._create_custom_renderer(provider, min_val, max_val, palette_override)
            
        renderer_family = metadata.get("renderer_family", "").lower()
        logger.info(f"========== RENDERER FACTORY DIAGNOSTICS ==========")
        logger.info(f"1. RendererFactory.create_renderer() CALLED.")
        logger.info(f"2. renderer_family read: '{renderer_family}'")
        
        if renderer_family == "vegetation":
            logger.info("3. Routing to VegetationRenderer.")
            renderer = VegetationRenderer.create(provider, min_val, max_val)
            logger.info(f"4. VegetationRenderer.create() executed. Returned type: {type(renderer).__name__}")
            logger.info(f"==================================================")
            return renderer
            
        elif renderer_family == "water_detection":
            logger.info("3. Routing to WaterDetectionRenderer.")
            renderer = WaterDetectionRenderer.create(provider, min_val, max_val)
            logger.info(f"4. WaterDetectionRenderer.create() executed. Returned type: {type(renderer).__name__}")
            logger.info(f"==================================================")
            return renderer
            
        elif renderer_family == "moisture":
            logger.info("3. Routing to MoistureRenderer.")
            renderer = MoistureRenderer.create(provider, min_val, max_val)
            logger.info(f"4. MoistureRenderer.create() executed. Returned type: {type(renderer).__name__}")
            logger.info(f"==================================================")
            return renderer
            
        elif renderer_family == "moisture_stress":
            logger.info("3. Routing to MoistureStressRenderer.")
            renderer = MoistureStressRenderer.create(provider, min_val, max_val)
            logger.info(f"4. MoistureStressRenderer.create() executed. Returned type: {type(renderer).__name__}")
            logger.info(f"==================================================")
            return renderer
            
        elif renderer_family == "urban":
            logger.info("3. Routing to UrbanRenderer.")
            renderer = UrbanRenderer.create(provider, min_val, max_val)
            logger.info(f"4. UrbanRenderer.create() executed. Returned type: {type(renderer).__name__}")
            logger.info(f"==================================================")
            return renderer
            
        elif renderer_family == "bare_soil":
            logger.info("3. Routing to BareSoilRenderer.")
            renderer = BareSoilRenderer.create(provider, min_val, max_val)
            logger.info(f"4. BareSoilRenderer.create() executed. Returned type: {type(renderer).__name__}")
            logger.info(f"==================================================")
            return renderer
            
        # Fallback to standard/legacy rendering if no family is specified or matched
        logger.info(f"RendererFactory: No specific family found for '{renderer_family}'. Falling back to None.")
        return None
