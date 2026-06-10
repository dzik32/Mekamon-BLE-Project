"""MekaMon BLE control GUI (PySide6).

Run:  python gui/app.py          (from the repo root)

Panels:
  * Connection  - scan, pick a device, connect/disconnect (runs the handshake)
  * Drive       - virtual joystick + turn slider, plus WASD / Q-E / Space keyboard
  * Limbs       - direct control of all 12 joints (4 legs x hip/knee/thigh)
  * Head LED    - RGB colour picker
  * Animations  - play a built-in animation by id
  * STOP        - emergency neutral + kill streams

The robot is driven by continuous streaming (handled by MekamonController on a
background thread); this UI just updates the target vector / pose.
"""
from __future__ import annotations

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PySide6.QtCore import Qt, QPointF, Signal
    from PySide6.QtGui import QColor, QPainter, QBrush, QPen
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QColorDialog, QComboBox, QFrame, QGridLayout,
        QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
        QPlainTextEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
    )
except ModuleNotFoundError:
    sys.exit(
        "PySide6 is not installed. Install the GUI deps with:\n"
        "    python -m pip install -r requirements.txt\n"
        "(or: python -m pip install PySide6 bleak)"
    )

from mekamon import (
    GaitParameterType,
    GaitType,
    KinematicStanceType,
    MekamonController,
)

DRIVE_SCALE = 80          # joystick edge -> int8 drive value (max useful ~80)
TURN_SCALE = 80
JOINTS = ["Hip", "Knee", "Thigh"]
LEGS = ["Front Left", "Front Right", "Back Left", "Back Right"]


