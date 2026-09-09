from PyQt6.QtWidgets import QLayout, QSizePolicy
from PyQt6.QtCore import QPoint, QRect, QSize, Qt

class FlowLayout(QLayout):
    """
    A custom layout that arranges widgets left-to-right, wrapping to the next line 
    when there isn't enough space. Ideal for responsive grid galleries.
    """
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.itemList = []

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self.itemList.append(item)

    def count(self):
        return len(self.itemList)

    def itemAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = self.doLayout(QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        preferred_width = 450
        return QSize(preferred_width, self.heightForWidth(preferred_width))

    def minimumSize(self):
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        margin_left, margin_top, margin_right, margin_bottom = self.getContentsMargins()
        
        base_min_width = size.width() + margin_left + margin_right
        preferred_width = 450
        required_height = self.heightForWidth(preferred_width)
        
        return QSize(base_min_width, required_height)

    def doLayout(self, rect, testOnly):
        x = rect.x()
        y = rect.y()
        lineHeight = 0
        spacing = self.spacing()

        for item in self.itemList:
            wid = item.widget()
            spaceX = spacing
            spaceY = spacing

            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())

        margins = self.getContentsMargins()
        final_height = y + lineHeight - rect.y() + margins[1] + margins[3]

        return final_height
