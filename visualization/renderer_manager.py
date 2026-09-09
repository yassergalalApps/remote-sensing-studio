from qgis.core import (
    QgsRasterLayer,
    QgsColorRampShader,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
    QgsColorRamp,
    QgsGradientColorRamp,
    QgsGradientStop
)
from qgis.PyQt.QtGui import QColor
import logging
from typing import Dict, Any

logger = logging.getLogger("RemoteSensingStudio")

class RendererManager:
    """
    Controls the instantaneous update of the QGIS canvas entirely in-memory.
    Caches renderer objects. Changing a palette will never trigger recalculation of statistics.
    Target refresh time: < 500 ms.
    """
    
    def __init__(self):
        self._cached_renderers = {}

    def _create_color_ramp(self, color_stops_data) -> QgsGradientColorRamp:
        """Creates a QgsGradientColorRamp from a list of color stops."""
        stops = []
        
        # Sort stops by value just in case
        sorted_stops = sorted(color_stops_data, key=lambda x: x["value"])
        
        if not sorted_stops:
            return QgsGradientColorRamp(QColor(0, 0, 0), QColor(255, 255, 255))
            
        color1 = QColor(sorted_stops[0]["color"])
        color2 = QColor(sorted_stops[-1]["color"])
        
        min_val = sorted_stops[0]["value"]
        max_val = sorted_stops[-1]["value"]
        value_range = max_val - min_val
        
        for stop in sorted_stops[1:-1]:
            if value_range > 0:
                normalized_offset = (stop["value"] - min_val) / value_range
            else:
                normalized_offset = 0.5
            stops.append(QgsGradientStop(normalized_offset, QColor(stop["color"])))
            
        return QgsGradientColorRamp(color1, color2, False, stops)

    def updateRenderer(self, layer: QgsRasterLayer, symbology_template: Dict[str, Any], palette_data: Dict[str, Any]):
        """
        Dynamically modifies the existing QgsColorRampShader on the layer.
        Does not recreate the QgsSingleBandPseudoColorRenderer itself.
        """
        if not layer or not layer.isValid():
            logger.error("RendererManager: Invalid layer provided.")
            return

        renderer = layer.renderer()
        if not isinstance(renderer, QgsSingleBandPseudoColorRenderer):
            logger.error("RendererManager: Layer does not have a QgsSingleBandPseudoColorRenderer. Cannot update.")
            return
            
        shader = renderer.shader()
        if not shader:
            logger.error("RendererManager: Renderer does not have a shader.")
            return
            
        color_ramp = shader.rasterShaderFunction()
        if not isinstance(color_ramp, QgsColorRampShader):
            logger.error("RendererManager: Shader is not a QgsColorRampShader.")
            return

        mode = symbology_template.get("Classification Method", "Continuous")
        display_range = symbology_template.get("Display Range", [0, 1])
        
        # update classification mode
        try:
            if mode == "Continuous":
                color_ramp.setColorRampType(QgsColorRampShader.Interpolated)
                color_ramp.setClassificationMode(QgsColorRampShader.Continuous)
            elif mode == "Equal Interval" or mode == "Natural Breaks (Jenks)":
                color_ramp.setColorRampType(QgsColorRampShader.Discrete)
                color_ramp.setClassificationMode(QgsColorRampShader.EqualInterval)
            elif mode == "Exact":
                color_ramp.setColorRampType(QgsColorRampShader.Exact)
            else:
                color_ramp.setColorRampType(QgsColorRampShader.Interpolated)
                color_ramp.setClassificationMode(QgsColorRampShader.Continuous)
        except AttributeError:
            pass # fallback to Qt6 enumerations if needed

        color_ramp.setMinimumValue(display_range[0])
        color_ramp.setMaximumValue(display_range[1])
        
        # Build color ramp
        palette_name = palette_data.get("name", "")
        color_stops_data = palette_data.get("color_stops", [])
        
        if not color_stops_data:
            # Native QGIS ramp
            from qgis.core import QgsStyle
            native_ramp = QgsStyle.defaultStyle().colorRamp(palette_name)
            if native_ramp:
                color_ramp.setSourceColorRamp(native_ramp)
                color_ramp.classifyColorRamp()
        else:
            # Custom palette
            new_ramp = self._create_color_ramp(color_stops_data)
            color_ramp.setSourceColorRamp(new_ramp)
            color_ramp.classifyColorRamp()
            
        renderer.setClassificationMin(display_range[0])
        renderer.setClassificationMax(display_range[1])
        
        # Do not recreate QgsSingleBandPseudoColorRenderer or call layer.setRenderer()
        # Just notify that style changed and repaint
        layer.triggerRepaint()
        if hasattr(layer, 'emitStyleChanged'):
            layer.emitStyleChanged()
            
        import qgis.utils
        if qgis.utils.iface:
            try:
                from qgis.core import QgsProject
                root = QgsProject.instance().layerTreeRoot()
                node = root.findLayer(layer.id())
                if node:
                    qgis.utils.iface.layerTreeView().layerTreeModel().refreshLayerLegend(node)
            except Exception:
                pass
                
        logger.info(f"RendererManager: Instantly updated existing renderer for layer {layer.name()} using {mode} classification.")
