# -*- coding: utf-8 -*-

import sys
import math
import random
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QDialog, QFormLayout, QLineEdit,
    QSpinBox, QFileDialog, QSizePolicy, QStyle, QFrame, QSpacerItem,
    QMessageBox
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QIcon, QPixmap, QPalette
)
from PyQt6.QtCore import (
    Qt, QTimer, QPointF, QRectF, QSettings, QUrl, QSize, pyqtSignal, QObject
)
# <<< Sound Import Still Enabled >>>
from PyQt6.QtMultimedia import QSoundEffect, QMediaPlayer, QAudioOutput

# --- Configuration Constants ---
DEFAULT_FOCUS_MINUTES = 90
DEFAULT_SHORT_BREAK_SECONDS = 10
DEFAULT_LONG_BREAK_MINUTES = 20
DEFAULT_SHORT_BREAK_MIN_TRIGGER_MINUTES = 3
DEFAULT_SHORT_BREAK_MAX_TRIGGER_MINUTES = 5
MAX_DRAGGABLE_MINUTES = 120
# NOTIFICATION_MAX_DURATION_MS = 5000 # No longer checked
SETTINGS_SOUND_KEY = "notification_sound_path"

# --- Application States ---
STATE_IDLE = 0
STATE_FOCUS = 1
STATE_SHORT_BREAK = 2
STATE_LONG_BREAK = 3
STATE_PAUSED = 4

