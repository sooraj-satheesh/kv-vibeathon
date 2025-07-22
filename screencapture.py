import sys
import math
import threading
from PIL import ImageGrab
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QInputDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QLineEdit
from PyQt6.QtGui import QPainter, QPixmap, QPen, QColor, QMouseEvent, QImage, QFont, QLinearGradient, QPainterPath, QTextCursor
from PyQt6.QtCore import Qt, QPoint, QRect, QTimer, QSize, QBuffer, QIODevice, QPointF, QRectF, pyqtSignal
from PIL import Image, ImageFilter
import litellm # Import litellm
import markdown # Import markdown library
import base64 # For base64 encoding images
import io # For in-memory image handling (still useful for general byte operations, but QBuffer for QImage.save)

MODES = ['freestyle', 'rect', 'arrow', 'text', 'blur', 'highlight', 'erase']

# unicode icons for modes
MODE_ICONS = {
    'freestyle': '✏️',
    'rect': '▭',
    'arrow': '➔',
    'text': '📝',
    'blur': '🌀',
    'highlight': '🔶',
    'erase': '🧽',
}

class ScreenshotAnnotator(QWidget):
    llm_chunk_received = pyqtSignal(str)
    llm_stream_finished = pyqtSignal(str)

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

        # --- Initial Full-Screen Animation State (now continuous wave) ---
        self.gradient_phase = 0.0 # Phase for the wave animation
        self.initial_animation_timer = QTimer(self) # Timer for the initial animation
        self.initial_animation_timer.timeout.connect(self.update_initial_animation)
        self.initial_animation_timer.setInterval(30) # Update every 30ms
        self.initial_animation_timer.start() # Animation now starts immediately on launch

        self.border_angle = 0.0 # New variable for border gradient rotation

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
        self.llm_chunk_received.connect(self.append_chat_chunk)
        self.llm_stream_finished.connect(self.finalize_llm_response)
        self.showFullScreen()

    def update_initial_animation(self):
        """
        Updates the phase for the full-screen wave animation
        and triggers a repaint.
        """
        self.gradient_phase = (self.gradient_phase + 0.05) % (2 * math.pi) # Increment phase, wrap around 2*PI
        self.border_angle = (self.border_angle + 0.03) % (2 * math.pi) # Increment border angle for rotation
        self.update() # Request a repaint

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

        # Common style for annotation buttons
        btn_style = """
            QPushButton {
            background-color: #f0f4fa;
            border: 1px solid #b0c4de;
            border-radius: 7px;
            font-size: 18px;
            }
            QPushButton:hover {
            background-color: #d0eaff;
            border: 1.5px solid #3399ff;
            }
            QPushButton:checked {
            background-color: #3399ff;
            color: white;
            border: 2px solid #005fa3;
            }
        """

        # Cancel
        btn_cancel = QPushButton("🞩", self)
        btn_cancel.setGeometry(self.selection_rect.left() + 10, self.selection_rect.top() - 40, 30, 30)
        btn_cancel.clicked.connect(self.restart_selection)
        btn_cancel.setStyleSheet(btn_style)
        btn_cancel.setToolTip("Cancel and reselect area")
        self.annotation_buttons.append(btn_cancel)

        # Undo
        btn_undo = QPushButton("↶", self)
        btn_undo.setGeometry(self.selection_rect.left() + 50, self.selection_rect.top() - 40, 30, 30)
        btn_undo.clicked.connect(self.undo)
        btn_undo.setStyleSheet(btn_style)
        btn_undo.setToolTip("Undo last annotation")
        self.annotation_buttons.append(btn_undo)

        # Mode buttons
        for i, mode_name in enumerate(MODES):
            btn = QPushButton(MODE_ICONS[mode_name], self)
            btn.setGeometry(self.selection_rect.left() + 90 + i * 40, self.selection_rect.top() - 40, 30, 30)
            btn.setCheckable(True)
            btn.setChecked(i == self.mode_index)
            btn.setStyleSheet(btn_style)
            btn.setToolTip(f"Switch to {mode_name} mode")
            btn.clicked.connect(lambda _, idx=i: self.set_mode(idx))
            self.annotation_buttons.append(btn)

        for btn in self.annotation_buttons:
            btn.show()

    def set_mode(self, idx):
        self.mode_index = idx
        self.mode = MODES[self.mode_index]
        # Update button checked state
        for i, btn in enumerate(self.annotation_buttons[len(self.annotation_buttons)-len(MODES):]):
            btn.setChecked(i == idx)

    def annotation_mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pt = event.position().toPoint() - self.selection_rect.topLeft()
            self.ann_drawing = True
            self.ann_start_point = pt
            self.ann_end_point = pt

            if self.mode == 'freestyle':
                self.ann_temp_path = [self.ann_start_point]
            elif self.mode == 'highlight':
                self.ann_temp_path = [self.ann_start_point]
            elif self.mode == 'blur':
                self.ann_temp_path = [self.ann_start_point]
            elif self.mode == 'erase':
                self.ann_temp_path = [self.ann_start_point]
            elif self.mode == 'text':
                for pos, txt in reversed(self.text_items):
                    rect = QRect(pos, QSize(200, 30))
                    if rect.contains(self.ann_start_point):
                        self.selected_text = (pos, txt)
                        self.drag_offset = self.ann_start_point - pos
                        return
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
            if self.mode in ['freestyle', 'highlight', 'erase']:
                self.ann_temp_path.append(self.ann_end_point)
            self.update()

            # Live preview for highlight and erase
            if self.mode in ['highlight', 'erase']:
                self.redraw_canvas()
                painter = QPainter(self.annotation_canvas)
                if self.mode == 'highlight':
                    highlight_pen = QPen(QColor(255, 255, 0, 10), 32, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                    painter.setPen(highlight_pen)
                    for i in range(1, len(self.ann_temp_path)):
                        painter.drawLine(self.ann_temp_path[i - 1], self.ann_temp_path[i])
                elif self.mode == 'erase':
                    erase_pen = QPen(Qt.GlobalColor.transparent, 32, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                    painter.setPen(erase_pen)
                    for i in range(1, len(self.ann_temp_path)):
                        painter.drawLine(self.ann_temp_path[i - 1], self.ann_temp_path[i])
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                painter.end()
                self.update()
            elif self.mode == 'blur':
                # Draw a preview rectangle for blur
                self.redraw_canvas()
                painter = QPainter(self.annotation_canvas)
                rect = QRect(self.ann_start_point, self.ann_end_point).normalized()
                preview_pen = QPen(QColor(0, 0, 0, 128), 2, Qt.PenStyle.DashLine)
                painter.setPen(preview_pen)
                painter.drawRect(rect)
                painter.end()
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
            elif self.mode == 'blur':
                # Apply blur to the selected rectangle
                rect = QRect(self.ann_start_point, self.ann_end_point).normalized()
                if rect.width() > 0 and rect.height() > 0:
                    base_qimg = self.annotation_base.copy(rect).toImage()
                    ptr = base_qimg.bits()
                    ptr.setsize(base_qimg.sizeInBytes())
                    pil_img = Image.frombytes("RGBA", (base_qimg.width(), base_qimg.height()), bytes(ptr))
                    blurred = pil_img.filter(ImageFilter.GaussianBlur(radius=6))
                    buf = blurred.tobytes("raw", "RGBA")
                    qimg_blur = QImage(buf, blurred.width, blurred.height, QImage.Format.Format_RGBA8888)
                    painter.drawImage(rect.topLeft(), qimg_blur)
            # No special action for highlight or erase on mouse release (already handled in live preview)
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
        """
        Handles the painting of the widget, including background, selection,
        annotations, and the LLM thinking animation.
        """
        painter = QPainter(self)

        # 1. Draw the original full screenshot
        painter.drawPixmap(0, 0, self.bg_pixmap)

        # 2. Draw the animated gradient over the entire screen (always active)
        # Using fixed RGB values for red and blue for the background gradient
        color1_bg = QColor(255, 0, 0, 100) # Red with 100 alpha
        color2_bg = QColor(0, 0, 255, 100) # Blue with 100 alpha

        gradient_full_screen = QLinearGradient(0, 0, self.width(), self.height())
        gradient_full_screen.setColorAt(0.0, color1_bg)
        gradient_full_screen.setColorAt(1.0, color2_bg)
        painter.fillRect(self.rect(), gradient_full_screen)


        # 3. Draw the dark overlay over the entire screen (on top of the background gradient)
        overlay_color = QColor(0, 0, 0, 128) # 50% opaque black
        painter.fillRect(self.rect(), overlay_color)

        # 4. If selection is confirmed, reveal the selected area and draw specific gradients/elements
        if self.selection_confirmed and self.selection_rect.isValid():
            # A. Reveal the selected area by drawing the original content there (drawn LAST to cover gradients)
            cropped = self.bg_pixmap.copy(self.selection_rect)
            painter.drawPixmap(self.selection_rect.topLeft(), cropped)

            # C. Draw annotations on top of the revealed screenshot
            painter.drawPixmap(self.selection_rect.topLeft(), self.annotation_canvas)

            # D. Draw the current temporary annotation being drawn
            painter.setPen(self.pen)
            if self.ann_drawing and self.mode != 'text':
                painter.save()
                painter.translate(self.selection_rect.topLeft())
                if self.mode == 'rect':
                    rect = QRect(self.ann_start_point, self.ann_end_point).normalized()
                    painter.drawRect(rect)
                elif self.mode == 'freestyle':
                    for i in range(1, len(self.ann_temp_path)):
                        painter.drawLine(self.ann_temp_path[i - 1], self.ann_temp_path[i])
                elif self.mode == 'arrow':
                    self.draw_arrow(painter, self.ann_start_point, self.ann_end_point)
                painter.restore()

            # E. Draw all text annotations
            painter.setPen(self.pen)
            painter.setFont(QFont("Sans", 16))
            painter.save()
            painter.translate(self.selection_rect.topLeft())
            for pos, text in self.text_items:
                painter.drawText(pos, text)
            painter.restore()

            # Add a red-grey-blue gradient border around the selected area
            # Calculate center of the selection rectangle
            center_x = self.selection_rect.center().x()
            center_y = self.selection_rect.center().y()

            # Determine a length for the gradient line that spans across the rectangle
            # It should be large enough to cover the diagonal
            gradient_line_length = math.sqrt(self.selection_rect.width()**2 + self.selection_rect.height()**2)

            # Calculate start and end points for the linear gradient based on the rotating angle
            # These points are relative to the center of the selection_rect
            start_x_rel = -gradient_line_length / 2 * math.cos(self.border_angle)
            start_y_rel = -gradient_line_length / 2 * math.sin(self.border_angle)
            end_x_rel = gradient_line_length / 2 * math.cos(self.border_angle)
            end_y_rel = gradient_line_length / 2 * math.sin(self.border_angle)

            # Convert relative points to absolute screen coordinates
            gradient_start_point = QPointF(center_x + start_x_rel, center_y + start_y_rel)
            gradient_end_point = QPointF(center_x + end_x_rel, center_y + end_y_rel)
            
            border_gradient = QLinearGradient(gradient_start_point, gradient_end_point)
            
            # Setting color stops for 3:7 red to (grey to blue) ratio
            border_gradient.setColorAt(0.0, QColor(255, 0, 0)) # Red starts
            border_gradient.setColorAt(0.3, QColor(255, 0, 0)) # Red ends at 30%
            border_gradient.setColorAt(0.3, QColor(128, 128, 128)) # Grey starts at 30%
            border_gradient.setColorAt(1.0, QColor(0, 0, 255)) # Blue ends at 100%

            gradient_pen = QPen(border_gradient, 2) # 2 pixels thick
            painter.setPen(gradient_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush) # No fill for the border
            
            # Add rounded edges to the border
            border_radius = 10 # Define a radius for rounded corners
            painter.drawRoundedRect(QRectF(self.selection_rect), border_radius, border_radius)

        # 4. If selection is NOT confirmed, draw the selection stroke
        elif self.drawing and len(self.strokes) > 1:
            pen = QPen(QColor(102, 204, 255, 200), 2)
            painter.setPen(pen)
            for i in range(len(self.strokes) - 1):
                painter.drawLine(self.strokes[i], self.strokes[i + 1])

    def send_message(self):
        user_message = self.message_input.text().strip()
        if not user_message and not self.selection_confirmed: # Don't send empty message if no selection
            return

        self.chat_display.append(f"<b>You:</b> {user_message}")
        self.chat_display.append("")
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
            if not self.chat_history or self.chat_history[-1]["role"] == "assistant":
                self.chat_history.append({"role": "user", "content": message_content})
            else:
                self.chat_history[-1]["content"].extend(message_content)

            # Run LLM call in a separate thread
            thread = threading.Thread(target=self.get_llm_response)
            thread.start()

    def get_llm_response(self):
        try:
            full_response_content = ""
            # First, emit a signal to indicate that the LLM is starting to respond
            self.llm_chunk_received.emit("<b><i>Sherlock: </i></b>")

            for chunk in litellm.completion(
                model="gemini/gemini-1.5-flash",
                messages=self.chat_history,
                stream=True
            ):
                if chunk.choices[0].delta.content:
                    content_chunk = chunk.choices[0].delta.content
                    self.llm_chunk_received.emit(content_chunk)
                    full_response_content += content_chunk
            
            self.llm_stream_finished.emit(full_response_content)

        except Exception as e:
            self.llm_chunk_received.emit(f"<i>Error:</i> {e}")

    def append_chat_chunk(self, chunk):
        html_chunk = markdown.markdown(chunk).strip()
        # Remove paragraph tags for smoother streaming
        if html_chunk.startswith("<p>") and html_chunk.endswith("</p>"):
            html_chunk = html_chunk[3:-4]
            
        self.chat_display.insertHtml(html_chunk)
        self.chat_display.ensureCursorVisible()
        QApplication.processEvents()

    def finalize_llm_response(self, full_response):
        self.chat_history.append({"role": "assistant", "content": full_response})
        self.chat_display.append("") # Add a newline for separation


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ScreenshotAnnotator()
    sys.exit(app.exec())
