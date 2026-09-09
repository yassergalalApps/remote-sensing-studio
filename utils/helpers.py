"""
General Helper Functions Module.
"""

import json

try:
    from qgis.core import (
        QgsGeometry, 
        QgsCoordinateReferenceSystem, 
        QgsCoordinateTransform, 
        QgsProject,
        QgsVectorLayer,
        QgsWkbTypes
    )
except ImportError:
    pass

def get_current_layer(iface):
    """Get the currently selected layer in QGIS."""
    return iface.activeLayer() if iface else None

def normalize_and_validate_geometry(geom, source_crs):
    """
    Transforms any geometry to EPSG:4326, validates it, and returns normalized metrics.
    Raises ValueError if geometry is invalid or not a polygon.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        from qgis.core import QgsWkbTypes
        logger.info("==================================================")
        logger.info("[DIAGNOSTIC]")
        logger.info("==================================================")
        logger.info(f"[DIAGNOSTIC] AOI CRS: {source_crs.authid() if source_crs else 'Unknown'}")
        
        type_str = "Unknown"
        if geom:
            if hasattr(geom, 'wkbType'):
                type_str = QgsWkbTypes.displayString(geom.wkbType())
            elif hasattr(geom, 'type'):
                type_str = str(geom.type())
                
        logger.info(f"[DIAGNOSTIC] AOI Geometry Type: {type_str}")
        logger.info(f"[DIAGNOSTIC] AOI Bounds: {geom.boundingBox().toString() if geom else 'None'}")
        logger.info(f"[DIAGNOSTIC] AOI Area: {geom.area() if geom else 0}")
        
        v_count = 0
        if geom:
            if hasattr(geom, 'vertexCount') and callable(getattr(geom, 'vertexCount')):
                v_count = geom.vertexCount()
            elif hasattr(geom, 'asWkb'):
                v_count = len(geom.asWkb()) // 16  # Rough approximation, just avoiding errors
        logger.info(f"[DIAGNOSTIC] AOI Vertex Count: {v_count}")
        
        has_z = QgsWkbTypes.hasZ(geom.wkbType()) if geom and hasattr(geom, 'wkbType') else False
        logger.info(f"[DIAGNOSTIC] Whether geometry has Z: {has_z}")
        
        is_valid = False
        if geom and hasattr(geom, 'isGeosValid'):
            is_valid = geom.isGeosValid()
        logger.info(f"[DIAGNOSTIC] Whether geometry is valid: {is_valid}")
    except Exception as diag_e:
        logger.error(f"[DIAGNOSTIC] Failed to log AOI diagnostics: {diag_e}")

    if not geom or geom.isEmpty():
        raise ValueError("Geometry is empty.")
        
    if not geom.isGeosValid():
        geom = geom.makeValid()
        if not geom.isGeosValid():
            raise ValueError("Geometry is invalid and could not be repaired by QGIS.")
            
    # We no longer strictly reject non-Polygon wkbTypes here, because collectGeometry 
    # might produce a GeometryCollection. We will extract the polygons after conversion.
        
    if geom.area() <= 0:
        raise ValueError("Geometry has zero area.")
        
    # Transform to EPSG:4326
    dest_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    if source_crs != dest_crs:
        if source_crs.mapUnits() == 0:
            densify_dist = 10.0
        else:
            densify_dist = 10.0
            
        geom = geom.densifyByDistance(densify_dist)
        xform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
        geom.transform(xform)
        
    if geom.isEmpty():
        raise ValueError("Geometry became empty after projection. The area might be out of valid CRS bounds.")
        
    # Generate GeoJSON and force it to be a pure Polygon or MultiPolygon
    raw_geojson = json.loads(geom.asJson())
    
    def strip_z(coords):
        if not coords:
            return coords
        if isinstance(coords[0], (int, float)):
            return coords[:2]
        return [strip_z(c) for c in coords]

    def extract_polys(g_dict):
        t = g_dict.get("type")
        if t in ("Polygon", "MultiPolygon"):
            g_dict["coordinates"] = strip_z(g_dict.get("coordinates", []))
            return [g_dict]
        elif t == "GeometryCollection":
            res = []
            for sub in g_dict.get("geometries", []):
                res.extend(extract_polys(sub))
            return res
        elif t == "Feature":
            return extract_polys(g_dict.get("geometry", {}))
        elif t == "FeatureCollection":
            res = []
            for feat in g_dict.get("features", []):
                res.extend(extract_polys(feat))
            return res
        return []
        
    extracted = extract_polys(raw_geojson)
    if not extracted:
        raise ValueError(f"Geometry must contain at least one Polygon. Found: {raw_geojson.get('type')}")
        
    if len(extracted) == 1:
        geojson_dict = extracted[0]
    else:
        multi_coords = []
        for p in extracted:
            if p["type"] == "Polygon":
                multi_coords.append(p["coordinates"])
            elif p["type"] == "MultiPolygon":
                multi_coords.extend(p["coordinates"])
        geojson_dict = {"type": "MultiPolygon", "coordinates": multi_coords}
    
    # Ensure coordinates are actually present
    coords = geojson_dict.get("coordinates", [])
    if not coords or (isinstance(coords, list) and len(coords) > 0 and not coords[0]):
        raise ValueError("Projection failed to generate valid coordinates. Please zoom in closer to your study area.")
        
    # Recalculate properties in WGS84 (approximate degrees, but consistent for preview)
    area = geom.area()
    perimeter = geom.length()
    bbox = geom.boundingBox()
    
    return {
        "geojson": geojson_dict,
        "area_sqdeg": area,
        "perimeter_deg": perimeter,
        "bbox": [bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum()],
        "original_crs": source_crs.authid() if source_crs else "Unknown",
        "feature_count": 1 # Normalization collapses to 1 MultiPolygon or Polygon
    }

def get_map_extent_geometry(iface):
    """Returns map extent as a QgsGeometry and its CRS."""
    if not iface: return None, None
    extent = iface.mapCanvas().extent()
    return QgsGeometry.fromRect(extent), iface.mapCanvas().mapSettings().destinationCrs()

def get_active_layer_extent_geometry(iface):
    """Returns active layer extent as a QgsGeometry and its CRS."""
    layer = get_current_layer(iface)
    if not layer: raise ValueError("No active layer selected.")
    return QgsGeometry.fromRect(layer.extent()), layer.crs()

def get_selected_feature_geometry(iface):
    """Returns union of selected features on the active layer as a QgsGeometry and its CRS."""
    layer = get_current_layer(iface)
    if not layer: raise ValueError("No active layer selected.")
    features = layer.selectedFeatures()
    if not features: raise ValueError("No features selected in the active layer.")
    
    geom = QgsGeometry()
    for feat in features:
        if geom.isEmpty():
            geom = QgsGeometry(feat.geometry())
        else:
            geom = geom.combine(feat.geometry())
    return geom, layer.crs()

def get_all_features_geometry(iface):
    """Returns union of all features on the active layer as a QgsGeometry and its CRS."""
    layer = get_current_layer(iface)
    if not layer: raise ValueError("No active layer selected.")
    
    geoms = [feat.geometry() for feat in layer.getFeatures() if feat.hasGeometry()]
    if not geoms: raise ValueError("Active layer contains no valid geometries.")
        
    combined = QgsGeometry.collectGeometry(geoms)
    return combined, layer.crs()

def get_vector_file_geometry(filepath):
    """Loads a vector file into memory and returns the combined geometry and its CRS."""
    layer = QgsVectorLayer(filepath, "temp_aoi", "ogr")
    if not layer.isValid():
        raise ValueError(f"Failed to load vector file: {filepath}")
        
    # For performance on very large files, we union the geometries. 
    # CollectGeometry creates a GeometryCollection/MultiPolygon much faster than geometric union.
    geoms = [feat.geometry() for feat in layer.getFeatures() if feat.hasGeometry()]
    if not geoms:
        raise ValueError("Vector file contains no valid geometries.")
        
    combined = QgsGeometry.collectGeometry(geoms)
    return combined, layer.crs()

def apply_scrollbar_style(widget):
    """
    Surgically injects a customized QScrollBar handle style into the target widget.
    This provides a COMPLETE subcontrol definition so Qt does not reject it,
    while explicitly omitting width/height to preserve native layout footprint.
    """
    style = """
        QScrollBar:vertical {
            background: transparent;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
            background: #10B981;
            min-height: 20px;
            border-radius: 4px;
            margin: 2px;
        }
        QScrollBar::handle:vertical:hover {
            background: #14C8A0;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
            subcontrol-origin: margin;
        }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
        }
        
        QScrollBar:horizontal {
            background: transparent;
            margin: 0px;
        }
        QScrollBar::handle:horizontal {
            background: #10B981;
            min-width: 20px;
            border-radius: 4px;
            margin: 2px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #14C8A0;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
            subcontrol-origin: margin;
        }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
            background: none;
        }
    """
    try:
        current = widget.styleSheet() or ""
        widget.setStyleSheet(current + style)
    except Exception:
        pass

def apply_custom_radio_style(widgets, accent_color="#10B981", hover_color="#14C8A0"):
    """
    Surgically injects a scoped QRadioButton style into specific widgets.
    """
    if not isinstance(widgets, list):
        widgets = [widgets]
        
    style = f"""
        QRadioButton::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 10px;
            border: 2px solid #5A7494;
            background-color: transparent;
        }}
        QRadioButton::indicator:hover {{
            border: 2px solid {hover_color};
        }}
        QRadioButton::indicator:checked {{
            width: 10px;
            height: 10px;
            border: 5px solid {accent_color};
            background-color: #FFFFFF;
        }}
        QRadioButton::indicator:checked:hover {{
            border: 5px solid {hover_color};
        }}
    """
    for widget in widgets:
        if widget:
            try:
                current = widget.styleSheet() or ""
                widget.setStyleSheet(current + style)
            except Exception:
                pass

def apply_custom_checkbox_style(widgets, accent_color="#10B981", hover_color="#14C8A0"):
    """
    Surgically injects a scoped QCheckBox style into specific widgets.
    Uses data URI SVG for the checkmark to remain self-contained.
    """
    if not isinstance(widgets, list):
        widgets = [widgets]
        
    style = f"""
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 2px solid #5A7494;
            background-color: transparent;
        }}
        QCheckBox::indicator:hover {{
            border: 2px solid {hover_color};
        }}
        QCheckBox::indicator:checked {{
            border: 2px solid {accent_color};
            background-color: {accent_color};
            image: url("data:image/svg+xml;utf8,<svg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'><path d='M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z' fill='white'/></svg>");
        }}
        QCheckBox::indicator:checked:hover {{
            border: 2px solid {hover_color};
            background-color: {hover_color};
        }}
    """
    for widget in widgets:
        if widget:
            try:
                current = widget.styleSheet() or ""
                widget.setStyleSheet(current + style)
            except Exception:
                pass

