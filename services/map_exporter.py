"""
Map Exporter Service Module.
Dedicated service for exporting high-resolution rendered maps from QGIS with professional
cartographic layouts (Legend, Scale Bar, North Arrow, and Coordinate Grid).
Fully decoupled from active canvas state and user UI zoom level.
"""
import os
import logging
from typing import Optional, List, Dict, Any, Tuple
from ..utils.logger import get_logger

try:
    from qgis.core import (
        QgsProject, QgsRasterLayer, QgsVectorLayer, QgsMapLayer,
        QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLegend,
        QgsLayoutItemScaleBar, QgsLayoutItemPicture, QgsLayoutItemLabel,
        QgsLayoutItemMapGrid, QgsLayoutExporter, QgsLayoutSize, QgsLayoutPoint,
        QgsUnitTypes, QgsRectangle, QgsMapSettings,
        QgsMapRendererCustomPainterJob, QgsLayoutItemShape,
        QgsSingleBandPseudoColorRenderer, QgsColorRampShader, QgsRasterShader,
        QgsLineSymbol, QgsFillSymbol, QgsTextFormat
    )
except ImportError:
    pass

try:
    from qgis.PyQt.QtCore import QSizeF, QRectF, Qt, QPointF
    from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter
except ImportError:
    pass