# --- Helper Class for Audio Duration Check (No longer used for check) ---
class AudioChecker(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        print("AudioChecker initialized (Duration check disabled).")

# --- Circular Timer Widget (No changes) ---
class CircularTimer(QWidget):
    time_changed_by_drag = pyqtSignal(int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.max_minutes = MAX_DRAGGABLE_MINUTES
        self.current_minutes = min(DEFAULT_FOCUS_MINUTES, self.max_minutes)
        self.total_seconds_display = DEFAULT_FOCUS_MINUTES * 60
        self.is_running = False
        self.is_dragging = False
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
                self.update()

    def set_display_time(self, total_seconds):
        self.total_seconds_display = max(0, total_seconds)
        self.update()

    def set_actual_total_seconds(self, total_seconds):
        self.actual_total_seconds_for_phase = total_seconds
        self.update()

    def set_running(self, running):
        self.is_running = running
        self.update()

    def _angle_to_minutes(self, angle_degrees):
        math_angle = (360 - angle_degrees) % 360
        angle_from_12_cw = (math_angle + 90) % 360
        minutes = (angle_from_12_cw / 360.0) * self.max_minutes
        return max(0, min(self.max_minutes, round(minutes)))

    def _minutes_to_angle_span(self, minutes):
        clamped_minutes = max(0, min(self.max_minutes, minutes))
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
        force_full_visual = self.actual_total_seconds_for_phase > self.max_minutes * 60
        if self.current_minutes >= self.max_minutes or (self.is_running and force_full_visual):
             span_angle = -360 * 16
        elif self.current_minutes <= 0 and not self.is_dragging:
             span_angle = 0
        else:
             span_angle = self._minutes_to_angle_span(self.current_minutes)
        painter.drawArc(arc_rect, start_angle_qt, span_angle)
        painter.setPen(self.text_color)
        font = QFont("Arial", int(radius * 0.4), QFont.Weight.Bold)
        painter.setFont(font)
        display_minutes = self.total_seconds_display // 60
        display_seconds = self.total_seconds_display % 60
        time_str = f"{display_minutes:02}:{display_seconds:02}"
        painter.drawText(arc_rect, Qt.AlignmentFlag.AlignCenter, time_str)

    def mousePressEvent(self, event):
        if self.is_running: return
        pos = event.pos(); center = QPointF(self.rect().center()); radius = min(self.width(), self.height()) / 2.0 * 0.9; dist_sq = (pos.x() - center.x())**2 + (pos.y() - center.y())**2; outer_radius_sq = radius**2; inner_radius_sq = (radius * 0.7)**2
        if inner_radius_sq <= dist_sq <= outer_radius_sq:
            self.is_dragging = True; dx = pos.x() - center.x(); dy = pos.y() - center.y(); raw_qt_angle_deg = (-math.degrees(math.atan2(dy, dx)) + 360) % 360; new_minutes = self._angle_to_minutes(raw_qt_angle_deg)
            if new_minutes != self.current_minutes:
                self.current_minutes = new_minutes; self.total_seconds_display = self.current_minutes * 60; self.time_changed_by_drag.emit(self.current_minutes); self.update()
        else:
            self.is_dragging = False

    def mouseMoveEvent(self, event):
        if self.is_dragging and not self.is_running:
            pos = event.pos(); center = QPointF(self.rect().center()); dx = pos.x() - center.x(); dy = pos.y() - center.y(); raw_qt_angle_deg = (-math.degrees(math.atan2(dy, dx)) + 360) % 360; new_minutes = self._angle_to_minutes(raw_qt_angle_deg)
            if new_minutes != self.current_minutes:
                self.current_minutes = new_minutes; self.total_seconds_display = self.current_minutes * 60; self.time_changed_by_drag.emit(self.current_minutes); self.update()

    def mouseReleaseEvent(self, event):
        if self.is_dragging:
            self.is_dragging = False

# --- Settings Dialog (Duration Check Removed) ---
class SettingsDialog(QDialog):
    settings_saved = pyqtSignal(dict)

    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.current_settings = current_settings
        self.selected_audio_file_path = self.current_settings.get(SETTINGS_SOUND_KEY)
        self.audio_path_valid = bool(self.selected_audio_file_path and \
                                   os.path.exists(self.selected_audio_file_path) and \
                                   os.path.isfile(self.selected_audio_file_path))
        if not self.audio_path_valid:
            self.selected_audio_file_path = None

        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.focus_duration_input = QSpinBox(); self.focus_duration_input.setRange(1, 999); self.focus_duration_input.setSuffix(" 分钟"); self.focus_duration_input.setValue(self.current_settings.get("focus_duration", DEFAULT_FOCUS_MINUTES)); form_layout.addRow("专注时长:", self.focus_duration_input)
        self.short_break_duration_input = QSpinBox(); self.short_break_duration_input.setRange(1, 300); self.short_break_duration_input.setSuffix(" 秒"); self.short_break_duration_input.setValue(self.current_settings.get("short_break_duration", DEFAULT_SHORT_BREAK_SECONDS)); form_layout.addRow("短休息时长:", self.short_break_duration_input)
        self.sb_trigger_min_input = QSpinBox(); self.sb_trigger_min_input.setRange(1, 60); self.sb_trigger_min_input.setSuffix(" 分钟"); self.sb_trigger_min_input.setValue(self.current_settings.get("sb_trigger_min", DEFAULT_SHORT_BREAK_MIN_TRIGGER_MINUTES)); form_layout.addRow("短休息触发下限:", self.sb_trigger_min_input)
        self.sb_trigger_max_input = QSpinBox(); self.sb_trigger_max_input.setRange(1, 120); self.sb_trigger_max_input.setSuffix(" 分钟"); self.sb_trigger_max_input.setValue(self.current_settings.get("sb_trigger_max", DEFAULT_SHORT_BREAK_MAX_TRIGGER_MINUTES)); form_layout.addRow("短休息触发上限:", self.sb_trigger_max_input)
        self.long_break_duration_input = QSpinBox(); self.long_break_duration_input.setRange(1, 120); self.long_break_duration_input.setSuffix(" 分钟"); self.long_break_duration_input.setValue(self.current_settings.get("long_break_duration", DEFAULT_LONG_BREAK_MINUTES)); form_layout.addRow("长休息时长:", self.long_break_duration_input)
        self.sb_trigger_min_input.valueChanged.connect(self._validate_bounds); self.sb_trigger_max_input.valueChanged.connect(self._validate_bounds); self._validate_bounds()

        sound_widget = QWidget(); sound_v_layout = QVBoxLayout(sound_widget); sound_v_layout.setContentsMargins(0,0,0,0)
        self.sound_select_button = QPushButton("选择本地音频文件...")
        initial_label_text = "未选择文件 (需要选择)"; initial_label_style = "color: gray;"
        if self.audio_path_valid: initial_label_text = "当前: " + os.path.basename(self.selected_audio_file_path); initial_label_style = "color: green;"
        self.sound_file_label = QLabel(initial_label_text); self.sound_file_label.setStyleSheet(initial_label_style)
        sound_v_layout.addWidget(self.sound_select_button); sound_v_layout.addWidget(self.sound_file_label); form_layout.addRow("通知声音:", sound_widget); self.sound_select_button.clicked.connect(self.select_local_sound)
        layout.addLayout(form_layout)

        button_layout = QHBoxLayout(); self.back_button = QPushButton("返回"); self.save_button = QPushButton("保存"); self.save_button.setDefault(True); self.save_button.setEnabled(self.audio_path_valid); button_layout.addStretch(1); button_layout.addWidget(self.back_button); button_layout.addWidget(self.save_button); layout.addLayout(button_layout)
        self.back_button.clicked.connect(self.reject); self.save_button.clicked.connect(self.save_and_close)

    def _validate_bounds(self):
        min_val = self.sb_trigger_min_input.value(); max_val = self.sb_trigger_max_input.value()
        if max_val <= min_val: self.sb_trigger_max_input.setValue(min_val + 1)
        self.sb_trigger_max_input.setMinimum(self.sb_trigger_min_input.value() + 1); self.sb_trigger_min_input.setMaximum(self.sb_trigger_max_input.value() - 1)

    def select_local_sound(self):
        supported_formats = "音频文件 (*.wav *.mp3 *.ogg *.flac)"; start_dir = os.path.dirname(self.selected_audio_file_path) if self.selected_audio_file_path and os.path.exists(os.path.dirname(self.selected_audio_file_path)) else ""
        file_path, _ = QFileDialog.getOpenFileName(self, "选择音频文件", start_dir, supported_formats)
        if file_path:
            self.selected_audio_file_path = file_path; self.audio_path_valid = True; self.sound_file_label.setText("当前: " + os.path.basename(self.selected_audio_file_path)); self.sound_file_label.setStyleSheet("color: green;"); self.save_button.setEnabled(True); print(f"Sound file selected (no duration check): {file_path}")

    def save_and_close(self):
        if not self.selected_audio_file_path or not self.audio_path_valid: QMessageBox.warning(self, "保存错误", "请选择一个有效的本地音频文件。"); return
        min_trigger = self.sb_trigger_min_input.value(); max_trigger = self.sb_trigger_max_input.value()
        if min_trigger >= max_trigger: QMessageBox.warning(self, "保存错误", "短休息触发下限必须小于上限。"); return
        new_settings = {"focus_duration": self.focus_duration_input.value(), "short_break_duration": self.short_break_duration_input.value(), "sb_trigger_min": min_trigger, "sb_trigger_max": max_trigger, "long_break_duration": self.long_break_duration_input.value(), SETTINGS_SOUND_KEY: self.selected_audio_file_path}; self.settings_saved.emit(new_settings); self.accept()

# --- Main Application Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("MyCompany", "FocusTimerApp")
        self.sound_file_valid = False
        self.load_settings()
        self.current_state = STATE_IDLE
        self.remaining_seconds = self.focus_duration * 60
        self.current_phase_total_seconds = self.focus_duration * 60
        self.next_short_break_trigger_time = -1
        self.init_ui()
        self.init_timers()
        self.init_sound()
        self.update_ui_for_state()

    def load_settings(self):
        self.focus_duration = self.settings.value("focus_duration", DEFAULT_FOCUS_MINUTES, type=int)
        self.short_break_duration = self.settings.value("short_break_duration", DEFAULT_SHORT_BREAK_SECONDS, type=int)
        self.sb_trigger_min = self.settings.value("sb_trigger_min", DEFAULT_SHORT_BREAK_MIN_TRIGGER_MINUTES, type=int)
        self.sb_trigger_max = self.settings.value("sb_trigger_max", DEFAULT_SHORT_BREAK_MAX_TRIGGER_MINUTES, type=int)
        self.long_break_duration = self.settings.value("long_break_duration", DEFAULT_LONG_BREAK_MINUTES, type=int)
        self.notification_sound_path = self.settings.value(SETTINGS_SOUND_KEY, None)
        print("Loaded settings:", { k: getattr(self, k, None) for k in ["focus_duration", "short_break_duration", "sb_trigger_min", "sb_trigger_max", "long_break_duration", "notification_sound_path"]})

    def save_settings(self, settings_dict):
        print("Saving settings:", settings_dict)
        sound_path = settings_dict.get(SETTINGS_SOUND_KEY)
        if sound_path and not os.path.exists(sound_path):
            print(f"Warning: Sound path '{sound_path}' seems invalid despite dialog check. Saving anyway.")
        for key, value in settings_dict.items():
            self.settings.setValue(key, value)
        self.settings.sync()
        self.load_settings()
        self.apply_settings_update()

    def apply_settings_update(self):
        print("Applying settings update...")
        self.init_sound()
        if self.current_state in [STATE_IDLE, STATE_PAUSED]:
            self.reset_to_idle_state(update_ui=True)

    def init_ui(self):
        self.setWindowTitle("专注时钟")
        self.setGeometry(300, 300, 400, 500)
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        top_bar_layout = QHBoxLayout()
        top_bar_layout.addStretch(1)
        self.settings_button = QPushButton()
        settings_icon_path = "settings.png"
        if os.path.exists(settings_icon_path):
            self.settings_button.setIcon(QIcon(settings_icon_path))
            self.settings_button.setIconSize(QSize(24, 24))
            self.settings_button.setFixedSize(QSize(32, 32))
            self.settings_button.setStyleSheet("QPushButton { border: none; background-color: transparent; }")
        else:
            self.settings_button.setText("⚙️")
        self.settings_button.setToolTip("打开设置")
        self.settings_button.clicked.connect(self.open_settings_dialog)
        top_bar_layout.addWidget(self.settings_button)
        main_layout.addLayout(top_bar_layout)
        self.timer_widget = CircularTimer(self)
        self.timer_widget.time_changed_by_drag.connect(self.handle_timer_drag)
        main_layout.addWidget(self.timer_widget)
        self.controls_container = QWidget()
        self.controls_layout = QHBoxLayout(self.controls_container)
        self.controls_layout.setContentsMargins(0, 0, 0, 0)
        self.start_skip_button = QPushButton()
        self.start_skip_button.setMinimumSize(120, 40)
        self.start_skip_button.clicked.connect(self.handle_start_skip_click)
        self.controls_layout.addWidget(self.start_skip_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.focus_controls_widget = QWidget()
        focus_controls_layout = QHBoxLayout(self.focus_controls_widget)
        focus_controls_layout.setContentsMargins(0, 0, 0, 0)
        focus_controls_layout.addStretch()
        self.pause_continue_button = QPushButton("暂停专注")
        self.end_focus_button = QPushButton("结束")
        self.pause_continue_button.setStyleSheet("QPushButton { background-color: #ffc107; color: black; padding: 10px 15px; font-size: 16px; border: none; border-radius: 5px; margin-right: 5px;} QPushButton:hover { background-color: #e0a800; }")
        self.end_focus_button.setStyleSheet("QPushButton { background-color: #dc3545; color: white; padding: 10px 15px; font-size: 16px; border: none; border-radius: 5px; margin-left: 5px;} QPushButton:hover { background-color: #c82333; }")
        self.pause_continue_button.setMinimumSize(100, 40)
        self.end_focus_button.setMinimumSize(80, 40)
        self.pause_continue_button.clicked.connect(self.handle_pause_continue_click)
        self.end_focus_button.clicked.connect(self.handle_end_focus_click)
        focus_controls_layout.addWidget(self.pause_continue_button)
        focus_controls_layout.addWidget(self.end_focus_button)
        focus_controls_layout.addStretch()
        self.controls_layout.addWidget(self.focus_controls_widget)
        self.focus_controls_widget.setVisible(False)
        main_layout.addWidget(self.controls_container, alignment=Qt.AlignmentFlag.AlignCenter)
        palette = central_widget.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(Qt.GlobalColor.white))
        central_widget.setAutoFillBackground(True)
        central_widget.setPalette(palette)
        self.start_skip_button.setStyleSheet("QPushButton { background-color: #007BFF; color: white; padding: 10px 20px; font-size: 16px; border: none; border-radius: 5px; } QPushButton:hover { background-color: #0056b3; } QPushButton:pressed { background-color: #004085; } QPushButton:disabled { background-color: #cccccc; color: #666666; }")

    def init_timers(self):
        self.main_timer = QTimer(self)
        self.main_timer.setInterval(1000)
        self.main_timer.timeout.connect(self.update_countdown)
        self.short_break_scheduler = QTimer(self)
        self.short_break_scheduler.setSingleShot(True)
        self.short_break_scheduler.timeout.connect(self.trigger_short_break)

    def init_sound(self):
        print("Initializing sound (Duration check disabled)...")
        if hasattr(self, 'sound_effect'):
            self.sound_effect.stop()
        self.sound_effect = QSoundEffect(self)
        self.sound_file_valid = False
        sound_path = self.notification_sound_path
        if not sound_path:
            print("No sound file selected.")
            self.sound_effect.setSource(QUrl())
            return
        if not os.path.exists(sound_path) or not os.path.isfile(sound_path):
            print(f"Error: Saved sound file not found or invalid: {sound_path}")
            QMessageBox.warning(self, "声音文件错误", f"之前选择的声音文件不存在或无效：\n'{sound_path}'\n\n请在设置中重新选择。")
            self.settings.remove(SETTINGS_SOUND_KEY)
            self.notification_sound_path = None
            self.sound_effect.setSource(QUrl())
            return
        print(f"Loading sound file: {sound_path}")
        self.sound_effect.setSource(QUrl.fromLocalFile(sound_path))
        self.sound_effect.setVolume(0.8)
        if self.sound_effect.source().isValid() and not self.sound_effect.source().isEmpty():
            print("Sound file loaded successfully.")
            self.sound_file_valid = True
        else:
            print(f"Error: Failed to load sound file, source is invalid: {sound_path}")
            QMessageBox.warning(self, "声音加载错误", f"无法加载声音文件：\n'{sound_path}'\n\n文件可能已损坏或格式不被支持。")
            self.settings.remove(SETTINGS_SOUND_KEY)
            self.notification_sound_path = None
            self.sound_effect.setSource(QUrl())

    def handle_timer_drag(self, minutes):
        if self.current_state == STATE_IDLE or self.current_state == STATE_PAUSED:
            print(f"Timer dragged to {minutes} minutes.")
            self.focus_duration = minutes
            if self.current_state == STATE_IDLE:
                self.current_phase_total_seconds = self.focus_duration * 60
                self.remaining_seconds = self.current_phase_total_seconds
                self.timer_widget.set_display_time(self.remaining_seconds)

    def handle_start_skip_click(self):
        if self.current_state == STATE_IDLE:
            self.start_focus()
        elif self.current_state in [STATE_SHORT_BREAK, STATE_LONG_BREAK]:
            self.end_break_early()

    def handle_pause_continue_click(self):
        if self.current_state == STATE_FOCUS:
            self.pause_focus()
        elif self.current_state == STATE_PAUSED:
            self.resume_focus()

    def handle_end_focus_click(self):
        if self.current_state in [STATE_FOCUS, STATE_PAUSED]:
            self.end_focus_immediately()

    def start_focus(self):
        if self.current_state != STATE_IDLE: return
        print("Starting focus...")
        self.current_state = STATE_FOCUS
        self.current_phase_total_seconds = self.focus_duration * 60
        self.remaining_seconds = self.current_phase_total_seconds
        print(f"Starting with duration: {self.focus_duration} min")
        self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds)
        self.timer_widget.set_display_time(self.remaining_seconds)
        self.timer_widget.set_running(True)
        self.timer_widget.outer_color = QColor("#A0D2EB")
        self.main_timer.start()
        self.schedule_next_short_break()
        self.update_ui_for_state()

    def pause_focus(self):
        if self.current_state != STATE_FOCUS: return
        print("Pausing focus...")
        self.current_state = STATE_PAUSED
        self.main_timer.stop()
        self.short_break_scheduler.stop()
        self.timer_widget.set_running(False)
        self.update_ui_for_state()

    def resume_focus(self):
        if self.current_state != STATE_PAUSED: return
        print("Resuming focus...")
        self.current_state = STATE_FOCUS
        self.timer_widget.set_running(True)
        self.main_timer.start()
        self.schedule_next_short_break()
        self.update_ui_for_state()

    def end_focus_immediately(self):
        if self.current_state not in [STATE_FOCUS, STATE_PAUSED]: return
        print("Ending focus immediately.")
        self.reset_to_idle_state(update_ui=True)

    def reset_to_idle_state(self, update_ui=False):
        print("Resetting to idle state.")
        self.main_timer.stop()
        self.short_break_scheduler.stop()
        if hasattr(self, 'sound_effect'): self.sound_effect.stop()
        self.timer_widget.set_running(False)
        self.current_state = STATE_IDLE
        self.load_settings()
        self.current_phase_total_seconds = self.focus_duration * 60
        self.remaining_seconds = self.current_phase_total_seconds
        draggable_minutes = min(self.focus_duration, MAX_DRAGGABLE_MINUTES)
        self.timer_widget.set_time(draggable_minutes)
        self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds)
        self.timer_widget.set_display_time(self.remaining_seconds)
        self.timer_widget.outer_color = QColor("#A0D2EB")
        if update_ui: self.update_ui_for_state()

    def end_break_early(self):
        if self.current_state not in [STATE_SHORT_BREAK, STATE_LONG_BREAK]: return
        print("Ending break early...")
        self.main_timer.stop()
        if hasattr(self, 'sound_effect'): self.sound_effect.stop()
        self.timer_widget.set_running(False)
        if self.current_state == STATE_SHORT_BREAK:
            print("Returning to focus from short break.")
            self.current_state = STATE_FOCUS
            try: self.remaining_seconds = self.focus_seconds_when_break_started
            except AttributeError: print("Warning: Could not restore focus time accurately after skipping break."); self.remaining_seconds = self.settings.value("focus_duration", DEFAULT_FOCUS_MINUTES, type=int) * 60
            self.current_phase_total_seconds = self.settings.value("focus_duration", DEFAULT_FOCUS_MINUTES, type=int) * 60
            self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds)
            self.timer_widget.set_display_time(self.remaining_seconds)
            self.timer_widget.outer_color = QColor("#A0D2EB")
            self.timer_widget.set_running(True)
            self.main_timer.start()
            self.schedule_next_short_break()
        elif self.current_state == STATE_LONG_BREAK:
            print("Returning to idle from long break.")
            self.reset_to_idle_state()
        self.update_ui_for_state()

    def schedule_next_short_break(self):
        self.short_break_scheduler.stop()
        self.next_short_break_trigger_time = -1
    
        if self.current_state != STATE_FOCUS or self.focus_duration <= 0:
            return
            
        min_trigger_sec = self.sb_trigger_min * 60
        max_trigger_sec = self.sb_trigger_max * 60
        
        if min_trigger_sec >= max_trigger_sec or max_trigger_sec <= 0:
            print("Warning: Invalid short break trigger bounds.")
            return
            
        min_trigger_sec = max(1, min_trigger_sec)
        
        try:
            delay_seconds = random.randint(min_trigger_sec, max_trigger_sec)
        except ValueError:
            delay_seconds = min_trigger_sec
            print(f"Error calculating short break delay. Using min: {delay_seconds}")
        
        if delay_seconds >= self.remaining_seconds:
            print("Next scheduled short break is after focus ends.")
        else:
            self.next_short_break_trigger_time = self.remaining_seconds - delay_seconds
            print(f"Scheduling next short break in {delay_seconds}s")
            self.short_break_scheduler.start(delay_seconds * 1000)

    def trigger_short_break(self):
        if self.current_state != STATE_FOCUS:
            print("Short break trigger ignored, not in focus state.")
            return
            
        print("Triggering short break...")
        self.main_timer.stop()
        self.focus_seconds_when_break_started = self.remaining_seconds
        self.current_state = STATE_SHORT_BREAK
        self.current_phase_total_seconds = self.short_break_duration
        self.remaining_seconds = self.current_phase_total_seconds
        self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds)
        self.timer_widget.set_display_time(self.remaining_seconds)
        self.timer_widget.outer_color = QColor("#FFD700")
        self.timer_widget.set_running(True)
        
        if self.sound_file_valid and hasattr(self, 'sound_effect'):
            print(f"Playing sound: {self.sound_effect.source().fileName()}")
            self.sound_effect.play()
        else:
            print("Skipping sound playback: No valid sound file loaded.")
            
        self.main_timer.start()
        self.update_ui_for_state()

    def start_long_break(self):
        print("Starting long break..."); self.current_state = STATE_LONG_BREAK; self.current_phase_total_seconds = self.long_break_duration * 60; self.remaining_seconds = self.current_phase_total_seconds; self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds); self.timer_widget.set_display_time(self.remaining_seconds); self.timer_widget.outer_color = QColor("#90EE90"); self.timer_widget.set_running(True); self.main_timer.start(); self.update_ui_for_state()

    def update_countdown(self):
        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self.timer_widget.set_display_time(self.remaining_seconds)
        else:
            self.main_timer.stop(); self.timer_widget.set_running(False);
            if hasattr(self, 'sound_effect'): self.sound_effect.stop()
            if self.current_state == STATE_FOCUS:
                print("Focus finished."); self.short_break_scheduler.stop(); self.start_long_break()
            elif self.current_state == STATE_SHORT_BREAK:
                print("Short break finished, resuming focus."); self.current_state = STATE_FOCUS
                try: self.remaining_seconds = self.focus_seconds_when_break_started
                except AttributeError: print("Warning: Could not restore focus time accurately after break."); self.remaining_seconds = self.settings.value("focus_duration", DEFAULT_FOCUS_MINUTES, type=int) * 60
                self.current_phase_total_seconds = self.settings.value("focus_duration", DEFAULT_FOCUS_MINUTES, type=int) * 60; self.timer_widget.set_actual_total_seconds(self.current_phase_total_seconds); self.timer_widget.set_display_time(self.remaining_seconds); self.timer_widget.outer_color = QColor("#A0D2EB"); self.timer_widget.set_running(True); self.main_timer.start(); self.schedule_next_short_break(); self.update_ui_for_state()
            elif self.current_state == STATE_LONG_BREAK:
                print("Long break finished."); self.reset_to_idle_state(update_ui=True)

    def update_ui_for_state(self):
        is_idle = self.current_state == STATE_IDLE; is_focus = self.current_state == STATE_FOCUS; is_paused = self.current_state == STATE_PAUSED; is_break = self.current_state in [STATE_SHORT_BREAK, STATE_LONG_BREAK]; self.start_skip_button.setVisible(is_idle or is_break); self.focus_controls_widget.setVisible(is_focus or is_paused);
        if is_idle: self.start_skip_button.setText("开始专注")
        elif is_break: self.start_skip_button.setText("跳过休息")
        if is_focus: self.pause_continue_button.setText("暂停专注")
        elif is_paused: self.pause_continue_button.setText("继续专注"); self.settings_button.setEnabled(is_idle or is_paused) # Corrected enabling logic
        if is_idle: self.timer_widget.outer_color = QColor("#A0D2EB")
        elif is_focus or is_paused: self.timer_widget.outer_color = QColor("#A0D2EB")
        elif self.current_state == STATE_SHORT_BREAK: self.timer_widget.outer_color = QColor("#FFD700")
        elif self.current_state == STATE_LONG_BREAK: self.timer_widget.outer_color = QColor("#90EE90");
        self.timer_widget.update() # Ensure update runs

    def open_settings_dialog(self):
        if self.current_state not in [STATE_IDLE, STATE_PAUSED]: QMessageBox.warning(self, "无法打开设置", "请先结束或暂停当前活动。"); return
        current_config = { k: getattr(self, k, None) for k in ["focus_duration", "short_break_duration", "sb_trigger_min", "sb_trigger_max", "long_break_duration"]}; current_config[SETTINGS_SOUND_KEY] = self.notification_sound_path; dialog = SettingsDialog(current_config, self); dialog.settings_saved.connect(self.save_settings); dialog.exec()

    def closeEvent(self, event):
        self.main_timer.stop(); self.short_break_scheduler.stop(); print("Closing application."); event.accept()

# --- Main Execution ---
if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())