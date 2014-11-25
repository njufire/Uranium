from PyQt5.QtCore import Qt, QEvent, QObject
from PyQt5.QtGui import QKeyEvent

from Cura.InputDevice import InputDevice
from Cura.Event import KeyEvent

class QtKeyDevice(InputDevice):
    def __init__(self):
        super().__init__()

    def handleEvent(self, event):
        if event.type() == QEvent.KeyPress:
            e = KeyEvent(KeyEvent.KeyPressEvent, self._qtKeyToCuraKey(event.key()))
            self.event.emit(e)
        elif event.type() == QEvent.KeyRelease:
            e = KeyEvent(KeyEvent.KeyReleaseEvent, self._qtKeyToCuraKey(event.key()))
            self.event.emit(e)

    def _qtKeyToCuraKey(self, key):
        return key
