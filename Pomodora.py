# -*- coding: utf-8 -*-
# Final Version with Progressive Break Logic, win11toast, all fixes, Fixed Mode

import sys
import math
import random
import os
import threading # For win11toast threading
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QDialog, QFormLayout, QLineEdit,
    QSpinBox, QFileDialog, QSizePolicy, QStyle, QFrame, QSpacerItem,
    QMessageBox, QSystemTrayIcon, QCheckBox # Added QCheckBox
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QIcon, QPixmap, QPalette
)
from PyQt6.QtCore import (
    Qt, QTimer, QPointF, QRectF, QSettings, QUrl, QSize, pyqtSignal, QObject
)
from PyQt6.QtMultimedia import QSoundEffect, QMediaPlayer, QAudioOutput

# --- Try importing win11toast (Conditional Import) ---
_Win11ToastImported = False
if sys.platform == 'win32':
    try:
        import win11toast # Directly import the main module
        _Win11ToastImported = True
        print("[Toast] win11toast library imported successfully.")
    except ImportError:
        print("[Toast] Warning: win11toast library not found. Falling back to QSystemTrayIcon notifications on Windows.")
        print("[Toast] Install using: pip install win11toast")
else:
    print("[Toast] Not on Windows, win11toast will not be used.")


# --- Configuration Constants ---
DEFAULT_FOCUS_MINUTES = 90
DEFAULT_SHORT_BREAK_SECONDS = 10
DEFAULT_LONG_BREAK_MINUTES = 20
DEFAULT_SHORT_BREAK_MAX_TRIGGER_MINUTES = 5 # Max time until next break
MAX_DRAGGABLE_MINUTES = 90
SETTINGS_SOUND_KEY = "notification_sound_path"
SETTINGS_FIXED_MODE_KEY = "fixed_mode_enabled" # New settings key
NOTIFICATION_DURATION_MS = 7000

# --- Application States ---
STATE_IDLE = 0
STATE_FOCUS = 1
STATE_SHORT_BREAK = 2
STATE_LONG_BREAK = 3
STATE_PAUSED = 4

# --- Helper Class for Audio Duration Check (Unchanged) ---
class AudioChecker(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)

