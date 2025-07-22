import sys
import math
from PIL import ImageGrab
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QInputDialog
from PyQt6.QtGui import QPainter, QPixmap, QPen, QColor, QMouseEvent, QImage, QFont
from PyQt6.QtCore import Qt, QPoint, QRect, QTimer, pyqtSignal, QSize

class ScreenshotSelector(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Capture screen
        img = ImageGrab.grab().convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        self.bg_pixmap = QPixmap.fromImage(qimg)

        self.resize(self.bg_pixmap.size())
        self.strokes = []
        self.last_point = QPoint()
        self.drawing = False
        self.selection_rect = QRect()
        self.show_rect = False

        self.showFullScreen()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drawing = True
            self.strokes = []
            self.last_point = event.position().toPoint()
            self.strokes.append(self.last_point)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.drawing:
            pt = event.position().toPoint()
            self.strokes.append(pt)
            self.last_point = pt
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False
            self.computeBoundingRect()
            self.show_rect = True
            self.update()
            QTimer.singleShot(1000, self.saveSelectionAndEdit)

    def computeBoundingRect(self):
        if not self.strokes:
            return
        min_x = min(p.x() for p in self.strokes)
        min_y = min(p.y() for p in self.strokes)
        max_x = max(p.x() for p in self.strokes)
        max_y = max(p.y() for p in self.strokes)
        self.selection_rect = QRect(QPoint(min_x, min_y), QPoint(max_x, max_y)).normalized()

    def saveSelectionAndEdit(self):
        self.editor = AnnotationEditor(self.bg_pixmap.copy(self.selection_rect))
        self.editor.confirmed.connect(self.save_final_image)
        self.editor.redo_requested.connect(self.restart_selection)
        self.editor.show()
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def save_final_image(self, image: QImage):
        image.save("selection_edited.png")
        self.close()

    def restart_selection(self):
        self.editor.close()
        self.showFullScreen()  # Reactivate selection

    def paintEvent(self, event):
        painter = QPainter(self)

        # Dark overlay
        overlay = QPixmap(self.bg_pixmap.size())
        overlay.fill(Qt.GlobalColor.transparent)
        p = QPainter(overlay)
        p.fillRect(overlay.rect(), QColor(0, 0, 0, 128))  # 50% opacity
        p.end()

        painter.drawPixmap(0, 0, self.bg_pixmap)
        painter.drawPixmap(0, 0, overlay)

        # Reveal selection rect
        if self.show_rect and self.selection_rect.isValid():
            cropped = self.bg_pixmap.copy(self.selection_rect)
            painter.drawPixmap(self.selection_rect.topLeft(), cropped)
            # Draw border around selection rect
            border_pen = QPen(QColor(255, 255, 255, 255), 3)
            painter.setPen(border_pen)
            painter.drawRect(self.selection_rect)

        # Draw stroke path
        if self.drawing and len(self.strokes) > 1:
            pen = QPen(QColor(102, 204, 255, 200), 2)
            painter.setPen(pen)
            for i in range(len(self.strokes) - 1):
                painter.drawLine(self.strokes[i], self.strokes[i + 1])


from PyQt6.QtWidgets import QWidget, QPushButton, QInputDialog
from PyQt6.QtGui import QPainter, QPen, QColor, QPixmap, QImage, QFont
from PyQt6.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal
import math

class AnnotationEditor(QWidget):
    confirmed = pyqtSignal(QImage)
    redo_requested = pyqtSignal()

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(pixmap.size())
        self.base = pixmap
        self.canvas = QPixmap(pixmap.size())
        self.canvas.fill(Qt.GlobalColor.transparent)

        self.border_color = QColor(102, 204, 255, 128)
        self.pen = QPen(self.border_color, 2)

        self.drawing = False
        self.start_point = QPoint()
        self.end_point = QPoint()
        self.temp_path = []

        self.actions = []
        self.text_items = []
        self.selected_text = None
        self.drag_offset = QPoint()

        self.modes = ['freestyle', 'rect', 'arrow', 'text']
        self.mode_index = 0
        self.mode = self.modes[self.mode_index]

        self.confirm_btn = QPushButton("Confirm", self)
        self.confirm_btn.setGeometry(10, 10, 80, 30)
        self.confirm_btn.clicked.connect(self.confirm)

        self.redo_btn = QPushButton("Redo", self)
        self.redo_btn.setGeometry(100, 10, 80, 30)
        self.redo_btn.clicked.connect(self.redo)

        self.undo_btn = QPushButton("Undo", self)
        self.undo_btn.setGeometry(190, 10, 80, 30)
        self.undo_btn.clicked.connect(self.undo)

        # Mode buttons
        self.mode_buttons = []
        mode_names = ['Freestyle', 'Rect', 'Arrow', 'Text']
        for i, mode_name in enumerate(mode_names):
            btn = QPushButton(mode_name, self)
            btn.setGeometry(280 + i * 90, 10, 80, 30)
            btn.setCheckable(True)
            btn.setChecked(i == self.mode_index)
            btn.clicked.connect(lambda checked, idx=i: self.set_mode(idx))
            self.mode_buttons.append(btn)


        self.show()

    def set_mode(self, idx):
        self.mode_index = idx
        self.mode = self.modes[self.mode_index]
        for i, btn in enumerate(self.mode_buttons):
            btn.setChecked(i == idx)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drawing = True
            self.start_point = event.position().toPoint()
            self.end_point = self.start_point

            if self.mode == 'freestyle':
                self.temp_path = [self.start_point]
            elif self.mode == 'text':
                # Check if moving existing text
                for pos, txt in reversed(self.text_items):
                    rect = QRect(pos, QSize(200, 30))
                    if rect.contains(self.start_point):
                        self.selected_text = (pos, txt)
                        self.drag_offset = self.start_point - pos
                        return
                # New text input
                self.drawing = False
                text, ok = QInputDialog.getText(self, "Enter Text", "Text:")
                if ok and text:
                    self.text_items.append((self.start_point, text))
                    self.actions.append(self.canvas.copy())
                    self.update()

    def mouseMoveEvent(self, event):
        if self.selected_text:
            new_pos = event.position().toPoint() - self.drag_offset
            idx = self.text_items.index(self.selected_text)
            self.text_items[idx] = (new_pos, self.selected_text[1])
            self.update()
            return

        if self.drawing and self.mode != 'text':
            self.end_point = event.position().toPoint()
            if self.mode == 'freestyle':
                self.temp_path.append(self.end_point)
            self.update()

    def mouseReleaseEvent(self, event):
        if self.selected_text:
            self.selected_text = None
            return

        if event.button() == Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False
            painter = QPainter(self.canvas)
            painter.setPen(self.pen)

            if self.mode == 'rect':
                rect = QRect(self.start_point, self.end_point).normalized()
                painter.drawRect(rect)
            elif self.mode == 'arrow':
                self.draw_arrow(painter, self.start_point, self.end_point)
            elif self.mode == 'freestyle':
                for i in range(1, len(self.temp_path)):
                    painter.drawLine(self.temp_path[i - 1], self.temp_path[i])

            painter.end()
            self.actions.append(self.canvas.copy())
            self.update()

    def draw_arrow(self, painter: QPainter, p1: QPoint, p2: QPoint):
        painter.drawLine(p1, p2)
        angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
        length = 10
        angle1 = angle + math.pi / 6
        angle2 = angle - math.pi / 6
        arrow_p1 = QPoint(
            int(p2.x() - length * math.cos(angle1)),
            int(p2.y() - length * math.sin(angle1))
        )
        arrow_p2 = QPoint(
            int(p2.x() - length * math.cos(angle2)),
            int(p2.y() - length * math.sin(angle2))
        )
        painter.drawLine(p2, arrow_p1)
        painter.drawLine(p2, arrow_p2)

    def undo(self):
        if self.actions:
            self.actions.pop()
            self.redraw_canvas()
            self.update()

    def redraw_canvas(self):
        self.canvas.fill(Qt.GlobalColor.transparent)
        for pix in self.actions:
            p = QPainter(self.canvas)
            p.drawPixmap(0, 0, pix)
            p.end()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.base)
        painter.drawPixmap(0, 0, self.canvas)

        painter.setPen(self.pen)
        if self.drawing and self.mode != 'text':
            if self.mode == 'rect':
                rect = QRect(self.start_point, self.end_point).normalized()
                painter.drawRect(rect)
            elif self.mode == 'freestyle':
                for i in range(1, len(self.temp_path)):
                    painter.drawLine(self.temp_path[i - 1], self.temp_path[i])
            elif self.mode == 'arrow':
                self.draw_arrow(painter, self.start_point, self.end_point)

        # Draw text
        painter.setPen(self.pen)
        painter.setFont(QFont("Sans", 16))
        for pos, text in self.text_items:
            painter.drawText(pos, text)

        # Draw border
        painter.setPen(QPen(self.border_color, 4))
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def confirm(self):
        final = QImage(self.size(), QImage.Format.Format_RGBA8888)
        final.fill(Qt.GlobalColor.white)
        p = QPainter(final)
        p.drawPixmap(0, 0, self.base)
        p.drawPixmap(0, 0, self.canvas)
        p.setPen(self.pen)
        p.setFont(QFont("Sans", 16))
        for pos, text in self.text_items:
            p.drawText(pos, text)
        p.end()
        self.confirmed.emit(final)

    def redo(self):
        self.redo_requested.emit()



if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ScreenshotSelector()
    sys.exit(app.exec())
