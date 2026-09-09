import logging

try:
    from qgis.core import (
        QgsSingleBandPseudoColorRenderer,
        QgsRasterShader,
        QgsColorRampShader,
        QgsGradientColorRamp,
        QgsGradientStop
    )
    from qgis.PyQt.QtGui import QColor
    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False

logger = logging.getLogger("RemoteSensingStudio")

class BareSoilRenderer:
    """
    Reusable renderer family for bare soil and arid indices (BSI, NDBaI, DBSI).
    Colors range from Cream (Covered/Vegetated) through Sand, Tan, and Brown to Dark Brown (Bare Soil).
    """
    
    @staticmethod
    def _create_ramp() -> 'QgsGradientColorRamp':
        colors = ["#FCF8E3", "#EEDC82", "#D2B48C", "#A67B5B", "#734A12", "#3F2A14"]
        color1 = QColor(colors[0])
        color2 = QColor(colors[-1])
        
        stops = []
        num_stops = len(colors)
        for i in range(1, num_stops - 1):
            offset = i / (num_stops - 1)
            stops.append(QgsGradientStop(offset, QColor(colors[i])))
            
        return QgsGradientColorRamp(color1, color2, False, stops)
    
    @staticmethod
    def create(provider, min_val: float, max_val: float) -> 'QgsSingleBandPseudoColorRenderer':
        if not HAS_QGIS:
            raise RuntimeError("QGIS core not available. Cannot create renderer.")
            
        ramp = BareSoilRenderer._create_ramp()
        
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
        
        color_ramp.setSourceColorRamp(ramp)
        color_ramp.classifyColorRamp()
        
        shader.setRasterShaderFunction(color_ramp)
        
        renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
        renderer.setClassificationMin(min_val)
        renderer.setClassificationMax(max_val)
        
        renderer._shader_ref = shader
        renderer._color_ramp_ref = color_ramp
        renderer._ramp_ref = ramp
        
        return renderer