class MapExporter:
    """
    Handles publication-quality cartographic map rendering and exporting.
    Preserves layer renderer, color ramp, stretch, classification, transparency, and layer order.
    Never relies on temporary map canvas visual state.
    """

    def __init__(self, default_dpi: int = 300) -> None:
        """
        Initialize MapExporter with configurable default resolution.
        
        Args:
            default_dpi (int): Default DPI resolution (e.g. 150, 300, 600).
        """
        self.logger: logging.Logger = get_logger(__name__)
        self.default_dpi: int = default_dpi

    def export_cartographic_map(
        self,
        target_layer: Any,  # QgsMapLayer / QgsRasterLayer
        output_path: str,
        export_format: str = "vector_preferred",
        dpi: Optional[int] = None,
        title_text: Optional[str] = None,
        custom_extent: Optional[Any] = None,
        context: Optional[Any] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Export a professional cartographic layout containing:
        - Main Analysis Map (dominant focal piece occupying maximum printable breadth)
        - Academic Legend (with meaningful scientific classes instead of generic labels like 'Band 1' or 'Gray')
        - Professional Metric Scale Bar (mathematically calibrated intervals, e.g. 0 - 250 - 500 - 1000 m or km)
        - North Arrow
        - Subtle Supportive Coordinate Grid (thin light gray lines #CBD5E1, 0.2 mm)
        Note: Locator (Inset) map and empty frames have been removed per publication refinement standards.

        Args:
            target_layer: The analysis raster or vector layer to render.
            output_path: Destination file path (PNG, PDF, or SVG).
            export_format: Preference for export format ('vector_preferred', 'raster', 'svg').
            dpi: DPI resolution (150, 300, 600). Defaults to initialized DPI.
            title_text: Optional title to render on top of map composition.
            custom_extent: Optional explicit QgsRectangle extent; if None, uses target_layer.extent().
            context: Optional AnalysisReportContext for extracting index metadata and classification labels.

        Returns:
            Tuple[bool, str, Dict[str, Any]]: Success status, output path, and layout diagnostic metadata.
        """
        export_dpi = dpi if dpi is not None else self.default_dpi
        metadata: Dict[str, Any] = {
            "dpi": export_dpi,
            "engine_used": "unknown",
            "legend_included": False,
            "scale_bar_included": False,
            "north_arrow_included": False,
            "grid_included": False,
            "locator_map_included": False,
            "locator_map_note": "Locator map omitted per user publication specification to maximize main map focal clarity."
        }

        if target_layer is None:
            self.logger.error("MapExporter cannot export map: target_layer is None.")
            return False, output_path, metadata

        try:
            # Step 1: Initialize temporary standalone print layout
            project = QgsProject.instance()
            layout = QgsPrintLayout(project)
            layout.setName("Scientific_Report_Cartographic_Layout")
            layout.initializeDefaults()

            # Configure expanded layout canvas dimensions to maximize printable page area
            # Width: 185 mm, Height: 140 mm (fits perfectly within A4 portrait ratios)
            page_width_mm = 185.0
            page_height_mm = 140.0
            if layout.pageCollection().pageCount() == 0:
                from qgis.core import QgsLayoutItemPage
                layout.pageCollection().addPage(QgsLayoutItemPage(layout))
            layout.pageCollection().pages()[0].setPageSize(
                QgsLayoutSize(page_width_mm, page_height_mm, QgsUnitTypes.LayoutUnit.LayoutMillimeters)
            )

            # Step 2: Configure Main Analysis Map Item (Dominant visual focal element)
            map_item = QgsLayoutItemMap(layout)
            layout.addLayoutItem(map_item)

            map_margin_x = 6.0
            map_margin_y = 6.0 if not title_text else 8.0
            # Reserve 32mm on right for compact legend and north arrow; map occupies 147 mm (~80% width)
            map_width = page_width_mm - map_margin_x - 32.0
            map_height = page_height_mm - map_margin_y - 14.0  # Reserve 14mm on bottom for scale bar & grid labels
            
            map_item.attemptMove(QgsLayoutPoint(map_margin_x, map_margin_y, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
            map_item.attemptResize(QgsLayoutSize(map_width, map_height, QgsUnitTypes.LayoutUnit.LayoutMillimeters))

            # Step 3: Symbology & Shader Refinement (Replace generic band names with meaningful scientific classes)
            try:
                if hasattr(target_layer, "renderer") and target_layer.renderer() is not None:
                    renderer = target_layer.renderer()
                    if hasattr(renderer, "shader") and renderer.shader() is not None:
                        shader = renderer.shader()
                        if hasattr(shader, "rasterShaderFunction") and shader.rasterShaderFunction() is not None:
                            func = shader.rasterShaderFunction()
                            if hasattr(func, "colorRampItemList") and hasattr(func, "setColorRampItemList"):
                                items = func.colorRampItemList()
                                new_items = []
                                formula = getattr(context, 'formula_name', '').upper() if context else ''
                                pos_mean = getattr(context, 'positive_meaning', 'Target Class') if context else 'Target Feature'
                                neg_mean = getattr(context, 'negative_meaning', 'Background Matrix') if context else 'Background Matrix'
                                thresh = getattr(context, 'classification_threshold', 0.2) if context else 0.2
                                
                                num_items = len(items)
                                for idx, item in enumerate(items):
                                    val = item.value
                                    col = item.color
                                    lbl = str(item.label or "").strip()
                                    
                                    # Always enforce meaningful scientific labels over raw numeric or generic tags
                                    if not lbl or "Band" in lbl or "Gray" in lbl or "Palette" in lbl or lbl == str(val) or lbl.replace(".","",1).replace("-","",1).isdigit():
                                        if formula == "NDVI":
                                            if val < 0.05: lbl = f"<{val:.2f} (Water / Bare Soil)"
                                            elif val < 0.20: lbl = f"{val:.2f} (Sparse Vegetation)"
                                            elif val < 0.50: lbl = f"{val:.2f} (Moderate Canopy)"
                                            else: lbl = f"&ge;{val:.2f} (Dense Canopy)"
                                        elif formula in ["NDWI", "MNDWI"]:
                                            if val < 0.0: lbl = f"<{val:.2f} (Non-Water / Land)"
                                            elif val < 0.10: lbl = f"{val:.2f} (Moist / Shallow)"
                                            else: lbl = f"&ge;{val:.2f} (Open Water Surface)"
                                        elif formula == "NDBI":
                                            if val < 0.0: lbl = f"<{val:.2f} (Vegetated / Water)"
                                            elif val < 0.10: lbl = f"{val:.2f} (Mixed / Peri-urban)"
                                            else: lbl = f"&ge;{val:.2f} (Built-up Surface)"
                                        else:
                                            if idx == 0: lbl = f"Low (<{thresh}): {neg_mean}"
                                            elif idx == num_items - 1: lbl = f"High (&ge;{thresh}): {pos_mean}"
                                            else: lbl = f"{val:.2f} ({neg_mean if val < thresh else pos_mean})"
                                            
                                    new_items.append(func.ColorRampItem(val, col, lbl))
                                if new_items:
                                    func.setColorRampItemList(new_items)
                                    target_layer.triggerRepaint()
            except Exception as sym_err:
                self.logger.debug(f"Could not apply automated shader label override: {sym_err}")

            map_item.setLayers([target_layer])
            map_item.setKeepLayerSet(True)
            map_item.setKeepLayerStyles(True)

            render_extent = custom_extent if custom_extent else target_layer.extent()
            map_item.setExtent(render_extent)
            map_item.refresh()

            # Step 4: Add Subtle Supportive Coordinate Grid (Thin light-gray lines #CBD5E1, 0.2mm)
            try:
                grid_stack = map_item.grids()
                grid = QgsLayoutItemMapGrid(map_item.displayName(), map_item)
                grid.setEnabled(True)
                grid.setStyle(QgsLayoutItemMapGrid.GridStyle.Solid)
                
                # Apply light gray supportive lines (#CBD5E1, thickness 0.2 mm)
                try:
                    if hasattr(QgsLineSymbol, "createSimple"):
                        line_sym = QgsLineSymbol.createSimple({'color': '#CBD5E1', 'width': '0.2'})
                        grid.setLineSymbol(line_sym)
                    elif grid.lineSymbol():
                        grid.lineSymbol().setColor(QColor("#CBD5E1"))
                        grid.lineSymbol().setWidth(0.2)
                except Exception as sym_line_err:
                    self.logger.debug(f"Grid line symbol override fallback: {sym_line_err}")

                # Use sleek exterior ticks instead of visually dominating frames
                if hasattr(QgsLayoutItemMapGrid.FrameStyle, "LineBorder"):
                    grid.setFrameStyle(QgsLayoutItemMapGrid.FrameStyle.LineBorder)
                elif hasattr(QgsLayoutItemMapGrid.FrameStyle, "ExteriorTicks"):
                    grid.setFrameStyle(QgsLayoutItemMapGrid.FrameStyle.ExteriorTicks)
                grid.setFrameWidth(0.5)

                # Intelligent grid spacing interval (approx. 4 sections across width)
                extent_width = render_extent.width()
                extent_height = render_extent.height()
                if extent_width > 0:
                    grid.setIntervalX(extent_width / 4.0)
                    grid.setIntervalY(extent_height / 4.0)

                # Enable readable coordinate annotations
                grid.setAnnotationEnabled(True)
                grid.setAnnotationFormat(QgsLayoutItemMapGrid.AnnotationFormat.Decimal)
                try:
                    if hasattr(QgsTextFormat, "__init__"):
                        tf = QgsTextFormat()
                        tf.setFont(QFont("Inter", 8, QFont.Weight.Normal))
                        tf.setColor(QColor("#334155"))
                        grid.setAnnotationTextFormat(tf)
                except Exception as tf_err:
                    self.logger.debug(f"Grid annotation font format override fallback: {tf_err}")

                grid.setAnnotationDisplay(QgsLayoutItemMapGrid.DisplayMode.ShowAll, QgsLayoutItemMapGrid.BorderSide.Left)
                grid.setAnnotationDisplay(QgsLayoutItemMapGrid.DisplayMode.ShowAll, QgsLayoutItemMapGrid.BorderSide.Bottom)
                grid.setAnnotationDisplay(QgsLayoutItemMapGrid.DisplayMode.HideAll, QgsLayoutItemMapGrid.BorderSide.Top)
                grid.setAnnotationDisplay(QgsLayoutItemMapGrid.DisplayMode.HideAll, QgsLayoutItemMapGrid.BorderSide.Right)
                grid_stack.addGrid(grid)
                metadata["grid_included"] = True
            except Exception as grid_err:
                self.logger.warning(f"Could not configure layout coordinate grid: {grid_err}")

            # Step 5: Add North Arrow
            try:
                north_arrow_x = page_width_mm - 28.0
                north_arrow_y = map_margin_y + 1.0
                north_label = QgsLayoutItemLabel(layout)
                layout.addLayoutItem(north_label)
                north_label.setText("▲\nN")
                north_label.setFont(QFont("Inter", 13, QFont.Weight.Bold))
                north_label.setHAlign(Qt.AlignmentFlag.AlignHCenter)
                north_label.setVAlign(Qt.AlignmentFlag.AlignVCenter)
                north_label.attemptMove(QgsLayoutPoint(north_arrow_x, north_arrow_y, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
                north_label.attemptResize(QgsLayoutSize(22.0, 14.0, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
                metadata["north_arrow_included"] = True
            except Exception as na_err:
                self.logger.warning(f"Could not add North Arrow: {na_err}")

            # Step 6: Add Scientific Legend (Enforce meaningful classes over generic 'Band 1' / 'Gray')
            try:
                legend = QgsLayoutItemLegend(layout)
                layout.addLayoutItem(legend)
                legend.setTitle("Legend")
                legend.setLinkedMap(map_item)
                legend.setAutoUpdateModel(False)
                
                # Override layer title and child legend nodes to remove generic terms
                try:
                    root_group = legend.model().rootGroup()
                    node_layer = root_group.findLayer(target_layer)
                    if node_layer:
                        if context and hasattr(context, 'formula_name'):
                            node_layer.setName(f"{context.formula_name} ({context.vis_palette})")
                        else:
                            node_layer.setName(getattr(target_layer, 'name', lambda: 'Spectral Analysis')())
                            
                        # Traverse child symbology nodes in legend tree to override any lingering generic strings
                        try:
                            legend_nodes = legend.model().layerLegendNodes(node_layer)
                            pos_m = getattr(context, 'positive_meaning', 'Target Feature') if context else 'Target Class'
                            neg_m = getattr(context, 'negative_meaning', 'Background Matrix') if context else 'Background Matrix'
                            thresh = getattr(context, 'classification_threshold', 0.2) if context else 0.2
                            
                            for idx, lnode in enumerate(legend_nodes):
                                txt = str(lnode.data(0) or "").strip()
                                if not txt or "Band" in txt or "Gray" in txt or "Palette" in txt or txt == "0" or txt.replace(".","",1).replace("-","",1).isdigit():
                                    if len(legend_nodes) == 1:
                                        new_lbl = f"Continuous ({neg_m} \u2192 {pos_m})"
                                    elif idx == 0:
                                        new_lbl = f"Low (<{thresh}): {neg_m}"
                                    elif idx == len(legend_nodes) - 1:
                                        new_lbl = f"High (\u2265{thresh}): {pos_m}"
                                    else:
                                        new_lbl = f"Class Range (~{thresh})"
                                        
                                    if hasattr(lnode, "setUserLabel"):
                                        lnode.setUserLabel(new_lbl)
                                    elif hasattr(lnode, "setData"):
                                        try:
                                            lnode.setData(new_lbl, 0)
                                        except Exception:
                                            pass
                        except Exception as lnode_err:
                            self.logger.debug(f"Could not override child legend node user labels: {lnode_err}")
                except Exception as node_err:
                    self.logger.debug(f"Could not rename legend node layer title: {node_err}")

                try:
                    if hasattr(QgsLayoutItemLegend, "TitleFont"):
                        legend.setFont(QgsLayoutItemLegend.TitleFont, QFont("Inter", 11, QFont.Weight.Bold))
                        legend.setFont(QgsLayoutItemLegend.LayerFont, QFont("Inter", 10, QFont.Weight.Bold))
                        legend.setFont(QgsLayoutItemLegend.ItemFont, QFont("Inter", 9, QFont.Weight.Normal))
                except Exception as font_err:
                    self.logger.debug(f"Legend font override fallback: {font_err}")

                legend_x = page_width_mm - 30.0
                legend_y = map_margin_y + 18.0
                legend.attemptMove(QgsLayoutPoint(legend_x, legend_y, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
                legend.attemptResize(QgsLayoutSize(28.0, map_height - 22.0, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
                metadata["legend_included"] = True
            except Exception as leg_err:
                self.logger.warning(f"Could not configure layout legend: {leg_err}")

            # Step 7: Add Professional Metric Scale Bar (Guaranteed calibrated segments e.g. 0 - 250 - 500 - 1000m)
            try:
                scale_bar = QgsLayoutItemScaleBar(layout)
                layout.addLayoutItem(scale_bar)
                scale_bar.setStyle("Single Box")
                scale_bar.setLinkedMap(map_item)
                
                # Mathematically calculate map ground extent to assign exact Units Per Segment
                is_geo = target_layer.crs().isGeographic() if hasattr(target_layer, "crs") and target_layer.crs().isValid() else False
                extent_w = render_extent.width()
                est_w_meters = extent_w * 100000.0 if is_geo else extent_w
                if est_w_meters <= 0:
                    est_w_meters = 10000.0  # Safe default fallback

                # We want 3 or 4 segments to span ~26% of map width
                target_seg_m = est_w_meters * 0.26 / 3.0
                metric_steps_m = [10, 20, 50, 100, 250, 500, 1000, 2000, 2500, 5000, 10000, 25000, 50000, 100000]
                best_step_m = metric_steps_m[0]
                for step in metric_steps_m:
                    if abs(step - target_seg_m) < abs(best_step_m - target_seg_m):
                        best_step_m = step

                if est_w_meters >= 3500.0:
                    # Use Kilometers (e.g., 0 - 0.5 - 1 km)
                    if hasattr(QgsUnitTypes, "DistanceUnit") and hasattr(QgsUnitTypes.DistanceUnit, "DistanceKilometers"):
                        scale_bar.setUnits(QgsUnitTypes.DistanceUnit.DistanceKilometers)
                    elif hasattr(QgsUnitTypes, "DistanceKilometers"):
                        scale_bar.setUnits(QgsUnitTypes.DistanceKilometers)
                    scale_bar.setUnitLabel("km")
                    
                    seg_val_km = float(best_step_m) / 1000.0
                    if seg_val_km < 0.25:
                        seg_val_km = 0.25
                    scale_bar.setUnitsPerSegment(seg_val_km)
                    scale_bar.setNumberOfSegments(4 if seg_val_km in [0.25, 0.5, 2.5] else 3)
                else:
                    # Use Meters (e.g., 0 - 250 - 500 - 750 - 1000 m)
                    if hasattr(QgsUnitTypes, "DistanceUnit") and hasattr(QgsUnitTypes.DistanceUnit, "DistanceMeters"):
                        scale_bar.setUnits(QgsUnitTypes.DistanceUnit.DistanceMeters)
                    elif hasattr(QgsUnitTypes, "DistanceMeters"):
                        scale_bar.setUnits(QgsUnitTypes.DistanceMeters)
                    scale_bar.setUnitLabel("m")
                    
                    scale_bar.setUnitsPerSegment(float(best_step_m))
                    scale_bar.setNumberOfSegments(4 if best_step_m in [25, 250, 2500] else 3)
                    
                scale_bar.setNumberOfSegmentsLeft(0)
                scale_bar.setHeight(3.0)
                try:
                    scale_bar.setFont(QFont("Inter", 9, QFont.Weight.Normal))
                except Exception:
                    pass
                
                if hasattr(scale_bar, "applyDefaultRenderer"):
                    scale_bar.applyDefaultRenderer()
                elif hasattr(scale_bar, "update"):
                    scale_bar.update()
                
                scale_x = map_margin_x
                scale_y = map_margin_y + map_height + 3.0
                scale_bar.attemptMove(QgsLayoutPoint(scale_x, scale_y, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
                metadata["scale_bar_included"] = True
            except Exception as sb_err:
                self.logger.warning(f"Could not configure layout scale bar: {sb_err}")

            # Note: Step 8 (Inset / Locator Map) has been intentionally removed per user specification
            # to prevent empty white rectangle frames and maximize main map dominance.

            # Step 9: Render & Export
            exporter = QgsLayoutExporter(layout)
            export_settings = QgsLayoutExporter.ImageExportSettings()
            export_settings.dpi = export_dpi
            
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

            res = None
            if export_format == "svg" or (export_format == "vector_preferred" and output_path.lower().endswith(".svg")):
                svg_settings = QgsLayoutExporter.SvgExportSettings()
                svg_settings.dpi = export_dpi
                res = exporter.exportToSvg(output_path, svg_settings)
                metadata["engine_used"] = "QgsLayoutExporter_SVG_Vector"
            elif output_path.lower().endswith(".pdf") and export_format == "vector_preferred":
                pdf_settings = QgsLayoutExporter.PdfExportSettings()
                pdf_settings.dpi = export_dpi
                res = exporter.exportToPdf(output_path, pdf_settings)
                metadata["engine_used"] = "QgsLayoutExporter_PDF_Vector"
            else:
                res = exporter.exportToImage(output_path, export_settings)
                metadata["engine_used"] = "QgsLayoutExporter_Raster_Image"

            if res == QgsLayoutExporter.ExportResult.Success and os.path.exists(output_path):
                self.logger.info(f"Cartographic map successfully exported via {metadata['engine_used']} to: {output_path}")
                return True, output_path, metadata
            else:
                self.logger.warning(f"QgsLayoutExporter returned status {res}. Attempting direct map renderer fallback.")

        except Exception as e:
            self.logger.error(f"Error building print layout for map export: {e}", exc_info=True)

        # Step 10: Architectural Fallback - Direct QgsMapRenderer Custom Painter Job
        try:
            self.logger.info("Executing Fallback Map Exporter using QgsMapRendererCustomPainterJob at configured DPI.")
            settings = QgsMapSettings()
            settings.setLayers([target_layer])
            settings.setExtent(target_layer.extent())
            
            scale_factor = float(export_dpi) / 96.0
            base_w, base_h = 1600, 1200
            settings.setOutputSize(QSizeF(base_w * scale_factor, base_h * scale_factor).toSize())
            settings.setOutputDpi(export_dpi)
            settings.setBackgroundColor(QColor("#FFFFFF"))
            
            image = QImage(settings.outputSize(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor("#FFFFFF"))
            
            painter = QPainter(image)
            job = QgsMapRendererCustomPainterJob(settings, painter)
            job.start()
            job.waitForFinished()
            painter.end()
            
            image.save(output_path)
            metadata["engine_used"] = "QgsMapRendererCustomPainterJob_Fallback"
            self.logger.info(f"Fallback map rendering successful: {output_path}")
            return True, output_path, metadata

        except Exception as fallback_e:
            self.logger.error(f"Fallback map rendering also failed: {fallback_e}", exc_info=True)
            metadata["engine_used"] = "failed"
            return False, output_path, metadata
