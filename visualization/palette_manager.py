import json
import os
import logging
from typing import Dict, Any, List

logger = logging.getLogger("RemoteSensingStudio")

class PaletteManager:
    """
    Manages the available palettes.
    Stores every palette as an external JSON definition.
    Allows saving and loading custom palettes.
    """
    
    def __init__(self, palettes_dir: str):
        self.palettes_dir = palettes_dir
        self.palettes: Dict[str, Dict[str, Any]] = {}
        
        if not os.path.exists(self.palettes_dir):
            os.makedirs(self.palettes_dir)
            
        self._ensure_default_palettes()
        self.load_all_palettes()

    def _ensure_default_palettes(self):
        """Creates default palette JSON files if they do not exist."""
        defaults = {
            "Standard NDVI": {
                "name": "Standard NDVI",
                "description": "Standard diverging color ramp for vegetation",
                "recommended_index": "NDVI",
                "recommended_display_range": [-1.0, 1.0],
                "recommended_threshold": 0.2,
                "color_stops": [
                    {"value": -1.0, "color": "#000000"},
                    {"value": 0.0, "color": "#FFFFFF"},
                    {"value": 0.2, "color": "#E6F598"},
                    {"value": 0.6, "color": "#66BD63"},
                    {"value": 1.0, "color": "#006837"}
                ]
            },
            "NDWI Blues": {
                "name": "NDWI Blues",
                "description": "Blue color ramp for water indices",
                "recommended_index": "NDWI",
                "recommended_display_range": [-1.0, 1.0],
                "recommended_threshold": 0.0,
                "color_stops": [
                    {"value": -1.0, "color": "#F7FBFF"},
                    {"value": 0.0, "color": "#9ECAE1"},
                    {"value": 1.0, "color": "#08306B"}
                ]
            },
            "Terrain": {
                "name": "Terrain",
                "description": "Standard terrain color ramp for elevation",
                "recommended_index": "DEM",
                "recommended_display_range": [0, 3000],
                "recommended_threshold": 1000,
                "color_stops": [
                    {"value": 0.0, "color": "#33A02C"},
                    {"value": 0.3, "color": "#B2DF8A"},
                    {"value": 0.6, "color": "#FDBF6F"},
                    {"value": 1.0, "color": "#FF7F00"}
                ]
            },
            "RdYlGn": {
                "name": "RdYlGn",
                "description": "Native QGIS RdYlGn color ramp",
                "recommended_index": "NDVI",
                "recommended_display_range": [-1.0, 1.0],
                "recommended_threshold": 0.2,
                "color_stops": []
            }
        }
        
        for name, data in defaults.items():
            file_path = os.path.join(self.palettes_dir, f"{name.replace(' ', '_')}.json")
            if not os.path.exists(file_path):
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)

    def load_all_palettes(self):
        """Loads all JSON palettes from the palettes directory."""
        self.palettes.clear()
        for filename in os.listdir(self.palettes_dir):
            if filename.endswith(".json"):
                file_path = os.path.join(self.palettes_dir, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if "name" in data:
                            self.palettes[data["name"]] = data
                except Exception as e:
                    logger.error(f"Failed to load palette {filename}: {e}")

    def load(self, palette_name: str) -> Dict[str, Any]:
        """Returns a specific palette by name."""
        if palette_name in self.palettes:
            return self.palettes[palette_name]
            
        try:
            from qgis.core import QgsStyle
            if palette_name in QgsStyle.defaultStyle().colorRampNames():
                return {"name": palette_name, "type": "continuous", "color_stops": []}
        except Exception:
            pass
            
        return self.palettes.get("RdYlGn", {})

    def get_palette_names(self) -> List[str]:
        """Returns a list of all loaded palette names."""
        return sorted(list(self.palettes.keys()))

    def save_custom_palette(self, name: str, palette_data: Dict[str, Any]):
        """Saves a custom palette definition to JSON."""
        file_path = os.path.join(self.palettes_dir, f"{name.replace(' ', '_')}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(palette_data, f, indent=4)
        self.palettes[name] = palette_data

    def populate_palette_combo(self, cmbPreviewPalette):
        from qgis.core import QgsStyle, QgsGradientColorRamp, QgsSymbolLayerUtils, QgsGradientStop
        from qgis.PyQt.QtGui import QIcon, QColor
        from qgis.PyQt.QtCore import QSize, Qt
        from qgis.PyQt.QtWidgets import QStyledItemDelegate
        
        cmbPreviewPalette.clear()
        cmbPreviewPalette.setIconSize(QSize(80, 14))
        
        class PaletteDelegate(QStyledItemDelegate):
            def initStyleOption(self, option, index):
                super().initStyleOption(option, index)
                display_role = Qt.ItemDataRole.DisplayRole if hasattr(Qt, 'ItemDataRole') else Qt.DisplayRole
                if index.data(display_role) == "Standard NDVI":
                    option.text = ""
        cmbPreviewPalette.setItemDelegate(PaletteDelegate(cmbPreviewPalette))
        
        custom_palettes = self.get_palette_names()
        model = cmbPreviewPalette.model()
        
        # 1. Custom Remote Sensing Studio Palettes
        cmbPreviewPalette.addItem("Remote Sensing Studio")
        idx = cmbPreviewPalette.count() - 1
        item = model.item(idx)
        if item:
            item.setEnabled(False)
            if hasattr(Qt, 'ItemFlag'):
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                item.setFlags(Qt.NoItemFlags)
        
        for name in custom_palettes:
            data = self.load(name)
            color_stops = data.get("color_stops", [])
            icon = QIcon()
            if color_stops:
                sorted_stops = sorted(color_stops, key=lambda s: s["value"])
                if sorted_stops:
                    color1 = QColor(sorted_stops[0]["color"])
                    color2 = QColor(sorted_stops[-1]["color"])
                    orig_min = sorted_stops[0]["value"]
                    orig_range = sorted_stops[-1]["value"] - orig_min
                    if orig_range == 0: orig_range = 1.0
                    
                    stops = []
                    if len(sorted_stops) > 2:
                        for stop in sorted_stops[1:-1]:
                            offset = (stop["value"] - orig_min) / orig_range
                            stops.append(QgsGradientStop(offset, QColor(stop["color"])))
                            
                    ramp = QgsGradientColorRamp(color1, color2, False, stops)
                    pixmap = QgsSymbolLayerUtils.colorRampPreviewPixmap(ramp, QSize(80, 14))
                    if not pixmap.isNull():
                        icon = QIcon(pixmap)
            else:
                style = QgsStyle.defaultStyle()
                ramp = style.colorRamp(name)
                if isinstance(ramp, QgsGradientColorRamp):
                    pixmap = QgsSymbolLayerUtils.colorRampPreviewPixmap(ramp, QSize(80, 14))
                    if not pixmap.isNull():
                        icon = QIcon(pixmap)
            cmbPreviewPalette.addItem(icon, name)
            
        # 2. QGIS Native Ramps
        cmbPreviewPalette.addItem("QGIS Color Ramps")
        idx = cmbPreviewPalette.count() - 1
        item = model.item(idx)
        if item:
            item.setEnabled(False)
            if hasattr(Qt, 'ItemFlag'):
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                item.setFlags(Qt.NoItemFlags)
        
        style = QgsStyle.defaultStyle()
        for ramp_name in style.colorRampNames():
            if ramp_name in custom_palettes:
                continue
                
            ramp = style.colorRamp(ramp_name)
            if isinstance(ramp, QgsGradientColorRamp):
                pixmap = QgsSymbolLayerUtils.colorRampPreviewPixmap(ramp, QSize(80, 14))
                if not pixmap.isNull():
                    cmbPreviewPalette.addItem(QIcon(pixmap), ramp_name)
