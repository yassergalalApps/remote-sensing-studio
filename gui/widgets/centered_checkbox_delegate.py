from qgis.PyQt import QtCore
from qgis.PyQt.QtWidgets import QStyledItemDelegate, QApplication, QStyle
from qgis.PyQt.QtGui import QPainter, QColor, QPen, QPainterPath
from qgis.PyQt.QtCore import Qt, QRect

class CenteredCheckboxDelegate(QStyledItemDelegate):
    """
    A custom item delegate that renders a centered, modern checkbox
    for use in QTableView/QTableWidget columns.
    It completely replaces the native checkbox drawing with a custom
    green/turquoise styled checkbox.
    """
    def paint(self, painter, option, index):
        painter.save()
        
        # 1. Draw the native selection background so row highlighting still works
        self.initStyleOption(option, index)
        widget = option.widget
        style = widget.style() if widget else QApplication.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, widget)
        
        # 2. Extract check state
        check_state = index.data(Qt.ItemDataRole.CheckStateRole)
        # If this item doesn't have a check state, don't draw our custom checkbox
        if check_state is None:
            painter.restore()
            return
            
        checked = False
        if isinstance(check_state, int):
            checked = (check_state == 2) # 2 is Qt.CheckState.Checked
        else:
            checked = (check_state == Qt.CheckState.Checked)
        
        # 3. Calculate centered bounding box
        box_size = 18
        rect = option.rect
        x = rect.x() + (rect.width() - box_size) // 2
        y = rect.y() + (rect.height() - box_size) // 2
        box_rect = QRect(x, y, box_size, box_size)
        
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Check hover state
        is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        checked_color = QColor("#14C8A0") if is_hovered else QColor("#10B981")
        unchecked_color = QColor("#27D8F7") if is_hovered else QColor("#5A7494")
        
        # 4. Draw the checkbox
        if checked:
            painter.setBrush(checked_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(box_rect, 4, 4)
            
            # Draw a white checkmark
            painter.setPen(QPen(QColor("#FFFFFF"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            path = QPainterPath()
            path.moveTo(x + 4, y + box_size // 2)
            path.lineTo(x + 8, y + box_size - 5)
            path.lineTo(x + box_size - 4, y + 5)
            painter.drawPath(path)
        else:
            # Unchecked: explicit empty square with a subtle border
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(unchecked_color, 2))
            painter.drawRoundedRect(box_rect, 4, 4)
            
        painter.restore()
        
    def editorEvent(self, event, model, option, index):
        # Handle cell clicks to toggle the checkbox
        if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                check_state = index.data(Qt.ItemDataRole.CheckStateRole)
                if check_state is not None:
                    is_checked = (check_state == 2) if isinstance(check_state, int) else (check_state == Qt.CheckState.Checked)
                    new_state = Qt.CheckState.Unchecked if is_checked else Qt.CheckState.Checked
                    model.setData(index, new_state, Qt.ItemDataRole.CheckStateRole)
                    return True
        return super().editorEvent(event, model, option, index)
