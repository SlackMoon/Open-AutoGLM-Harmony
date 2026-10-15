"""DPI-aware window sizing and controls that do not collapse below their text."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton, QScrollArea, QSizePolicy


def scroll_panel(content, name=""):
    area = QScrollArea()
    area.setObjectName(name)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setMinimumSize(0, 0)
    area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    area.setWidget(content)
    return area


def fit_initial_window(window):
    screen = QApplication.primaryScreen()
    if screen is None:
        window.setMinimumSize(640, 420)
        window.resize(1120, 760)
        return
    available = screen.availableGeometry()
    width = min(1320, max(320, available.width() - 32))
    height = min(860, max(240, available.height() - 48))
    window.setMinimumSize(min(760, width), min(480, height))
    window.resize(width, height)
    window.move(available.center() - window.rect().center())


def size_controls_to_text(root):
    for control in root.findChildren((QLineEdit, QComboBox, QPushButton)):
        control.ensurePolished()
        if not hasattr(control, "_layout_base_minimum"):
            control._layout_base_minimum = control.minimumSize()
        base = control._layout_base_minimum
        metrics = QFontMetrics(control.font())
        control.setMinimumHeight(max(base.height(), metrics.height() + 18))
        if isinstance(control, QPushButton):
            width = metrics.horizontalAdvance(control.text()) + 36
            control.setMinimumWidth(max(base.width(), width))
            control.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        elif isinstance(control, QComboBox):
            control.setMinimumContentsLength(4)
            control.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            control.setMinimumWidth(max(base.width(), metrics.horizontalAdvance("MMMM") + 42))
            longest = max((metrics.horizontalAdvance(control.itemText(i)) for i in range(control.count())), default=0)
            control.view().setMinimumWidth(longest + 48)
            control.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            control.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
