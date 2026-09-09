"""
Pixel Inspector Dialog Module.
Provides a modern, stays-on-top analytical tool panel that displays comprehensive
spectral inspection results in real time as the user clicks across the QGIS map canvas.
"""
from typing import Dict, Any, Optional

try:
    from PyQt6.QtCore import Qt, pyqtSignal
    from PyQt6.QtGui import QFont, QColor
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
        QPushButton, QFrame, QWidget, QApplication
    )
except ImportError:
    from qgis.PyQt.QtCore import Qt, pyqtSignal
    from qgis.PyQt.QtGui import QFont, QColor
    from qgis.PyQt.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
        QPushButton, QFrame, QWidget, QApplication
    )

class PixelInspectorDialog(QDialog):
    """
    Non-modal floating tool panel displaying real-time inspection diagnostics:
    - Map Coordinates (X / Y) & Geographic Coordinates (Latitude / Longitude)
    - Calculated Spectral Index Value or Original Spectral Bands
    - Classification & Decision Threshold
    - Mathematical Threshold Difference (Delta)
    - Precise Metric Pixel Resolution & Layer CRS
    """

    inspector_closed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Spectral Pixel Inspector Diagnostics")
        
        # Enforce PyQt6 window types: stays on top without blocking canvas interactions
        self.setWindowFlags(
            Qt.WindowType.Tool | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(420, 440)
        self.setStyleSheet("""
            QDialog {
                background-color: #12243B;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #D7E3F4;
            }
            QFrame#cardFrame {
                background-color: #12243B;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
            }
            QPushButton {
                background-color: #1E3A5F;
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                padding: 6px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #27D8F7;
                color: #0C1B30;
            }
        """)
        
        self.setup_ui()

    def setup_ui(self) -> None:
        """Constructs the structured grid layout for scientific parameter observation."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header section
        self.lbl_title = QLabel("<b>Pixel Inspection Live Monitor</b>")
        self.lbl_title.setStyleSheet("font-size: 13pt; color: #FFFFFF;")
        main_layout.addWidget(self.lbl_title)
        
        self.lbl_subtitle = QLabel("Click anywhere on the QGIS canvas to inspect pixels.")
        self.lbl_subtitle.setStyleSheet("font-size: 9.5pt; color: #B8C6D8; margin-bottom: 4px;")
        main_layout.addWidget(self.lbl_subtitle)

        # Primary observation box (Index Value + Classification Badge)
        self.card_frame = QFrame()
        self.card_frame.setObjectName("cardFrame")
        card_layout = QVBoxLayout(self.card_frame)
        card_layout.setContentsMargins(12, 12, 12, 12)
        
        self.lbl_index_val = QLabel("Index Value: --")
        self.lbl_index_val.setStyleSheet("font-size: 15pt; font-weight: 700; color: #27D8F7;")
        card_layout.addWidget(self.lbl_index_val)
        
        self.lbl_class_badge = QLabel("Classification: --")
        self.lbl_class_badge.setStyleSheet("font-size: 11pt; font-weight: 600; color: #D7E3F4; margin-top: 4px;")
        card_layout.addWidget(self.lbl_class_badge)
        
        main_layout.addWidget(self.card_frame)

        # Parameter details table matrix
        grid_frame = QFrame()
        grid_frame.setStyleSheet("background-color: #12243B; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 4px;")
        grid_layout = QGridLayout(grid_frame)
        grid_layout.setContentsMargins(10, 10, 10, 10)
        grid_layout.setHorizontalSpacing(12)
        grid_layout.setVerticalSpacing(8)

        # Helpers for consistent table cell formatting
        def make_header_label(text: str) -> QLabel:
            lbl = QLabel(f"<b>{text}:</b>")
            lbl.setStyleSheet("color: #D7E3F4; font-size: 9.5pt;")
            return lbl

        def make_value_label() -> QLabel:
            lbl = QLabel("--")
            lbl.setStyleSheet("color: #FFFFFF; font-size: 9.5pt; font-family: 'Consolas', monospace;")
            lbl.setWordWrap(True)
            return lbl

        self.hdr_map_coords = make_header_label("Map Coordinates")
        self.hdr_lat_lon = make_header_label("Geographic Coordinates")
        self.hdr_bands = make_header_label("Spectral Index Value")
        self.hdr_threshold = make_header_label("Decision Threshold")
        self.hdr_delta = make_header_label("Threshold Delta (Δ)")
        self.hdr_resolution = make_header_label("Pixel Resolution")
        self.hdr_crs = make_header_label("Layer CRS")

        self.val_map_coords = make_value_label()
        self.val_lat_lon = make_value_label()
        self.val_bands = make_value_label()
        self.val_threshold = make_value_label()
        self.val_delta = make_value_label()
        self.val_resolution = make_value_label()
        self.val_crs = make_value_label()

        grid_layout.addWidget(self.hdr_map_coords, 0, 0)
        grid_layout.addWidget(self.val_map_coords, 0, 1)

        grid_layout.addWidget(self.hdr_lat_lon, 1, 0)
        grid_layout.addWidget(self.val_lat_lon, 1, 1)

        grid_layout.addWidget(self.hdr_bands, 2, 0)
        grid_layout.addWidget(self.val_bands, 2, 1)

        grid_layout.addWidget(self.hdr_threshold, 3, 0)
        grid_layout.addWidget(self.val_threshold, 3, 1)

        grid_layout.addWidget(self.hdr_delta, 4, 0)
        grid_layout.addWidget(self.val_delta, 4, 1)

        grid_layout.addWidget(self.hdr_resolution, 5, 0)
        grid_layout.addWidget(self.val_resolution, 5, 1)

        grid_layout.addWidget(self.hdr_crs, 6, 0)
        grid_layout.addWidget(self.val_crs, 6, 1)

        grid_layout.setColumnStretch(1, 1)
        main_layout.addWidget(grid_frame)

        main_layout.addStretch()

        # Action bar
        btn_layout = QHBoxLayout()
        self.btn_copy = QPushButton("Copy Diagnostic JSON")
        self.btn_copy.clicked.connect(self.copy_to_clipboard)
        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet("background-color: #1E3A5F; color: #D7E3F4; border: 1px solid rgba(255, 255, 255, 0.1);")
        self.btn_close.clicked.connect(self._on_close_clicked)
        
        btn_layout.addWidget(self.btn_copy)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        main_layout.addLayout(btn_layout)

        self._current_data_cache: Dict[str, Any] = {}

    def update_inspection_data(
        self,
        inspection_data: Dict[str, Any],
        threshold: float,
        positive_meaning: str,
        negative_meaning: str,
        formula_name: Optional[str] = None,
        satellite: Optional[str] = None,
        resolution_meta: Optional[str] = None
    ) -> None:
        """
        Populates the analytical tool panel with newly captured pixel telemetry and classification evaluations.
        """
        self._current_data_cache = {
            "inspection": inspection_data,
            "threshold": threshold,
            "positive_class": positive_meaning,
            "negative_class": negative_meaning,
            "formula": formula_name,
            "satellite": satellite
        }

        layer_lbl = inspection_data.get('layer_name', 'Raster Layer')
        title_str = f"<b>{formula_name or layer_lbl}</b> Inspection Monitor"
        self.lbl_title.setText(title_str)
        self.lbl_subtitle.setText(f"Targeting active matrix: <i>{layer_lbl}</i>")

        val = float(inspection_data.get('value', 0.0))
        self.lbl_index_val.setText(f"Index Value: {val:.4f}")

        # Classification assessment
        if val >= threshold:
            class_str = f"Classification: {positive_meaning} (≥ T)"
            self.lbl_class_badge.setStyleSheet("font-size: 11pt; font-weight: 700; color: #047857;") # Emerald Green
        else:
            class_str = f"Classification: {negative_meaning} (< T)"
            self.lbl_class_badge.setStyleSheet("font-size: 11pt; font-weight: 700; color: #B45309;") # Amber/Orange

        self.lbl_class_badge.setText(class_str)

        # 1. Map coordinates (Strict X / Y formatting)
        x, y = float(inspection_data.get('x', 0.0)), float(inspection_data.get('y', 0.0))
        self.val_map_coords.setText(f"X: {x:.2f} | Y: {y:.2f}")

        # 2. Geographic Coordinates (Strict Latitude / Longitude formatting with Lat before Lon)
        lat, lon = float(inspection_data.get('lat', 0.0)), float(inspection_data.get('lon', 0.0))
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "E" if lon >= 0 else "W"
        self.val_lat_lon.setText(f"Latitude: {abs(lat):.4f}° {lat_dir} | Longitude: {abs(lon):.4f}° {lon_dir}")

        # 3. Spectral Index vs Original Spectral Bands formatting
        bands = inspection_data.get('bands', {})
        if len(bands) <= 1:
            idx_name = formula_name or "Spectral Index"
            self.hdr_bands.setText(f"<b>{idx_name} Value:</b>")
            self.val_bands.setText(f"{val:.4f} ({idx_name})")
        else:
            self.hdr_bands.setText("<b>Original Spectral Bands:</b>")
            band_str = " | ".join([f"Band {k}: {v:.4f}" for k, v in sorted(bands.items())])
            self.val_bands.setText(band_str)

        # 4. Decision threshold and delta
        self.val_threshold.setText(f"{threshold:.4f}")
        delta = val - threshold
        if delta >= 0:
            self.val_delta.setText(f"+{delta:.4f} (Above Threshold)")
            self.val_delta.setStyleSheet("color: #047857; font-size: 9.5pt; font-weight: 700;")
        else:
            self.val_delta.setText(f"{delta:.4f} (Below Threshold)")
            self.val_delta.setStyleSheet("color: #E11D48; font-size: 9.5pt; font-weight: 700;")

        # 5. Precise Metric Pixel Resolution (resolves 0.00x0.00 degree issues & integrates satellite mission specs)
        px_x = float(inspection_data.get('pixel_size_x', 0.0))
        px_y = float(inspection_data.get('pixel_size_y', 0.0))
        px_meters_x = float(inspection_data.get('pixel_meters_x', px_x))
        px_meters_y = float(inspection_data.get('pixel_meters_y', px_y))
        is_geo = inspection_data.get('is_geographic', False)
        
        sat_suffix = f" ({satellite})" if satellite and str(satellite) != 'None' else ""
        if resolution_meta and str(resolution_meta) != '0' and str(resolution_meta) != 'None':
            res_str = f"{float(resolution_meta):.0f} × {float(resolution_meta):.0f} m{sat_suffix}"
            if is_geo and px_x > 0:
                res_str += f" [{px_x:.6f}° × {px_y:.6f}°]"
        elif px_meters_x > 0 and px_meters_y > 0:
            if is_geo:
                res_str = f"~{px_meters_x:.1f} × {px_meters_y:.1f} m [{px_x:.6f}° × {px_y:.6f}°]{sat_suffix}"
            else:
                res_str = f"{px_x:.2f} × {px_y:.2f} m{sat_suffix}"
        else:
            res_str = f"Native Sensor Resolution{sat_suffix}"
        self.val_resolution.setText(res_str)

        # 6. Layer CRS
        crs_id = inspection_data.get('crs_authid', 'N/A')
        crs_desc = inspection_data.get('crs_desc', '')
        self.val_crs.setText(f"{crs_id} ({crs_desc})")

        if not self.isVisible():
            self.show()
        self.raise_()

    def copy_to_clipboard(self) -> None:
        """Copies the observed diagnostics to system clipboard in JSON format."""
        import json
        try:
            clipboard = QApplication.clipboard()
            text = json.dumps(self._current_data_cache, indent=2, default=str)
            if clipboard:
                clipboard.setText(text)
        except Exception:
            pass

    def _on_close_clicked(self) -> None:
        """Handles Close button click to hide dialog without disrupting active map inspection tools."""
        self.hide()

    def closeEvent(self, event: Any) -> None:
        """Captures window close attempts (titlebar X button) to hide dialog without terminating inspection session."""
        self.hide()
        if hasattr(event, "accept"):
            event.accept()

    def reject(self) -> None:
        """Handles dialog rejection (closing or dismissing) without terminating inspection session."""
        self.hide()
        super().reject()

    def keyPressEvent(self, event: Any) -> None:
        """Captures ESC key presses directly on dialog components to terminate the inspection session."""
        if hasattr(event, "key") and event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.inspector_closed.emit()
            if hasattr(event, "accept"):
                event.accept()
        else:
            super().keyPressEvent(event)