# --- Circular Timer Widget (Unchanged) ---
class CircularTimer(QWidget):
    time_changed_by_drag = pyqtSignal(int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.max_minutes = MAX_DRAGGABLE_MINUTES
        self.current_minutes = min(DEFAULT_FOCUS_MINUTES, self.max_minutes)
        self.total_seconds_display = self.current_minutes * 60
        self.is_running = False
        self.is_dragging = False
        self.is_break_phase = False
        self.actual_total_seconds_for_phase = self.total_seconds_display
        self.setMinimumSize(250, 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.outer_color = QColor("#A0D2EB")
        self.text_color = QColor(Qt.GlobalColor.black)
        self.background_color = QColor(Qt.GlobalColor.white)

    def set_time(self, minutes):
        if not self.is_running and not self.is_dragging:
            clamped_minutes = max(0, min(self.max_minutes, minutes))
            if self.current_minutes != clamped_minutes:
                self.current_minutes = clamped_minutes
            self.total_seconds_display = self.current_minutes * 60
            self.update()

    def set_display_time(self, total_seconds):
        self.total_seconds_display = max(0, total_seconds)
        if not self.is_running or (self.is_running and not self.is_break_phase):
            display_minutes = total_seconds / 60.0
            self.current_minutes = max(0, min(self.max_minutes, round(display_minutes)))
        self.update()

    def set_actual_total_seconds(self, total_seconds):
        self.actual_total_seconds_for_phase = total_seconds
        if not self.is_running and not self.is_dragging:
             potential_minutes = total_seconds / 60.0
             clamped_minutes = max(0, min(self.max_minutes, round(potential_minutes)))
             if self.current_minutes != clamped_minutes:
                 self.current_minutes = clamped_minutes
                 self.total_seconds_display = clamped_minutes * 60
             self.update()
        elif self.is_running and self.is_break_phase:
             self.update()

    def set_running(self, running):
        was_running = self.is_running
        self.is_running = running
        if not running and was_running:
             display_minutes = self.total_seconds_display / 60.0
             self.current_minutes = max(0, min(self.max_minutes, round(display_minutes)))
             self.is_break_phase = False
        self.update()

    def set_break_phase(self, is_break):
        if self.is_break_phase != is_break:
            self.is_break_phase = is_break
            if not self.is_running and is_break:
                 total_break_minutes = self.actual_total_seconds_for_phase / 60.0
                 self.current_minutes = max(0, min(self.max_minutes, round(total_break_minutes)))
            self.update()

    def _get_angle_from_pos(self, pos):
        center = QPointF(self.rect().center())
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        if dx == 0 and dy == 0: return 0
        raw_qt_angle_deg = math.degrees(math.atan2(dy, dx))
        if raw_qt_angle_deg < 0: raw_qt_angle_deg += 360
        return raw_qt_angle_deg

    def _angle_to_minutes(self, angle_degrees):
        angle_from_12_cw = (angle_degrees - 270 + 360) % 360
        if self.max_minutes == 0: return 0
        epsilon = 1e-9
        minutes = ((angle_from_12_cw + epsilon) / 360.0) * self.max_minutes
        rounded_minutes = round(minutes)
        return max(0, min(self.max_minutes, rounded_minutes))

    def _minutes_to_angle_span(self, minutes):
        clamped_minutes = max(0, min(self.max_minutes, minutes))
        if self.max_minutes == 0: return 0
        fraction = clamped_minutes / self.max_minutes
        span_angle = -fraction * 360.0 * 16
        return int(span_angle)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        widget_rect = self.rect()
        side = min(widget_rect.width(), widget_rect.height())
        padding = side * 0.1
        diameter = side - 2 * padding
        radius = diameter / 2.0
        center = QPointF(widget_rect.center())
        arc_rect = QRectF(center.x() - radius, center.y() - radius, diameter, diameter)
        pen = QPen(self.outer_color, 15)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        start_angle_qt = 90 * 16
        minutes_for_arc = 0
        if self.is_running and self.is_break_phase:
            total_break_minutes = self.actual_total_seconds_for_phase / 60.0
            minutes_for_arc = max(0, min(self.max_minutes, round(total_break_minutes)))
        elif self.is_break_phase and not self.is_running:
             total_break_minutes = self.actual_total_seconds_for_phase / 60.0
             minutes_for_arc = max(0, min(self.max_minutes, round(total_break_minutes)))
        else:
            minutes_for_arc = self.current_minutes
        if minutes_for_arc >= self.max_minutes: span_angle = -360 * 16
        elif minutes_for_arc <= 0: span_angle = 0
        else: span_angle = self._minutes_to_angle_span(minutes_for_arc)
        painter.drawArc(arc_rect, start_angle_qt, span_angle)
        painter.setPen(self.text_color)
        font = QFont("Arial", int(radius * 0.4), QFont.Weight.Bold)
        painter.setFont(font)
        display_minutes = self.total_seconds_display // 60
        display_seconds = self.total_seconds_display % 60
        time_str = f"{display_minutes:02}:{display_seconds:02}"
        painter.drawText(arc_rect, Qt.AlignmentFlag.AlignCenter, time_str)

    def _update_time_from_drag(self, pos):
        # Prevent dragging *while* running (is_running check in mouse events)
        if self.is_running: return
        center = QPointF(self.rect().center())
        radius = min(self.width(), self.height()) / 2.0 * 0.9
        dist_sq = (pos.x() - center.x())**2 + (pos.y() - center.y())**2
        outer_radius_sq = radius**2
        inner_radius_sq = (radius * 0.7)**2
        if not (inner_radius_sq <= dist_sq <= outer_radius_sq): return
        raw_qt_angle_deg = self._get_angle_from_pos(pos)
        potential_new_minutes = self._angle_to_minutes(raw_qt_angle_deg)
        final_new_minutes = potential_new_minutes
        near_max_threshold = self.max_minutes - max(1, self.max_minutes * 0.08)
        near_min_threshold = max(1, self.max_minutes * 0.08)
        if self.current_minutes >= near_max_threshold and potential_new_minutes <= near_min_threshold:
            final_new_minutes = self.max_minutes
        if final_new_minutes != self.current_minutes:
            self.current_minutes = final_new_minutes
            self.total_seconds_display = self.current_minutes * 60
            # Emit signal regardless, MainWindow decides if to use it
            self.time_changed_by_drag.emit(self.current_minutes)
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Prevent dragging if timer is running AT ALL
            if self.is_running:
                event.ignore()
                return
            pos = event.pos()
            center = QPointF(self.rect().center())
            radius = min(self.width(), self.height()) / 2.0 * 0.9
            dist_sq = (pos.x() - center.x())**2 + (pos.y() - center.y())**2
            outer_radius_sq = radius**2
            inner_radius_sq = (radius * 0.7)**2
            if inner_radius_sq <= dist_sq <= outer_radius_sq:
                self.is_dragging = True
                self._update_time_from_drag(pos)
                event.accept()
            else:
                self.is_dragging = False
                event.ignore()
        else: event.ignore()

    def mouseMoveEvent(self, event):
        # Prevent dragging if timer is running AT ALL
        if self.is_running:
             self.is_dragging = False # Ensure dragging stops if timer starts mid-drag
             event.ignore()
             return
        if self.is_dragging:
             if event.buttons() & Qt.MouseButton.LeftButton:
                 self._update_time_from_drag(event.pos())
                 event.accept()
             else:
                 self.is_dragging = False
                 event.ignore()
        else: event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.is_dragging:
                self.is_dragging = False
                event.accept()
            else:
                event.ignore()
        else: event.ignore()

# --- Settings Dialog (Unchanged) ---
class SettingsDialog(QDialog):
    settings_saved = pyqtSignal(dict)

    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.current_settings = current_settings
        self.selected_audio_file_path = self.current_settings.get(SETTINGS_SOUND_KEY)
        # Check validity on init
        self.audio_path_valid = bool(self.selected_audio_file_path and \
                                   os.path.exists(self.selected_audio_file_path) and \
                                   os.path.isfile(self.selected_audio_file_path))
        if not self.audio_path_valid:
            self.selected_audio_file_path = None # Clear if invalid

        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # Create and configure input widgets
        self.focus_duration_input = QSpinBox(); self.focus_duration_input.setRange(1, 999); self.focus_duration_input.setSuffix(" 分钟"); self.focus_duration_input.setValue(self.current_settings.get("focus_duration", DEFAULT_FOCUS_MINUTES)); form_layout.addRow("专注时长:", self.focus_duration_input)
        self.short_break_duration_input = QSpinBox(); self.short_break_duration_input.setRange(1, 300); self.short_break_duration_input.setSuffix(" 秒"); self.short_break_duration_input.setValue(self.current_settings.get("short_break_duration", DEFAULT_SHORT_BREAK_SECONDS)); form_layout.addRow("短休息时长:", self.short_break_duration_input)
        self.sb_trigger_max_input = QSpinBox(); self.sb_trigger_max_input.setRange(1, 120); self.sb_trigger_max_input.setSuffix(" 分钟"); self.sb_trigger_max_input.setValue(self.current_settings.get("sb_trigger_max", DEFAULT_SHORT_BREAK_MAX_TRIGGER_MINUTES)); form_layout.addRow("短休息最晚触发时间:", self.sb_trigger_max_input) # Changed Label
        self.long_break_duration_input = QSpinBox(); self.long_break_duration_input.setRange(1, 120); self.long_break_duration_input.setSuffix(" 分钟"); self.long_break_duration_input.setValue(self.current_settings.get("long_break_duration", DEFAULT_LONG_BREAK_MINUTES)); form_layout.addRow("长休息时长:", self.long_break_duration_input)

        # Sound Selection Widget (Unchanged)
        sound_widget = QWidget(); sound_v_layout = QVBoxLayout(sound_widget); sound_v_layout.setContentsMargins(0,0,0,0); self.sound_select_button = QPushButton("选择本地音频文件...")
        initial_label_text = "未选择文件 (需要选择)"; initial_label_style = "color: gray;"
        if self.audio_path_valid: initial_label_text = "当前: " + os.path.basename(self.selected_audio_file_path); initial_label_style = "color: green;"
        self.sound_file_label = QLabel(initial_label_text); self.sound_file_label.setStyleSheet(initial_label_style); self.sound_file_label.setWordWrap(True)
        sound_v_layout.addWidget(self.sound_select_button); sound_v_layout.addWidget(self.sound_file_label); form_layout.addRow("通知声音:", sound_widget); self.sound_select_button.clicked.connect(self.select_local_sound)

        layout.addLayout(form_layout)

        # Dialog Buttons (Unchanged)
        button_layout = QHBoxLayout(); self.back_button = QPushButton("返回"); self.save_button = QPushButton("保存")
        self.save_button.setDefault(True); button_layout.addStretch(1); button_layout.addWidget(self.back_button); button_layout.addWidget(self.save_button)
        layout.addLayout(button_layout); self.back_button.clicked.connect(self.reject); self.save_button.clicked.connect(self.save_and_close)

    def select_local_sound(self):
        supported_formats = "音频文件 (*.wav *.mp3 *.ogg *.flac)"; start_dir = "";
        if self.selected_audio_file_path and os.path.exists(os.path.dirname(self.selected_audio_file_path)): start_dir = os.path.dirname(self.selected_audio_file_path)
        else: start_dir = os.path.expanduser("~")
        file_path, _ = QFileDialog.getOpenFileName(self, "选择音频文件", start_dir, supported_formats)
        if file_path:
            if os.path.exists(file_path) and os.path.isfile(file_path):
                 self.selected_audio_file_path = file_path; self.audio_path_valid = True; self.sound_file_label.setText("当前: " + os.path.basename(self.selected_audio_file_path)); self.sound_file_label.setStyleSheet("color: green;"); print(f"[Settings] Sound file selected: {file_path}")
            else:
                 self.selected_audio_file_path = None; self.audio_path_valid = False; self.sound_file_label.setText("选择的文件无效或不存在"); self.sound_file_label.setStyleSheet("color: red;"); QMessageBox.warning(self, "文件错误", f"选择的文件路径无效或不存在:\n{file_path}")

    def save_and_close(self):
        path_to_save = self.selected_audio_file_path; is_path_valid_at_save = False
        if path_to_save and os.path.exists(path_to_save) and os.path.isfile(path_to_save): is_path_valid_at_save = True
        else:
            if path_to_save: QMessageBox.warning(self, "保存错误", f"之前选择的音频文件现在似乎不存在或无效：\n{path_to_save}\n\n将保存为空白路径，请稍后重新选择。")
            path_to_save = None
        max_trigger = self.sb_trigger_max_input.value()
        new_settings = {
            "focus_duration": self.focus_duration_input.value(),
            "short_break_duration": self.short_break_duration_input.value(),
            "sb_trigger_max": max_trigger,
            "long_break_duration": self.long_break_duration_input.value(),
            SETTINGS_SOUND_KEY: path_to_save
            # Fixed mode is NOT saved via this dialog
        }
        self.settings_saved.emit(new_settings)
        self.accept()


# --- Main Application Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("MyCompany", "FocusTimerApp")
        self.sound_file_valid = False
        self.tray_icon = None
        self.app_icon_path = None

        # Initialize core timer variables
        self.focus_duration = DEFAULT_FOCUS_MINUTES # Will be updated by load_settings
        self.current_state = STATE_IDLE
        self.remaining_seconds = 0 # Will be set based on focus_duration
        self.current_phase_total_seconds = 0 # Will be set based on focus_duration
        self.focus_seconds_when_break_started = 0

        # Initialize fixed mode state BEFORE loading settings
        self.is_fixed_mode_enabled = False

        # Load settings, including fixed mode state
        self.load_settings() # Now loads fixed mode setting

        # UI Initialization depends on loaded settings (e.g., initial timer value, fixed mode checkbox state)
        self.init_ui()

        # Initialize timers, sound system
        self.init_timers()
        self.init_sound()

        # Apply settings and update UI based on initial state
        self.apply_settings_update(initial_load=True) # Sets initial timer display etc.
        self.update_ui_for_state() # Sets initial button states etc.

    # --- Settings Load/Save/Apply (MODIFIED - Added Fixed Mode) ---
    def load_settings(self):
        """Loads settings from QSettings or uses defaults."""
        self.focus_duration = self.settings.value("focus_duration", DEFAULT_FOCUS_MINUTES, type=int)
        self.short_break_duration = self.settings.value("short_break_duration", DEFAULT_SHORT_BREAK_SECONDS, type=int)
        self.sb_trigger_max = self.settings.value("sb_trigger_max", DEFAULT_SHORT_BREAK_MAX_TRIGGER_MINUTES, type=int)
        self.long_break_duration = self.settings.value("long_break_duration", DEFAULT_LONG_BREAK_MINUTES, type=int)
        self.notification_sound_path = self.settings.value(SETTINGS_SOUND_KEY, None)
        # Load fixed mode setting (default to False if not found)
        self.is_fixed_mode_enabled = self.settings.value(SETTINGS_FIXED_MODE_KEY, False, type=bool) # Use new key

        print("[Settings] Loaded settings:", {
            k: getattr(self, k, None) for k in [
                "focus_duration", "short_break_duration", "sb_trigger_max",
                "long_break_duration", "notification_sound_path", "is_fixed_mode_enabled" # Added fixed mode
            ]
        })

        # Apply Basic Validation
        self.focus_duration = max(1, self.focus_duration)
        self.short_break_duration = max(1, self.short_break_duration)
        self.long_break_duration = max(1, self.long_break_duration)
        self.sb_trigger_max = max(1, self.sb_trigger_max)

    def save_settings(self, settings_dict):
        """Saves the validated settings dictionary (from dialog) to QSettings."""
        print("[Settings] Saving settings from dialog:", settings_dict)
        sound_path = settings_dict.get(SETTINGS_SOUND_KEY)

        # Update instance variables from validated dict
        self.focus_duration = max(1, settings_dict.get("focus_duration", self.focus_duration))
        self.short_break_duration = max(1, settings_dict.get("short_break_duration", self.short_break_duration))
        self.long_break_duration = max(1, settings_dict.get("long_break_duration", self.long_break_duration))
        self.sb_trigger_max = max(1, settings_dict.get("sb_trigger_max", self.sb_trigger_max))
        self.notification_sound_path = sound_path
        # Fixed mode is NOT saved via this dialog, but via checkbox directly

        # Save to QSettings
        self.settings.setValue("focus_duration", self.focus_duration)
        self.settings.setValue("short_break_duration", self.short_break_duration)
        self.settings.setValue("long_break_duration", self.long_break_duration)
        self.settings.setValue("sb_trigger_max", self.sb_trigger_max)
        if self.notification_sound_path:
            print(f"[Settings] Saving sound path: {self.notification_sound_path}")
            self.settings.setValue(SETTINGS_SOUND_KEY, self.notification_sound_path)
        else:
            print("[Settings] No valid sound path to save, removing key.")
            self.settings.remove(SETTINGS_SOUND_KEY)
        # Don't save fixed mode here, it's saved by checkbox handler

        self.settings.sync()
        self.apply_settings_update() # Apply changes immediately

    def apply_settings_update(self, initial_load=False):
        """Applies loaded/saved settings to the application state and UI."""
        print("[App] Applying settings update...");
        self.init_sound() # Re-init sound in case path changed

        # Set the checkbox state based on the loaded/current value
        # Need to ensure checkbox exists first (might be called before init_ui)
        if hasattr(self, 'fixed_mode_checkbox'):
            self.fixed_mode_checkbox.setChecked(self.is_fixed_mode_enabled)
            print(f"[App] Setting checkbox checked state to: {self.is_fixed_mode_enabled}")


        # Reset timer visuals only if idle or on initial load
        if self.current_state == STATE_IDLE or initial_load:
            print("[App] State Idle/Initial, resetting visuals.");
            self.reset_to_idle_state(update_ui=False) # Prevent double update
        elif self.current_state == STATE_PAUSED:
            # Update total duration if focus duration changed while paused
            # Check if we can update based on fixed mode (cannot update if fixed mode was ON when focus started)
            # Note: Dragging itself is prevented during pause if fixed mode is on,
            # but settings dialog could change focus_duration. This check handles that.
             print("[App] State Paused, updating visuals.");
             # If fixed mode is ON, the total duration should remain what it was when focus started.
             # If fixed mode is OFF, allow focus_duration from settings to potentially change the total.
             if not self.is_fixed_mode_enabled:
                 self.current_phase_total_seconds = self.focus_duration * 60;
                 self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds);
             # Always update display time
             self.timer_widget.set_display_time(self.remaining_seconds)

        self.update_ui_for_state() # Ensure UI always updates state (buttons etc.)

    # --- UI Initialization (MODIFIED - Added Checkbox) ---
    def init_ui(self):
        self.setWindowTitle("专注时钟"); self.setGeometry(300, 300, 400, 500); central_widget = QWidget(self); self.setCentralWidget(central_widget); palette = central_widget.palette(); palette.setColor(QPalette.ColorRole.Window, QColor(Qt.GlobalColor.white)); central_widget.setAutoFillBackground(True); central_widget.setPalette(palette); main_layout = QVBoxLayout(central_widget); main_layout.setContentsMargins(15, 10, 15, 15)

        # --- Top Bar Layout ---
        top_bar_layout = QHBoxLayout()

        # Add Fixed Mode Checkbox (Left)
        self.fixed_mode_checkbox = QCheckBox("固定模式")
        self.fixed_mode_checkbox.setToolTip("启用后，短休息将在最晚时间触发，且专注开始后无法修改时长")
        self.fixed_mode_checkbox.setChecked(self.is_fixed_mode_enabled) # Set initial state from loaded settings
        self.fixed_mode_checkbox.stateChanged.connect(self._handle_fixed_mode_changed)
        top_bar_layout.addWidget(self.fixed_mode_checkbox)

        top_bar_layout.addStretch(1); # Stretch between checkbox and settings

        # Settings Button (Right)
        self.settings_button = QPushButton(); self.settings_button.setToolTip("打开设置"); self.settings_button.setFixedSize(QSize(32, 32)); self.settings_button.setStyleSheet("QPushButton { border: none; background-color: transparent; }"); self.settings_button.clicked.connect(self.open_settings_dialog);
        top_bar_layout.addWidget(self.settings_button)
        main_layout.addLayout(top_bar_layout)

        # --- Icon Loading (Unchanged) ---
        default_app_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon); app_icon = default_app_icon; self.app_icon_path = None; settings_icon_filename = "settings.png"
        try:
            script_dir = os.path.dirname(os.path.realpath(__file__)); potential_path = os.path.join(script_dir, settings_icon_filename)
            if os.path.exists(potential_path): self.app_icon_path = os.path.abspath(potential_path); app_icon = QIcon(self.app_icon_path); print(f"[UI] Found settings icon: {self.app_icon_path}"); self.settings_button.setIcon(app_icon); self.settings_button.setIconSize(QSize(24, 24))
            else:
                 # Check if running as a bundled executable (PyInstaller)
                 if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                      bundle_dir = sys._MEIPASS; potential_bundle_path = os.path.join(bundle_dir, settings_icon_filename)
                      if os.path.exists(potential_bundle_path):
                           self.app_icon_path = os.path.abspath(potential_bundle_path); app_icon = QIcon(self.app_icon_path); print(f"[UI] Found bundled icon: {self.app_icon_path}"); self.settings_button.setIcon(app_icon); self.settings_button.setIconSize(QSize(24, 24))
                      else: print(f"[UI] Icon not found in bundle. Using text."); self.settings_button.setText("⚙️"); self.settings_button.setFont(QFont("Arial", 16))
                 else: print(f"[UI] Icon not found. Using text."); self.settings_button.setText("⚙️"); self.settings_button.setFont(QFont("Arial", 16))
        except Exception as e: print(f"[UI] Error finding icon: {e}. Using text."); self.settings_button.setText("⚙️"); self.settings_button.setFont(QFont("Arial", 16))
        self.setWindowIcon(app_icon)

        # --- Timer Widget (Unchanged setup) ---
        self.timer_widget = CircularTimer(self); self.timer_widget.time_changed_by_drag.connect(self.handle_timer_drag); main_layout.addWidget(self.timer_widget, 1)

        # --- Controls Container (Unchanged setup) ---
        self.controls_container = QWidget(); self.controls_layout = QHBoxLayout(self.controls_container); self.controls_layout.setContentsMargins(0, 10, 0, 0); self.controls_layout.setSpacing(10)
        self.start_skip_button = QPushButton(); self.start_skip_button.setMinimumSize(140, 45)
        self.start_skip_button.setStyleSheet("""QPushButton { background-color: #007BFF; color: white; padding: 10px 20px; font-size: 16px; border: none; border-radius: 5px; } QPushButton:hover { background-color: #0056b3; } QPushButton:pressed { background-color: #004085; } QPushButton:disabled { background-color: #cccccc; color: #666666; }""")
        self.start_skip_button.clicked.connect(self.handle_start_skip_click); self.controls_layout.addWidget(self.start_skip_button, 0, Qt.AlignmentFlag.AlignCenter)
        self.focus_controls_widget = QWidget(); focus_controls_layout = QHBoxLayout(self.focus_controls_widget); focus_controls_layout.setContentsMargins(0, 0, 0, 0); focus_controls_layout.setSpacing(10); focus_controls_layout.addStretch()
        self.pause_continue_button = QPushButton(); self.pause_continue_button.setMinimumSize(110, 45)
        self.pause_continue_button.setStyleSheet("""QPushButton { background-color: #ffc107; color: black; padding: 10px 15px; font-size: 16px; border: none; border-radius: 5px; } QPushButton:hover { background-color: #e0a800; } QPushButton:pressed { background-color: #c69500; }""")
        self.pause_continue_button.clicked.connect(self.handle_pause_continue_click)
        self.end_focus_button = QPushButton("结束"); self.end_focus_button.setMinimumSize(90, 45)
        self.end_focus_button.setStyleSheet("""QPushButton { background-color: #dc3545; color: white; padding: 10px 15px; font-size: 16px; border: none; border-radius: 5px; } QPushButton:hover { background-color: #c82333; } QPushButton:pressed { background-color: #b02a37; }""")
        self.end_focus_button.clicked.connect(self.handle_end_focus_click)
        focus_controls_layout.addWidget(self.pause_continue_button); focus_controls_layout.addWidget(self.end_focus_button); focus_controls_layout.addStretch()
        self.controls_layout.addWidget(self.focus_controls_widget); self.focus_controls_widget.setVisible(False); main_layout.addWidget(self.controls_container, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)

        # --- Tray Icon (Unchanged setup) ---
        self.init_tray_icon(app_icon)

    # --- NEW Checkbox Handler ---
    def _handle_fixed_mode_changed(self, state):
        """Updates the fixed mode state and saves it to settings."""
        self.is_fixed_mode_enabled = (state == Qt.CheckState.Checked.value)
        print(f"[App] Fixed Mode {'Enabled' if self.is_fixed_mode_enabled else 'Disabled'}")
        self.settings.setValue(SETTINGS_FIXED_MODE_KEY, self.is_fixed_mode_enabled)
        self.settings.sync()
        # Optionally update UI elements if behavior needs to change immediately
        # (e.g., disable dragging even if idle, but current spec allows dragging before start)
        # The main effect (break scheduling) happens on next focus start.
        # update_ui_for_state() will manage the checkbox enable state correctly.
        # self.update_ui_for_state() # Ensure checkbox enabled state updates correctly if needed

    # --- Tray Icon Methods (Unchanged) ---
    def init_tray_icon(self, icon):
        if QSystemTrayIcon.isSystemTrayAvailable(): print("[Tray] System tray available."); self.tray_icon = QSystemTrayIcon(icon, self); self.tray_icon.setToolTip("专注时钟"); self.tray_icon.show(); self.tray_icon.activated.connect(self.handle_tray_activation)
        else: print("[Tray] System tray not available."); self.tray_icon = None

    def handle_tray_activation(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isHidden(): self.showNormal(); self.activateWindow()
            else: self.hide()

    # --- Notification Method (Unchanged) ---
    def _show_notification(self, title, message, icon=None, duration=NOTIFICATION_DURATION_MS):
        """Shows a VISUAL notification, using win11toast in a separate thread on Windows if available."""
        def show_toast_thread():
            print(f"[Toast Thread] Attempting win11toast.toast: '{title}'")
            toast_shown_successfully = False
            try:
                # Try the simpler .toast first if the library supports it directly
                print(f"[Toast Thread] Calling win11toast.toast(...) with: title='{title}', msg='{message}', audio={{'silent': 'true'}}")
                # Ensure audio is explicitly silenced for the visual toast
                win11toast.toast(title, message, audio={'silent': 'true'}, app_id="专注时钟")
                print("[Toast Thread] Toast call completed.")
                toast_shown_successfully = True
            except AttributeError:
                 print(f"[Toast Thread] Info: The imported 'win11toast' module might not have a direct '.toast' function. Trying 'show_toast'...")
                 try:
                    toast_duration = 'short' if duration <= 7000 else 'long'
                    # Ensure icon path is valid or empty string
                    icon_path_to_use = self.app_icon_path if self.app_icon_path and os.path.exists(self.app_icon_path) else ''
                    # Build arguments dictionary for show_toast
                    toast_args = {
                        'title': title, 'msg': message, 'icon_path': icon_path_to_use,
                        'duration': toast_duration,
                        'audio': None, # Let show_toast handle default sound or silence
                        'app_id': "专注时钟"
                    }
                    print(f"[Toast Thread] Calling win11toast.show_toast with args: {toast_args}")
                    win11toast.show_toast(**toast_args)
                    print("[Toast Thread] Fallback toast sent using show_toast.")
                    toast_shown_successfully = True
                 except Exception as e_fallback:
                      print(f"[Toast Thread] Error showing fallback win11toast notification via show_toast: {e_fallback}")
                      toast_shown_successfully = False
            except Exception as e:
                print(f"[Toast Thread] Error showing win11toast notification: {e}")
                toast_shown_successfully = False

            if not toast_shown_successfully:
                 print(f"[Toast Thread] All win11toast attempts failed for: '{title}'. Falling back to Tray if available.")
                 # Fallback to tray from within the thread might be complex due to Qt context.
                 # Better to handle fallback in the main thread if thread creation fails or if toast lib fails AND tray exists.

        if _Win11ToastImported:
            print(f"[Toast] Creating and starting notification thread for: '{title}'")
            try:
                thread = threading.Thread(target=show_toast_thread)
                thread.daemon = True
                thread.start()
                print("[Toast] Notification thread started.")
            except Exception as e_main:
                print(f"[Toast] Error creating/starting notification thread: {e_main}")
                if self.tray_icon and self.tray_icon.isVisible():
                     print("[Tray] Thread error, falling back to QSystemTrayIcon.");
                     self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, duration)
        elif self.tray_icon and self.tray_icon.isVisible():
            print(f"[Tray] Falling back to QSystemTrayIcon: '{title}' - '{message}'")
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, duration)
        else:
             print(f"[Notification] No visual method available (No win11toast/No Tray). Skipping: '{title}'")

    # --- Timer Initialization (Unchanged) ---
    def init_timers(self):
        self.main_timer = QTimer(self); self.main_timer.setInterval(1000); self.main_timer.timeout.connect(self.update_countdown)
        self.short_break_scheduler = QTimer(self); self.short_break_scheduler.setSingleShot(True); self.short_break_scheduler.timeout.connect(self.trigger_short_break)

    # --- Sound Initialization and Playback (Unchanged) ---
    def init_sound(self):
        print("[Sound] Initializing sound system...");
        if hasattr(self, 'sound_effect') and self.sound_effect: print("[Sound] Stopping existing sound effect."); self.sound_effect.stop()
        self.sound_effect = QSoundEffect(self); self.sound_file_valid = False; sound_path = self.notification_sound_path
        if not sound_path: print("[Sound] No sound path."); self.sound_effect.setSource(QUrl()); return
        print(f"[Sound] Path: '{sound_path}'");
        if not os.path.exists(sound_path): print(f"[Sound] ERROR: Not found."); self.sound_effect.setSource(QUrl()); return
        if not os.path.isfile(sound_path): print(f"[Sound] ERROR: Not a file."); self.sound_effect.setSource(QUrl()); return
        print(f"[Sound] Creating QUrl...");
        try: abs_sound_path = os.path.abspath(sound_path); print(f"[Sound] Abs Path: {abs_sound_path}"); file_url = QUrl.fromLocalFile(abs_sound_path)
        except Exception as e: print(f"[Sound] ERROR QUrl: {e}"); self.sound_effect.setSource(QUrl()); return
        if not file_url.isValid(): print(f"[Sound] ERROR: Invalid QUrl"); self.sound_effect.setSource(QUrl()); return
        if file_url.isEmpty(): print(f"[Sound] ERROR: Empty QUrl"); self.sound_effect.setSource(QUrl()); return
        print(f"[Sound] QUrl OK: {file_url.toString()}"); print(f"[Sound] Setting source..."); self.sound_effect.setSource(file_url)
        status = self.sound_effect.status(); print(f"[Sound] Status after setSource: {status}")
        if status == QSoundEffect.Status.Error: print("[Sound] ERROR: Load failed."); self.sound_effect.setSource(QUrl()); return
        elif status == QSoundEffect.Status.Loading: print("[Sound] Loading...")
        elif status == QSoundEffect.Status.Ready: print("[Sound] Ready.")
        else: print(f"[Sound] Warn: Status {status}")
        print(f"[Sound] Source set: {self.sound_effect.source().toLocalFile()}"); self.sound_file_valid = True; self.sound_effect.setVolume(0.8); print("[Sound] Init OK.")

    def _play_notification_sound(self, context=""):
        print(f"[Sound] Playback: '{context}'");
        if not self.sound_file_valid: print(f"[Sound] Skip: Invalid file."); return
        if not hasattr(self, 'sound_effect') or not self.sound_effect: print(f"[Sound] Skip: No object."); self.sound_file_valid = False; return
        status = self.sound_effect.status(); print(f"[Sound] Status before play: {status}")
        if status != QSoundEffect.Status.Ready:
            print(f"[Sound] Skip: Not Ready (Status: {status}).")
            if status == QSoundEffect.Status.Error:
                print("[Sound] Status is Error, marking sound as invalid.")
                self.sound_file_valid = False
            return
        source_url = self.sound_effect.source();
        if not source_url.isValid() or source_url.isEmpty(): print(f"[Sound] Skip: Invalid source."); self.sound_file_valid = False; return
        print(f"[Sound] Playing: {source_url.fileName()}")
        try: self.sound_effect.play()
        except Exception as e: print(f"[Sound] ERROR Play: {e}"); self.sound_file_valid = False

    # --- Drag Handling (Modified - Added Fixed Mode Check) ---
    def handle_timer_drag(self, minutes):
        # Ignore drag updates if we are currently in a focus state AND fixed mode is enabled
        # Also ignore if not in idle or paused state (standard behavior)
        # Note: Timer widget itself prevents dragging when 'is_running' is True (Focus/Break states)
        # This check primarily prevents applying a drag update during PAUSED state if fixed mode is ON,
        # or if somehow a drag event got through during FOCUS with fixed mode.
        if (self.is_fixed_mode_enabled and self.current_state == STATE_FOCUS) or \
           self.current_state not in [STATE_IDLE, STATE_PAUSED]:
            print(f"[App] Drag ignored. FixedModeActive={self.is_fixed_mode_enabled}, State={self.current_state}")
            # Reset the visual to match the actual remaining time if paused
            if self.current_state == STATE_PAUSED:
                self.timer_widget.set_display_time(self.remaining_seconds)
            return # Prevent updating focus duration via drag

        # If allowed (idle/paused AND fixed mode off, or just idle), proceed
        clamped_minutes = max(1, minutes) # Ensure minimum 1 minute from drag
        if self.focus_duration != clamped_minutes:
            print(f"[App] Dragged: {clamped_minutes}m")
            self.focus_duration = clamped_minutes
            self.current_phase_total_seconds = self.focus_duration * 60
            self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds)

        if self.current_state == STATE_IDLE:
            # Update remaining time only if idle (paused keeps its remaining time)
            self.remaining_seconds = self.current_phase_total_seconds
            self.timer_widget.set_display_time(self.remaining_seconds) # Update display immediately for idle
        elif self.current_state == STATE_PAUSED:
             # If paused AND fixed mode is OFF, dragging should update the total time
             # but keep the remaining time. Display updates happen below.
             pass # Logic above already updated total_seconds

        self.timer_widget.update() # Update visual arc


    # --- Button Click Handlers (Unchanged) ---
    def handle_start_skip_click(self):
        print("--- handle_start_skip_click called ---")
        print(f"    Current state is: {self.current_state} (Idle={STATE_IDLE}, ShortBreak={STATE_SHORT_BREAK}, LongBreak={STATE_LONG_BREAK})")
        if self.current_state == STATE_IDLE:
            print("    State is IDLE, calling start_focus()...")
            self.start_focus()
        elif self.current_state in [STATE_SHORT_BREAK, STATE_LONG_BREAK]:
            print("    State is BREAK, calling end_break_early()...")
            self.end_break_early()
        else: print(f"    State is {self.current_state}, doing nothing in handle_start_skip_click.")
        print("--- handle_start_skip_click finished ---")

    def handle_pause_continue_click(self):
        print("--- handle_pause_continue_click called ---")
        print(f"    Current state: {self.current_state} (Focus={STATE_FOCUS}, Paused={STATE_PAUSED})")
        if self.current_state == STATE_FOCUS: print("    State is FOCUS, calling pause_focus()..."); self.pause_focus()
        elif self.current_state == STATE_PAUSED: print("    State is PAUSED, calling resume_focus()..."); self.resume_focus()
        else: print(f"    State is {self.current_state}, doing nothing.")
        print("--- handle_pause_continue_click finished ---")

    def handle_end_focus_click(self):
        print("--- handle_end_focus_click called ---")
        print(f"    Current state: {self.current_state} (Focus={STATE_FOCUS}, Paused={STATE_PAUSED})")
        if self.current_state in [STATE_FOCUS, STATE_PAUSED]: print("    State is FOCUS or PAUSED, calling end_focus_immediately()..."); self.end_focus_immediately()
        else: print(f"    State is {self.current_state}, doing nothing.")
        print("--- handle_end_focus_click finished ---")

    # --- State Transition Methods (Unchanged - Logic adapted via fixed mode check elsewhere) ---
    def start_focus(self):
        print("--- start_focus called ---")
        if self.current_state != STATE_IDLE: print(f"    ERROR in start_focus: Current state ({self.current_state}) is not IDLE. Returning."); return

        print("    Setting state to FOCUS...")
        self.current_state = STATE_FOCUS
        # Use the focus_duration set *before* starting (either default, loaded, settings, or drag)
        self.focus_duration = max(1, self.focus_duration) # Ensure at least 1 min
        self.current_phase_total_seconds = self.focus_duration * 60
        self.remaining_seconds = self.current_phase_total_seconds
        print(f"    Session details: Duration={self.focus_duration}m, TotalSeconds={self.current_phase_total_seconds}, Remaining={self.remaining_seconds}")
        if self.is_fixed_mode_enabled:
            print("    Fixed Mode is ON: Focus duration is now locked for this session. Short breaks will be fixed.")
        else:
            print("    Fixed Mode is OFF: Short breaks will use progressive timing.")

        print("    Updating timer widget visuals...")
        self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds)
        self.timer_widget.set_break_phase(False)
        self.timer_widget.set_display_time(self.remaining_seconds)
        self.timer_widget.outer_color = QColor("#A0D2EB")
        self.timer_widget.set_running(True) # set_running automatically prevents dragging in CircularTimer

        print("    Starting main timer...")
        self.main_timer.start()

        print("    Scheduling next short break...")
        self.schedule_next_short_break() # Schedule logic will check fixed mode

        print("    Updating UI for state (disables settings/checkbox/drag)...")
        self.update_ui_for_state()
        print("--- start_focus finished ---")

    def pause_focus(self):
        print("--- pause_focus called ---")
        if self.current_state != STATE_FOCUS: print(f"    ERROR in pause_focus: Current state ({self.current_state}) is not FOCUS. Returning."); return
        print("    Setting state to PAUSED...")
        self.current_state = STATE_PAUSED
        print("    Stopping main timer...")
        self.main_timer.stop()
        print("    Stopping short break scheduler...")
        self.short_break_scheduler.stop()
        print("    Updating timer widget running state to False...")
        self.timer_widget.set_running(False) # Allows dragging again IF NOT fixed mode
        self.timer_widget.set_break_phase(False)
        print("    Updating UI for state...")
        self.update_ui_for_state() # Enables settings button & checkbox again
        print("--- pause_focus finished ---")

    def resume_focus(self):
        print("--- resume_focus called ---")
        if self.current_state != STATE_PAUSED: print(f"    ERROR in resume_focus: Current state ({self.current_state}) is not PAUSED. Returning."); return
        if self.remaining_seconds <= 0: print("    Cannot resume, no time left. Resetting."); self.reset_to_idle_state(update_ui=True); return
        print(f"    Resuming focus with {self.remaining_seconds} seconds left...")
        print("    Setting state to FOCUS...")
        self.current_state = STATE_FOCUS
        print("    Updating timer widget visuals...")
        self.timer_widget.set_break_phase(False)
        self.timer_widget.set_running(True) # Re-disables dragging
        print("    Starting main timer...")
        self.main_timer.start()
        print("    Rescheduling next short break...")
        self.schedule_next_short_break() # Uses fixed mode if enabled
        print("    Updating UI for state...")
        self.update_ui_for_state() # Re-disables settings/checkbox
        print("--- resume_focus finished ---")

    def end_focus_immediately(self):
        print("--- end_focus_immediately called ---")
        if self.current_state not in [STATE_FOCUS, STATE_PAUSED]: print(f"    ERROR in end_focus_immediately: Current state ({self.current_state}) is not FOCUS or PAUSED. Returning."); return
        print("    State is valid for ending focus."); print("    Playing sound..."); self._play_notification_sound("Focus Manually Ended"); print("    Showing notification..."); self._show_notification("专注结束", "专注时段已手动结束。"); print("    Resetting to idle state..."); self.reset_to_idle_state(update_ui=True);
        print("--- end_focus_immediately finished ---")

    def reset_to_idle_state(self, update_ui=False):
        print("[State] Resetting to idle state."); self.main_timer.stop(); self.short_break_scheduler.stop();
        if hasattr(self, 'sound_effect') and self.sound_effect: self.sound_effect.stop();
        self.current_state = STATE_IDLE;
        # Reset timer based on current focus_duration setting
        # This focus_duration might have been changed via drag or settings *before* the last focus session
        self.focus_duration = max(1, self.settings.value("focus_duration", DEFAULT_FOCUS_MINUTES, type=int)) # Reload from settings to be sure
        self.current_phase_total_seconds = self.focus_duration * 60;
        self.remaining_seconds = self.current_phase_total_seconds;
        # Update timer widget visuals
        self.timer_widget.set_break_phase(False);
        self.timer_widget.set_running(False); # Allows dragging again
        self.timer_widget.outer_color = QColor("#A0D2EB");
        self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds);
        self.timer_widget.set_time(self.focus_duration) # Use set_time to update internal minutes and display
        # self.timer_widget.set_display_time(self.remaining_seconds); # set_time handles this

        if update_ui: self.update_ui_for_state() # Updates buttons/checkbox enabled state

    def end_break_early(self):
        if self.current_state not in [STATE_SHORT_BREAK, STATE_LONG_BREAK]: return
        break_type = "短" if self.current_state == STATE_SHORT_BREAK else "长"
        print(f"[State] Ending {break_type}休息 early (skipped)..."); self.main_timer.stop()
        if hasattr(self, 'sound_effect') and self.sound_effect: self.sound_effect.stop()
        self._play_notification_sound(f"{break_type} Break Skipped");
        if self.current_state == STATE_SHORT_BREAK:
            print("[State] Resuming focus from skipped short break."); self.current_state = STATE_FOCUS;
            if self.focus_seconds_when_break_started > 0: self.remaining_seconds = self.focus_seconds_when_break_started; print(f"[State] Restored remaining focus time to: {self.remaining_seconds}s")
            else: print("[State] Warn: Cannot restore focus time, using fallback (60s)."); self.remaining_seconds = 60
            # Use the focus duration that was active when the break *started* for the visual total
            # This value doesn't change during fixed mode, but might if settings were changed during pause without fixed mode
            original_focus_duration = self.settings.value("focus_duration", DEFAULT_FOCUS_MINUTES, type=int) # Or get from instance variable if more reliable
            self.current_phase_total_seconds = original_focus_duration * 60
            self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds)
            self.timer_widget.set_break_phase(False); self.timer_widget.set_display_time(self.remaining_seconds); self.timer_widget.outer_color = QColor("#A0D2EB"); self.timer_widget.set_running(True); # Resuming focus, disable dragging
            self.main_timer.start(); print(f"[State] Scheduling next short break."); self.schedule_next_short_break(); # Reschedule potentially
            self._show_notification("恢复专注", f"已跳过{break_type}休息，继续专注。")
        elif self.current_state == STATE_LONG_BREAK:
            print("[State] Returning to idle from skipped long break."); self._show_notification("返回空闲", f"已跳过{break_type}休息。"); self.reset_to_idle_state(update_ui=True)
        self.update_ui_for_state()

    # --- Break Calculation (Unchanged) ---
    def _calculate_next_break_delay(self, max_seconds: int, mean_ratio: float = 25 / 30, beta_param: float = 1.0) -> int:
        if max_seconds <= 0: print("[Scheduler] Warning: max_seconds <= 0，立即觸發"); return 1
        mean_ratio = max(0.01, min(mean_ratio, 0.99)); target_mean_sec = int(mean_ratio * max_seconds); target_mean_sec = max(1, min(target_mean_sec, max_seconds - 1));
        # Adjust alpha/beta slightly to avoid extremes near 0 or max_seconds too often
        alpha_param = (mean_ratio * beta_param) / (1 - mean_ratio);
        alpha_param = max(0.5, alpha_param) # Prevent alpha getting too close to 0
        beta_param = max(0.5, beta_param)   # Prevent beta getting too close to 0
        x = random.betavariate(alpha_param, beta_param);
        delay = max(1, int(round(x * max_seconds)));
        return min(delay, max_seconds) # Ensure delay doesn't exceed max

    # --- MODIFIED Break Scheduling Logic (Checks Fixed Mode) ---
    def schedule_next_short_break(self):
        """Schedules the short break timer using fixed time or progressive probability."""
        self.short_break_scheduler.stop()

        if self.current_state != STATE_FOCUS or self.remaining_seconds <= 0:
            print("[Scheduler] Not scheduling break (not in focus or no time left).")
            return # Not in focus or no time left

        max_trigger_sec = max(1, self.sb_trigger_max * 60)
        focus_duration_until_break_sec = 0

        # --- FIXED MODE CHECK ---
        if self.is_fixed_mode_enabled:
            focus_duration_until_break_sec = max_trigger_sec # Use the exact max time
            print(f"[Scheduler] Fixed Mode ON: Using fixed break delay: {focus_duration_until_break_sec}s ({self.sb_trigger_max} min)")
        else:
            # Use the progressive probability method
            focus_duration_until_break_sec = self._calculate_next_break_delay(max_trigger_sec)
            print(f"[Scheduler] Fixed Mode OFF: Calculated next break delay (progressive): {focus_duration_until_break_sec}s (Max possible: {max_trigger_sec}s)")
        # --- END FIXED MODE CHECK ---

        # Check if there's enough remaining focus time for this break delay
        # Add a small buffer (e.g., 1 second) to prevent scheduling a break *exactly* when focus ends
        if focus_duration_until_break_sec < self.remaining_seconds - 1:
             delay_ms = int(focus_duration_until_break_sec * 1000)
             print(f"[Scheduler] Scheduling next short break to trigger in {focus_duration_until_break_sec:.0f} seconds ({delay_ms} ms).")
             self.short_break_scheduler.start(delay_ms)
        else:
             print(f"[Scheduler] Skipping short break schedule: Required delay ({focus_duration_until_break_sec}s) >= remaining focus time ({self.remaining_seconds}s). Focus will end first.")

    # --- Trigger/Start Breaks (Unchanged) ---
    def trigger_short_break(self):
        if self.current_state != STATE_FOCUS: print("[State] Ignored short break trigger: Not in focus."); return;
        if self.remaining_seconds <= 0: print("[State] Ignored short break trigger: Focus time already expired."); return;
        print("[State] Triggering short break..."); self.main_timer.stop(); self.short_break_scheduler.stop(); # Stop scheduler too
        self.focus_seconds_when_break_started = self.remaining_seconds; # Store remaining focus time
        self.current_state = STATE_SHORT_BREAK; self.short_break_duration = max(1, self.settings.value("short_break_duration", DEFAULT_SHORT_BREAK_SECONDS, type=int)); # Reload duration
        self.current_phase_total_seconds = self.short_break_duration; self.remaining_seconds = self.current_phase_total_seconds;
        self._play_notification_sound("Short Break Start");
        self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds); self.timer_widget.set_break_phase(True); self.timer_widget.set_display_time(self.remaining_seconds); self.timer_widget.outer_color = QColor("#FFD700"); self.timer_widget.set_running(True); # Break running, disable drag
        self._show_notification("短休息时间！", f"现在开始 {self.short_break_duration} 秒的短休息.");
        self.main_timer.start(); self.update_ui_for_state()

    def start_long_break(self):
        print("[State] Focus finished. Starting long break..."); self.short_break_scheduler.stop(); self.current_state = STATE_LONG_BREAK; self.long_break_duration = max(1, self.settings.value("long_break_duration", DEFAULT_LONG_BREAK_MINUTES, type=int)); # Reload duration
        self.current_phase_total_seconds = self.long_break_duration * 60; self.remaining_seconds = self.current_phase_total_seconds;
        self._play_notification_sound("Long Break Start");
        self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds); self.timer_widget.set_break_phase(True); self.timer_widget.set_display_time(self.remaining_seconds); self.timer_widget.outer_color = QColor("#90EE90"); self.timer_widget.set_running(True); # Break running, disable drag
        self._show_notification("长休息时间！", f"现在开始 {self.long_break_duration} 分钟的长休息。");
        self.main_timer.start(); self.update_ui_for_state()

    # --- update_countdown (Unchanged Logic - Relies on Correct State Transitions) ---
    def update_countdown(self):
        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self.timer_widget.set_display_time(self.remaining_seconds)
            # Optional: Update tray tooltip with remaining time
            # if self.tray_icon:
            #     minutes = self.remaining_seconds // 60
            #     seconds = self.remaining_seconds % 60
            #     state_str = {STATE_FOCUS: "Focus", STATE_SHORT_BREAK: "Short Break", STATE_LONG_BREAK: "Long Break"}.get(self.current_state, "Idle")
            #     self.tray_icon.setToolTip(f"专注时钟 - {state_str}: {minutes:02d}:{seconds:02d}")

        else: # remaining_seconds <= 0
            self.main_timer.stop()
            phase_when_finished = self.current_state
            # Stop sound just in case it was playing somehow
            if hasattr(self, 'sound_effect') and self.sound_effect: self.sound_effect.stop()

            if phase_when_finished == STATE_FOCUS:
                print("[State] Focus time finished naturally.");
                self.short_break_scheduler.stop(); # Ensure scheduler is stopped
                self.start_long_break() # Transition to long break

            elif phase_when_finished == STATE_SHORT_BREAK:
                print("[State] Short break finished.");
                self._play_notification_sound("Short Break End");
                self._show_notification("短休息结束", "准备恢复专注！");
                self.current_state = STATE_FOCUS; # Transition back to focus

                if self.focus_seconds_when_break_started > 0:
                    self.remaining_seconds = self.focus_seconds_when_break_started; # Restore remaining focus time
                    print(f"[State] Resuming focus with {self.remaining_seconds}s.")
                    # Restore the total duration for the visual arc
                    original_focus_duration = self.settings.value("focus_duration", DEFAULT_FOCUS_MINUTES, type=int) # Reload in case changed? Or use value from start_focus?
                    self.current_phase_total_seconds = original_focus_duration * 60 # Use initial focus total
                    self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds) # Set total for arc
                    self.timer_widget.set_break_phase(False);
                    self.timer_widget.set_display_time(self.remaining_seconds); # Set remaining time display
                    self.timer_widget.outer_color = QColor("#A0D2EB");
                    self.timer_widget.set_running(True); # Resume focus running state
                    self.main_timer.start();
                    print(f"[State] Scheduling next short break.");
                    self.schedule_next_short_break(); # Schedule the *next* break
                    self.update_ui_for_state() # Update buttons etc.
                else:
                    print("[State] Warn: Cannot restore focus time after short break (focus_seconds_when_break_started was 0). Resetting to Idle.");
                    self.reset_to_idle_state(update_ui=True)

            elif phase_when_finished == STATE_LONG_BREAK:
                print("[State] Long break finished.");
                self._play_notification_sound("Long Break End");
                self._show_notification("长休息结束", "准备好开始新的专注时段了吗？");
                self.reset_to_idle_state(update_ui=True) # Reset to idle after long break

            else: # Should not happen in normal operation
                print(f"[State] Timer finished unexpectedly in state: {phase_when_finished}. Resetting to Idle.");
                self.timer_widget.set_running(False);
                self.timer_widget.set_break_phase(False);
                self.reset_to_idle_state(update_ui=True)

    # --- UI Update (MODIFIED - Checkbox Enable State) ---
    def update_ui_for_state(self):
        is_idle = self.current_state == STATE_IDLE
        is_focus = self.current_state == STATE_FOCUS
        is_paused = self.current_state == STATE_PAUSED
        is_break = self.current_state in [STATE_SHORT_BREAK, STATE_LONG_BREAK]
        is_running_active_phase = is_focus or is_break # Check if *any* timer is actively running

        # Controls visibility
        self.start_skip_button.setVisible(is_idle or is_break)
        self.focus_controls_widget.setVisible(is_focus or is_paused)

        # Settings button enabled only when idle or paused
        self.settings_button.setEnabled(is_idle or is_paused)

        # Fixed mode checkbox enabled only when idle or paused
        # (Prevents changing mode during an active session)
        if hasattr(self, 'fixed_mode_checkbox'): # Ensure checkbox exists
             self.fixed_mode_checkbox.setEnabled(is_idle or is_paused)

        # Button Texts and States
        if is_idle:
            self.start_skip_button.setText("开始专注")
            self.start_skip_button.setEnabled(True)
            if self.tray_icon: self.tray_icon.setToolTip("专注时钟 - 空闲")
        elif is_break:
            break_type = "短" if self.current_state == STATE_SHORT_BREAK else "长"
            self.start_skip_button.setText(f"跳过{break_type}休息")
            self.start_skip_button.setEnabled(True)
            if self.tray_icon: self.tray_icon.setToolTip(f"专注时钟 - {break_type}休息中")
        elif is_focus:
            self.pause_continue_button.setText("暂停专注")
            self.pause_continue_button.setEnabled(True)
            self.end_focus_button.setEnabled(True)
            if self.tray_icon: self.tray_icon.setToolTip("专注时钟 - 专注中")
        elif is_paused:
            self.pause_continue_button.setText("继续专注")
            self.pause_continue_button.setEnabled(True)
            self.end_focus_button.setEnabled(True)
            if self.tray_icon: self.tray_icon.setToolTip("专注时钟 - 已暂停")

        # Update timer widget visual state (important after state changes)
        # Ensure 'running' state reflects active phases, and break phase is set
        self.timer_widget.set_running(is_running_active_phase)
        self.timer_widget.set_break_phase(is_break)
        # Set colors based on state
        if is_idle or is_focus or is_paused:
            self.timer_widget.outer_color = QColor("#A0D2EB")
        elif self.current_state == STATE_SHORT_BREAK:
            self.timer_widget.outer_color = QColor("#FFD700") # Gold
        elif self.current_state == STATE_LONG_BREAK:
            self.timer_widget.outer_color = QColor("#90EE90") # Light Green
        self.timer_widget.update()


    # --- Settings Dialog Opener (Unchanged regarding fixed mode) ---
    def open_settings_dialog(self):
        if self.current_state not in [STATE_IDLE, STATE_PAUSED]:
             QMessageBox.warning(self, "无法打开设置", "请先结束或暂停当前活动，才能更改设置。");
             return;
        # Gather current settings *excluding* fixed mode for the dialog
        current_config = {
            "focus_duration": self.focus_duration,
            "short_break_duration": self.short_break_duration,
            "sb_trigger_max": self.sb_trigger_max,
            "long_break_duration": self.long_break_duration,
            SETTINGS_SOUND_KEY: self.notification_sound_path
        }
        dialog = SettingsDialog(current_config, self);
        dialog.settings_saved.connect(self.save_settings);
        dialog.exec()

    # --- Close Event (Unchanged) ---
    def closeEvent(self, event):
        print("[App] Closing application...");
        self.main_timer.stop();
        self.short_break_scheduler.stop()
        if hasattr(self, 'sound_effect') and self.sound_effect:
            self.sound_effect.stop()
        if self.tray_icon:
            self.tray_icon.hide()
        print("[App] Timers stopped, tray icon hidden.");
        self.settings.sync(); # Ensure settings (including fixed mode) are saved
        event.accept()


# --- Main Execution ---
if __name__ == '__main__':
    # Enable high DPI scaling for better visuals on modern displays
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setOrganizationName("MyCompany")
    app.setApplicationName("FocusTimerApp")
    app.setQuitOnLastWindowClosed(True) # Ensure app quits when window closes

    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())