# --------------------------------------------------------------------------- #
#  Virtual joystick widget
# --------------------------------------------------------------------------- #
class Joystick(QWidget):
    """A self-centering 2-axis joystick. Emits ``moved(x, y)`` with x,y in [-1, 1]."""

    moved = Signal(float, float)

    def __init__(self, size: int = 200):
        super().__init__()
        self.setFixedSize(size, size)
        self._knob = QPointF(0, 0)     # offset from centre, in pixels
        self._radius = size / 2 - 18
        self._dragging = False

    def _center(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._center()
        p.setPen(QPen(QColor("#444"), 2))
        p.setBrush(QBrush(QColor("#1e1e24")))
        p.drawEllipse(c, self._radius, self._radius)
        # cross-hairs
        p.setPen(QPen(QColor("#333"), 1))
        p.drawLine(QPointF(c.x() - self._radius, c.y()), QPointF(c.x() + self._radius, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - self._radius), QPointF(c.x(), c.y() + self._radius))
        # knob
        knob = c + self._knob
        p.setPen(QPen(QColor("#2a82da"), 2))
        p.setBrush(QBrush(QColor("#2a82da")))
        p.drawEllipse(knob, 16, 16)

    def mousePressEvent(self, e):
        self._dragging = True
        self._update(e.position())

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._update(e.position())

    def mouseReleaseEvent(self, _):
        self._dragging = False
        self._knob = QPointF(0, 0)
        self.update()
        self.moved.emit(0.0, 0.0)

    def _update(self, pos: QPointF):
        d = pos - self._center()
        dist = (d.x() ** 2 + d.y() ** 2) ** 0.5
        if dist > self._radius:
            d = QPointF(d.x() / dist * self._radius, d.y() / dist * self._radius)
        self._knob = d
        self.update()
        x = d.x() / self._radius
        y = -d.y() / self._radius           # up = +forward
        self.moved.emit(x, y)


# --------------------------------------------------------------------------- #
#  Main window
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    _conn_changed = Signal(bool)
    _response = Signal(object, bytes, bool)
    _scan_done = Signal(object)
    _log_sig = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MekaMon BLE Controller")
        self.controller = MekamonController()
        self.controller.on_connection_changed = self._conn_changed.emit
        self.controller.on_response = lambda pt, pl, ok: self._response.emit(pt, pl, ok)
        self._conn_changed.connect(self._on_conn_changed)
        self._response.connect(self._on_response)
        self._scan_done.connect(self._on_scan_done)
        self._log_sig.connect(self._append_log)

        self._devices = []
        self._pressed = set()
        self._turn = 0.0
        self._stick = (0.0, 0.0)

        central = QWidget()
        root = QHBoxLayout(central)
        root.addLayout(self._build_left_column(), 1)
        root.addLayout(self._build_right_column(), 1)
        self.setCentralWidget(central)
        self.setFocusPolicy(Qt.StrongFocus)
        self._set_enabled(False)

    # ---- layout builders ------------------------------------------------ #
    def _build_left_column(self):
        col = QVBoxLayout()
        col.addWidget(self._build_connection_box())
        col.addWidget(self._build_drive_box())
        col.addWidget(self._build_head_box())
        col.addWidget(self._build_moves_box())
        col.addStretch(1)
        return col

    def _build_right_column(self):
        col = QVBoxLayout()
        col.addWidget(self._build_limbs_box(), 1)
        col.addWidget(self._build_gait_box())
        col.addWidget(self._build_log_box())
        return col

    def _build_connection_box(self):
        box = QGroupBox("Connection")
        v = QVBoxLayout(box)
        self.device_list = QListWidget()
        self.device_list.setMaximumHeight(110)
        v.addWidget(self.device_list)
        row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.clicked.connect(self._do_scan)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._do_connect)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self._do_disconnect)
        self.disconnect_btn.setEnabled(False)
        row.addWidget(self.scan_btn)
        row.addWidget(self.connect_btn)
        row.addWidget(self.disconnect_btn)
        v.addLayout(row)
        self.status = QLabel("Disconnected")
        self.status.setStyleSheet("color:#c0392b; font-weight:bold;")
        v.addWidget(self.status)
        return box

    def _build_drive_box(self):
        box = QGroupBox("Drive  (W/S = fwd/back, A/D = left/right, Q/E = turn, Space = stop)")
        v = QVBoxLayout(box)
        self.joystick = Joystick(190)
        self.joystick.moved.connect(self._on_stick)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(self.joystick)
        h.addStretch(1)
        v.addLayout(h)
        v.addWidget(QLabel("Turn"))
        self.turn_slider = QSlider(Qt.Horizontal)
        self.turn_slider.setRange(-TURN_SCALE, TURN_SCALE)
        self.turn_slider.setValue(0)
        self.turn_slider.valueChanged.connect(self._on_turn_slider)
        self.turn_slider.sliderReleased.connect(self._reset_turn)
        v.addWidget(self.turn_slider)
        self.stop_btn = QPushButton("⏹  EMERGENCY STOP")
        self.stop_btn.setStyleSheet(
            "background:#c0392b; color:white; font-weight:bold; padding:10px;"
        )
        self.stop_btn.clicked.connect(self._do_stop)
        v.addWidget(self.stop_btn)
        return box

    def _build_head_box(self):
        box = QGroupBox("Head LED")
        h = QHBoxLayout(box)
        self.colour_btn = QPushButton("Pick colour…")
        self.colour_btn.clicked.connect(self._pick_colour)
        h.addWidget(self.colour_btn)
        for name, rgb in [("Off", (0, 0, 0)), ("Red", (255, 0, 0)),
                          ("Green", (0, 255, 0)), ("Blue", (0, 80, 255))]:
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, c=rgb: self.controller.set_head_colour(*c))
            h.addWidget(b)
        return box

    def _build_moves_box(self):
        box = QGroupBox("Moves")
        v = QVBoxLayout(box)

        # Animation (id is content-driven -> experiment)
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("Animation id"))
        self.anim_id = QSpinBox()
        self.anim_id.setRange(0, 255)
        h1.addWidget(self.anim_id)
        play = QPushButton("Play")
        play.clicked.connect(lambda: self.controller.play_animation(self.anim_id.value()))
        h1.addWidget(play)
        h1.addStretch(1)
        v.addLayout(h1)
        v.addWidget(QLabel("(animation ids are content-driven — try values to find moves)"))

        # Take steps
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Walk"))
        self.step_count = QSpinBox()
        self.step_count.setRange(1, 255)
        self.step_count.setValue(3)
        h2.addWidget(self.step_count)
        h2.addWidget(QLabel("step cycles"))
        go = QPushButton("Go")
        go.clicked.connect(lambda: self.controller.take_steps(self.step_count.value()))
        h2.addWidget(go)
        h2.addStretch(1)
        v.addLayout(h2)

        # Body / stance mode
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("Body mode"))
        self.stance_combo = QComboBox()
        for s in KinematicStanceType:
            self.stance_combo.addItem(s.name, int(s))
        self.stance_combo.setCurrentText("Kinematic")
        h3.addWidget(self.stance_combo)
        setb = QPushButton("Set")
        setb.clicked.connect(
            lambda: self.controller.kinematic_stance(self.stance_combo.currentData())
        )
        h3.addWidget(setb)
        h3.addStretch(1)
        v.addLayout(h3)
        return box

    def _build_gait_box(self):
        box = QGroupBox("Gait tuning  (raw 0–255 bytes — experiment)")
        v = QVBoxLayout(box)
        grid = QGridLayout()
        self.gait_sliders = {}
        defaults = {GaitParameterType.GaitType: int(GaitType.Trot)}
        for i, p in enumerate(GaitParameterType):
            grid.addWidget(QLabel(p.name), i, 0)
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 255)
            s.setValue(defaults.get(p, 128))
            lbl = QLabel(str(s.value()))
            lbl.setMinimumWidth(30)
            s.valueChanged.connect(lambda val, l=lbl: l.setText(str(val)))
            grid.addWidget(s, i, 1)
            grid.addWidget(lbl, i, 2)
            self.gait_sliders[p] = s
        v.addLayout(grid)
        self.gait_apply = QPushButton("Apply gait")
        self.gait_apply.clicked.connect(self._apply_gait)
        v.addWidget(self.gait_apply)
        return box

    def _apply_gait(self):
        params = [self.gait_sliders[p].value() for p in GaitParameterType]
        self.controller.gait_set_all(params)
        self._log(f"-> GaitSetAll {params}")

    def _build_limbs_box(self):
        box = QGroupBox("Limb control — 12 joints (signed int8; scaling needs live calibration)")
        outer = QVBoxLayout(box)
        top = QHBoxLayout()
        self.joint_mode = QCheckBox("Direct joint mode (stream poses)")
        self.joint_mode.toggled.connect(self._on_joint_mode)
        top.addWidget(self.joint_mode)
        top.addStretch(1)
        neutral = QPushButton("Neutral (all 0)")
        neutral.clicked.connect(self._neutral_joints)
        top.addWidget(neutral)
        outer.addLayout(top)

        grid = QGridLayout()
        self.joint_sliders = {}          # (leg, joint) -> QSlider
        self.joint_labels = {}
        for col, leg in enumerate(LEGS):
            grid.addWidget(self._leg_header(leg), 0, col)
            legbox = QVBoxLayout()
            for joint in JOINTS:
                legbox.addWidget(QLabel(joint))
                s = QSlider(Qt.Horizontal)
                s.setRange(-128, 127)
                s.setValue(0)
                lbl = QLabel("0")
                lbl.setMinimumWidth(30)
                s.valueChanged.connect(
                    lambda val, l=lbl: l.setText(str(val))
                )
                s.valueChanged.connect(self._push_joints)
                row = QHBoxLayout()
                row.addWidget(s, 1)
                row.addWidget(lbl)
                legbox.addLayout(row)
                self.joint_sliders[(leg, joint)] = s
                self.joint_labels[(leg, joint)] = lbl
            holder = QWidget()
            holder.setLayout(legbox)
            grid.addWidget(holder, 1, col)
        outer.addLayout(grid)
        return box

    def _leg_header(self, text):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-weight:bold;")
        return lbl

    def _build_log_box(self):
        box = QGroupBox("Robot responses")
        v = QVBoxLayout(box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        v.addWidget(self.log)
        return box

    # ---- connection actions -------------------------------------------- #
    def _do_scan(self):
        self.scan_btn.setEnabled(False)
        self.status.setText("Scanning…")
        self.status.setStyleSheet("color:#e67e22; font-weight:bold;")

        def work():
            try:
                devs = self.controller.scan(6.0)
            except Exception as e:
                devs = e
            self._scan_done.emit(devs)

        threading.Thread(target=work, daemon=True).start()

    def _on_scan_done(self, devs):
        self.scan_btn.setEnabled(True)
        if isinstance(devs, Exception):
            self._log(f"Scan failed: {devs}")
            self.status.setText("Scan failed")
            return
        self._devices = devs
        self.device_list.clear()
        for d in devs:
            tag = "  ★ MekaMon?" if d.likely_mekamon else ""
            item = QListWidgetItem(f"{d.name}   [{d.address}]  {d.rssi} dBm{tag}")
            self.device_list.addItem(item)
        if devs:
            self.device_list.setCurrentRow(0)
        self.status.setText(f"Found {len(devs)} device(s)")
        self.status.setStyleSheet("color:#2c3e50; font-weight:bold;")

    def _do_connect(self):
        row = self.device_list.currentRow()
        if row < 0 or row >= len(self._devices):
            self._log("Select a device first.")
            return
        dev = self._devices[row]
        self.status.setText(f"Connecting to {dev.name}…")
        self.connect_btn.setEnabled(False)

        def work():
            try:
                self.controller.connect(dev.device)
            except Exception as e:
                self._conn_changed.emit(False)
                self._scan_done_error(e)

        threading.Thread(target=work, daemon=True).start()

    def _scan_done_error(self, e):
        self._log(f"Connect failed: {e}")

    def _do_disconnect(self):
        self.controller.disconnect()

    def _do_stop(self):
        self.controller.stop()
        self.joint_mode.setChecked(False)
        self.turn_slider.setValue(0)
        self._log("STOP sent.")

    # ---- drive ---------------------------------------------------------- #
    def _on_stick(self, x, y):
        self._stick = (x, y)
        self._push_drive()

    def _on_turn_slider(self, val):
        self._turn = val / TURN_SCALE
        self._push_drive()

    def _reset_turn(self):
        self.turn_slider.setValue(0)

    def _push_drive(self):
        if not self.controller.is_connected:
            return
        x, y = self._stick
        strafe = int(x * DRIVE_SCALE)
        forward = int(y * DRIVE_SCALE)
        turn = int(self._turn * TURN_SCALE)
        self.controller.set_drive(forward, strafe, turn)

    # ---- limbs ---------------------------------------------------------- #
    def _on_joint_mode(self, on):
        if not self.controller.is_connected:
            return
        if on:
            self.controller.set_mode("joint")
            self._push_joints()
        else:
            self.controller.set_mode("drive")

    def _push_joints(self):
        if not self.controller.is_connected or not self.joint_mode.isChecked():
            return
        legs = []
        for leg in LEGS:
            legs.append(tuple(self.joint_sliders[(leg, j)].value() for j in JOINTS))
        self.controller.set_joints(*legs)

    def _neutral_joints(self):
        for s in self.joint_sliders.values():
            s.blockSignals(True)
            s.setValue(0)
            s.blockSignals(False)
        for lbl in self.joint_labels.values():
            lbl.setText("0")
        self._push_joints()

    # ---- head ----------------------------------------------------------- #
    def _pick_colour(self):
        c = QColorDialog.getColor(parent=self)
        if c.isValid():
            self.controller.set_head_colour(c.red(), c.green(), c.blue())

    # ---- callbacks ------------------------------------------------------ #
    def _on_conn_changed(self, connected):
        self._set_enabled(connected)
        self.disconnect_btn.setEnabled(connected)
        self.connect_btn.setEnabled(not connected)
        if connected:
            self.status.setText("Connected ✓")
            self.status.setStyleSheet("color:#27ae60; font-weight:bold;")
            self._log("Connected — handshake sent.")
        else:
            self.status.setText("Disconnected")
            self.status.setStyleSheet("color:#c0392b; font-weight:bold;")

    def _on_response(self, ptype, payload, ok):
        flag = "" if ok else "  (BAD CHECKSUM)"
        self._log(f"<- {ptype.name} {payload.hex(' ')}{flag}")

    def _log(self, msg):
        # Thread-safe: callable from worker threads (scan/connect) and GUI slots alike.
        self._log_sig.emit(msg)

    def _append_log(self, msg):
        self.log.appendPlainText(msg)

    def _set_enabled(self, on):
        for w in (self.joystick, self.turn_slider, self.stop_btn, self.colour_btn,
                  self.joint_mode):
            w.setEnabled(on)

    # ---- keyboard driving ---------------------------------------------- #
    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        if e.key() == Qt.Key_Space:
            self._do_stop()
            return
        self._pressed.add(e.key())
        self._keys_to_drive()

    def keyReleaseEvent(self, e):
        if e.isAutoRepeat():
            return
        self._pressed.discard(e.key())
        self._keys_to_drive()

    def _keys_to_drive(self):
        k = self._pressed
        fwd = (Qt.Key_W in k) - (Qt.Key_S in k)
        strafe = (Qt.Key_D in k) - (Qt.Key_A in k)
        turn = (Qt.Key_E in k) - (Qt.Key_Q in k)
        self._stick = (strafe, fwd)
        self._turn = turn
        self._push_drive()

    def closeEvent(self, e):
        try:
            self.controller.shutdown()
        finally:
            e.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.resize(1040, 880)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
