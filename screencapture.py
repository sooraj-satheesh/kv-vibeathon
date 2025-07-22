import sys
import math
from PIL import ImageGrab
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QInputDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QLineEdit
from PyQt6.QtGui import QPainter, QPixmap, QPen, QColor, QMouseEvent, QImage, QFont, QTextCursor
from PyQt6.QtCore import Qt, QPoint, QRect, QTimer, QSize, QBuffer, QIODevice # Import QBuffer and QIODevice
import litellm # Import litellm
import markdown # Import markdown library
import base64 # For base64 encoding images
import io # For in-memory image handling (still useful for general byte operations, but QBuffer for QImage.save)

MODES = ['freestyle', 'rect', 'arrow', 'text']

# unicode icons for modes
MODE_ICONS = {
    'freestyle': '✏️',
    'rect': '⬜',
    'arrow': '➡️',
    'text': '📝'
}

class ScreenshotAnnotator(QWidget):
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
        self.selection_confirmed = False

        # Annotation state
        self.annotation_canvas = None
        self.annotation_base = None
        self.annotation_buttons = []
        self.mode_index = 0
        self.mode = MODES[self.mode_index]
        self.pen = QPen(QColor(102, 204, 255), 4)
        self.border_color = QColor(102, 204, 255, 128)
        self.ann_drawing = False
        self.ann_start_point = QPoint()
        self.ann_end_point = QPoint()
        self.ann_temp_path = []
        self.ann_actions = []
        self.text_items = []
        self.selected_text = None
        self.drag_offset = QPoint()

        # Chat interface elements
        self.chat_display = QTextBrowser(self)
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("""
            background-color: rgba(255, 255, 255, 180);
            border-radius: 10px;     
            padding: 5px;
        """)
        # Initial position, will be adjusted after selection
        self.chat_display.hide()

        self.message_input = QLineEdit(self)
        self.message_input.setPlaceholderText("Type your message...")
        self.message_input.returnPressed.connect(self.send_message)
        self.message_input.setStyleSheet("""
            background-color: rgba(255, 255, 255, 200);
            border-radius: 5px;
            padding: 5px;
        """)
        self.message_input.hide()

        self.send_button = QPushButton("Send", self)
        self.send_button.clicked.connect(self.send_message)
        self.send_button.setStyleSheet("""
            background-color: #4CAF50;
            color: white;
            border-radius: 5px;
            padding: 5px 10px;
        """)
        self.send_button.hide()

        self.chat_history = [] # Initialize chat history
        self.showFullScreen()

    # --- Selection Phase ---
    def mousePressEvent(self, event: QMouseEvent):
        if not self.selection_confirmed:
            if event.button() == Qt.MouseButton.LeftButton:
                self.drawing = True
                self.strokes = []
                self.last_point = event.position().toPoint()
                self.strokes.append(self.last_point)
        else:
            self.annotation_mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self.selection_confirmed:
            if self.drawing:
                pt = event.position().toPoint()
                self.strokes.append(pt)
                self.last_point = pt
                self.update()
        else:
            self.annotation_mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self.selection_confirmed:
            if event.button() == Qt.MouseButton.LeftButton and self.drawing:
                self.drawing = False
                self.computeBoundingRect()
                # self.show_rect = True
                self.update()
                self.confirm_selection()
        else:
            self.annotation_mouseReleaseEvent(event)

    def computeBoundingRect(self):
        if not self.strokes:
            return
        min_x = min(p.x() for p in self.strokes)
        min_y = min(p.y() for p in self.strokes)
        max_x = max(p.x() for p in self.strokes)
        max_y = max(p.y() for p in self.strokes)
        self.selection_rect = QRect(QPoint(min_x, min_y), QPoint(max_x, max_y)).normalized()

    def confirm_selection(self):
        if not self.selection_rect.isValid():
            return
        self.selection_confirmed = True
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.annotation_base = self.bg_pixmap.copy(self.selection_rect)
        self.annotation_canvas = QPixmap(self.annotation_base.size())
        self.annotation_canvas.fill(Qt.GlobalColor.transparent)
        self.ann_actions = []
        self.text_items = []
        self.mode_index = 0
        self.mode = MODES[self.mode_index]
        self.create_annotation_buttons()
        self.update()

        # Show and position chat elements to the right of the selection
        screen_width = self.bg_pixmap.width()
        chat_x = self.selection_rect.right() + 10
        chat_y = self.selection_rect.top()
        chat_width = 300  # Fixed width for the chat panel
        chat_height = self.selection_rect.height() - 30 # Leave space for input at bottom of chat
        
        if chat_x + chat_width > screen_width:
            chat_x = self.selection_rect.right() - chat_width - 40
            chat_height -= 10
            

        input_x = chat_x
        input_y = chat_y + chat_height + 5 # Below chat display, with a small gap
        input_width = chat_width - 80
        input_height = 25

        send_x = chat_x + chat_width - 70
        send_y = input_y
        send_width = 70
        send_height = 25

        self.chat_display.setGeometry(chat_x, chat_y, chat_width, chat_height)
        self.message_input.setGeometry(input_x, input_y, input_width, input_height)
        self.send_button.setGeometry(send_x, send_y, send_width, send_height)

        self.chat_display.show()
        self.message_input.show()
        self.send_button.show()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    # --- Annotation Phase ---
    def create_annotation_buttons(self):
        # Remove old buttons
        for btn in self.annotation_buttons:
            btn.setParent(None)
        self.annotation_buttons = []

        # Confirm
        btn_confirm = QPushButton("🗸", self)
        btn_confirm.setGeometry(self.selection_rect.left() + 10, self.selection_rect.top() - 40, 30, 30)
        btn_confirm.clicked.connect(self.save_final_image)
        self.annotation_buttons.append(btn_confirm)

        # Cancel
        btn_cancel = QPushButton("🞩", self)
        btn_cancel.setGeometry(self.selection_rect.left() + 50, self.selection_rect.top() - 40, 30, 30)
        btn_cancel.clicked.connect(self.restart_selection)
        self.annotation_buttons.append(btn_cancel)

        # Undo
        btn_undo = QPushButton("↶", self)
        btn_undo.setGeometry(self.selection_rect.left() + 90, self.selection_rect.top() - 40, 30, 30)
        btn_undo.clicked.connect(self.undo)
        self.annotation_buttons.append(btn_undo)

        # Mode buttons
        for i, mode_name in enumerate(MODES):
            btn = QPushButton(MODE_ICONS[mode_name], self)
            btn.setGeometry(self.selection_rect.left() + 130 + i * 40, self.selection_rect.top() - 40, 30, 30)
            btn.setCheckable(True)
            btn.setChecked(i == self.mode_index)
            btn.clicked.connect(lambda _, idx=i: self.set_mode(idx))
            self.annotation_buttons.append(btn)

        for btn in self.annotation_buttons:
            btn.show()

    def set_mode(self, idx):
        self.mode_index = idx
        self.mode = MODES[self.mode_index]
        # Update button checked state
        for i, btn in enumerate(self.annotation_buttons[3:]):
            btn.setChecked(i == idx)

    def annotation_mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Translate event to selection_rect-local coordinates
            pt = event.position().toPoint() - self.selection_rect.topLeft()
            self.ann_drawing = True
            self.ann_start_point = pt
            self.ann_end_point = pt

            if self.mode == 'freestyle':
                self.ann_temp_path = [self.ann_start_point]
            elif self.mode == 'text':
                # Check if moving existing text
                for pos, txt in reversed(self.text_items):
                    rect = QRect(pos, QSize(200, 30))
                    if rect.contains(self.ann_start_point):
                        self.selected_text = (pos, txt)
                        self.drag_offset = self.ann_start_point - pos
                        return
                # New text input
                self.ann_drawing = False
                text, ok = QInputDialog.getText(self, "Enter Text", "Text:")
                if ok and text:
                    self.text_items.append((self.ann_start_point, text))
                    self.ann_actions.append(self.annotation_canvas.copy())
                    self.update()

    def annotation_mouseMoveEvent(self, event):
        pt = event.position().toPoint() - self.selection_rect.topLeft()
        if self.selected_text:
            new_pos = pt - self.drag_offset
            idx = self.text_items.index(self.selected_text)
            self.text_items[idx] = (new_pos, self.selected_text[1])
            self.update()
            return

        if self.ann_drawing and self.mode != 'text':
            self.ann_end_point = pt
            if self.mode == 'freestyle':
                self.ann_temp_path.append(self.ann_end_point)
            self.update()

    def annotation_mouseReleaseEvent(self, event):
        if self.selected_text:
            self.selected_text = None
            return

        if event.button() == Qt.MouseButton.LeftButton and self.ann_drawing:
            self.ann_drawing = False
            painter = QPainter(self.annotation_canvas)
            painter.setPen(self.pen)

            if self.mode == 'rect':
                rect = QRect(self.ann_start_point, self.ann_end_point).normalized()
                painter.drawRect(rect)
            elif self.mode == 'arrow':
                self.draw_arrow(painter, self.ann_start_point, self.ann_end_point)
            elif self.mode == 'freestyle':
                for i in range(1, len(self.ann_temp_path)):
                    painter.drawLine(self.ann_temp_path[i - 1], self.ann_temp_path[i])

            painter.end()
            self.ann_actions.append(self.annotation_canvas.copy())
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
        if self.ann_actions:
            self.ann_actions.pop()
            self.redraw_canvas()
            self.update()

    def redraw_canvas(self):
        self.annotation_canvas.fill(Qt.GlobalColor.transparent)
        for pix in self.ann_actions:
            p = QPainter(self.annotation_canvas)
            p.drawPixmap(0, 0, pix)
            p.end()

    def save_final_image(self):
        final = QImage(self.selection_rect.size(), QImage.Format.Format_RGBA8888)
        final.fill(Qt.GlobalColor.white)
        p = QPainter(final)
        p.drawPixmap(0, 0, self.annotation_base)
        p.drawPixmap(0, 0, self.annotation_canvas)
        p.setPen(self.pen)
        p.setFont(QFont("Sans", 16))
        for pos, text in self.text_items:
            p.drawText(pos, text)
        p.end()
        final.save("selection_edited.png")
        self.close()

    def restart_selection(self):
        self.selection_confirmed = False
        for btn in self.annotation_buttons:
            btn.setParent(None)
        self.annotation_buttons = []
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.show_rect = False
        self.selection_rect = QRect()
        self.chat_display.hide()
        self.message_input.hide()
        self.send_button.hide()
        self.update()

    def get_current_annotated_image_base64(self):
        if not self.selection_confirmed or not self.selection_rect.isValid():
            return None

        # Create a QImage to draw the current annotated state
        combined_image = QImage(self.selection_rect.size(), QImage.Format.Format_RGBA8888)
        combined_image.fill(Qt.GlobalColor.transparent) # Start with transparent background

        painter = QPainter(combined_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw the base image
        painter.drawPixmap(0, 0, self.annotation_base)

        # Draw the annotation canvas
        painter.drawPixmap(0, 0, self.annotation_canvas)

        # Draw text items
        painter.setPen(self.pen)
        painter.setFont(QFont("Sans", 16))
        for pos, text in self.text_items:
            painter.drawText(pos, text)
        painter.end()

        # Convert QImage to bytes using QBuffer and then to base64
        byte_array = QBuffer()
        byte_array.open(QIODevice.OpenModeFlag.WriteOnly)
        combined_image.save(byte_array, "PNG") # Save as PNG to maintain transparency
        encoded_image = base64.b64encode(byte_array.data()).decode("utf-8")
        byte_array.close()
        return encoded_image

    # --- Paint ---
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

        # Draw stroke path (selection phase)
        if self.drawing and len(self.strokes) > 1:
            pen = QPen(QColor(102, 204, 255, 255), 4)
            painter.setPen(pen)
            for i in range(len(self.strokes) - 1):
                painter.drawLine(self.strokes[i], self.strokes[i + 1])

        # Draw annotation (annotation phase)
        if self.selection_confirmed and self.selection_rect.isValid():
            # Draw annotation base and canvas
            painter.drawPixmap(self.selection_rect.topLeft(), self.annotation_base)
            painter.drawPixmap(self.selection_rect.topLeft(), self.annotation_canvas)

            # Draw current drawing
            painter.setPen(self.pen)
            if self.ann_drawing and self.mode != 'text':
                if self.mode == 'rect':
                    rect = QRect(self.ann_start_point, self.ann_end_point).normalized()
                    painter.save()
                    painter.translate(self.selection_rect.topLeft())
                    painter.drawRect(rect)
                    painter.restore()
                elif self.mode == 'freestyle':
                    painter.save()
                    painter.translate(self.selection_rect.topLeft())
                    for i in range(1, len(self.ann_temp_path)):
                        painter.drawLine(self.ann_temp_path[i - 1], self.ann_temp_path[i])
                    painter.restore()
                elif self.mode == 'arrow':
                    painter.save()
                    painter.translate(self.selection_rect.topLeft())
                    self.draw_arrow(painter, self.ann_start_point, self.ann_end_point)
                    painter.restore()

            # Draw text
            painter.setPen(self.pen)
            painter.setFont(QFont("Sans", 16))
            painter.save()
            painter.translate(self.selection_rect.topLeft())
            for pos, text in self.text_items:
                painter.drawText(pos, text)
            painter.restore()

            # Draw border
            painter.setPen(QPen(self.border_color, 4))
            painter.drawRect(self.selection_rect.adjusted(1, 1, -2, -2))

    def send_message(self):
        user_message = self.message_input.text().strip()
        if not user_message and not self.selection_confirmed: # Don't send empty message if no selection
            return

        self.chat_display.append(f"<b>You:</b> {user_message}")
        self.message_input.clear()

        # Prepare message content, including image if available
        message_content = []
        if user_message:
            message_content.append({"type": "text", "text": user_message})

        # Get current annotated image and add to message if selection is confirmed
        if self.selection_confirmed:
            encoded_image = self.get_current_annotated_image_base64()
            if encoded_image:
                message_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded_image}"}
                })

        if message_content:
            # If this is the first message or if the last message was from assistant, add a new user role
            # Otherwise, append to the last user message (if it was multimodal)
            if not self.chat_history or self.chat_history[-1]["role"] == "assistant":
                self.chat_history.append({"role": "user", "content": message_content})
            else: # Append to existing user message
                # This part needs careful handling for existing multimodal messages
                # For simplicity, we'll just append new content to the last user message's content list
                # A more robust solution might involve merging content or creating new messages
                self.chat_history[-1]["content"].extend(message_content)

            QTimer.singleShot(500, lambda: self.get_llm_response())

    def get_llm_response(self):
        try:
            self.chat_display.append("<i>LLM:</i> ")
            QApplication.processEvents()

            full_response_content = ""
            for chunk in litellm.completion(
                model="gemini/gemini-1.5-flash",
                messages=self.chat_history,
                stream=True
            ):
                if chunk.choices[0].delta.content:
                    content_chunk = chunk.choices[0].delta.content
                    full_response_content += content_chunk
                    self.chat_display.insertPlainText(content_chunk)
                    self.chat_display.ensureCursorVisible()
                    QApplication.processEvents()

            self.chat_history.append({"role": "assistant", "content": full_response_content})
        except Exception as e:
            self.chat_display.append(f"<i>LLM Error:</i> {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ScreenshotAnnotator()
    sys.exit(app.exec())
