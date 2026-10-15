"""
Aurora Glass Theme Qt Style Sheet for Open-AutoGLM GUI.
"""

MODERN_DARK_THEME = """
/* 
   Aurora Glass Theme
   A vibrant, modern aesthetic combining "Aurora" gradients with neo-glassmorphism.
*/

/* Global Reset */
QWidget {
    font-family: 'Segoe UI Variable', 'Segoe UI', 'Roboto', sans-serif;
    font-size: 14px;
    color: #2D3436; /* Deep charcoal for high contrast text */
    outline: none;
}

/* Main Window - The Canvas */
#MainWindow {
    /* Vibrant Gradient: Sky Blue (#8EC5FC) to Soft Lavender (#E0C3FC) */
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8EC5FC, stop:0.5 #C8CDFA, stop:1 #E0C3FC);
}

/* Tooltips */
QToolTip {
    border: 1px solid rgba(255, 255, 255, 0.6);
    background-color: rgba(255, 255, 255, 0.95);
    color: #6C5CE7;
    padding: 6px;
    border-radius: 6px;
    font-weight: bold;
}

/* Group Box - The Glass Cards */
QGroupBox {
    /* Highly transparent white background for that "premium glass" look */
    background-color: rgba(255, 255, 255, 0.55);
    
    /* Subtle white border to define edges without heaviness */
    border: 1px solid rgba(255, 255, 255, 0.9);
    
    border-radius: 12px;
    margin-top: 1.4em; /* Space for title */
    padding-top: 15px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 15px;
    padding: 0 5px;
    
    /* Stylish Title */
    color: #574B90; /* Muted deep purple */
    font-weight: 800;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* Buttons - Floating Actions */
QPushButton {
    background-color: rgba(255, 255, 255, 0.7);
    border: 1px solid rgba(255, 255, 255, 1.0);
    border-radius: 8px;
    padding: 8px 16px;
    color: #574B90;
    font-weight: 600;
    
    /* Soft shadow for depth */
    /* Note: Box-shadow not supported in QSS standard for QPushButton in all modes, 
       but we design for clean look anyway */
}

QPushButton:hover {
    background-color: rgba(255, 255, 255, 0.95);
    /* Mimic "glow" with color change */
    color: #6C5CE7;
}

QPushButton:pressed {
    background-color: #E0C3FC;
    border-color: #A29BFE;
}

QPushButton:disabled {
    background-color: rgba(255, 255, 255, 0.3);
    color: #B2BEC3;
    border: 1px solid rgba(255, 255, 255, 0.2);
}

/* Inputs - Frosted Fields */
QLineEdit, QTextEdit, QComboBox {
    background-color: rgba(255, 255, 255, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.8);
    border-radius: 8px;
    padding: 8px 10px;
    color: #2D3436;
    selection-background-color: #A29BFE;
    selection-color: #ffffff;
}

QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    background-color: rgba(255, 255, 255, 0.9);
    border: 1px solid #6C5CE7; /* Focus accent */
}

/* ComboBox Dropdown */
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left-width: 0px;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}

/* List Widget - Content Pane */
QListWidget {
    background-color: rgba(255, 255, 255, 0.4);
    border: 1px solid rgba(255, 255, 255, 0.6);
    border-radius: 10px;
    outline: none;
}

QListWidget::item {
    margin: 4px 8px;
    padding: 8px;
    border-radius: 6px;
    color: #2D3436;
}

QListWidget::item:selected {
    background-color: #6C5CE7; /* Vibrant accent for selection */
    color: white;
}

QListWidget::item:hover:!selected {
    background-color: rgba(255, 255, 255, 0.6);
}

/* Scrollbars - Hidden/Minimal */
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 4px;
}

QScrollBar::handle:vertical {
    background: rgba(45, 52, 54, 0.2);
    min-height: 20px;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(45, 52, 54, 0.4);
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

/* Splitter */
QSplitter::handle {
    background-color: rgba(255, 255, 255, 0.0); /* Invisible splitter handle */
}

/* --- Hero Elements --- */

/* Start Button - Vibrant Aurora Green */
QPushButton#startBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #00b894, stop:1 #00cec9);
    border: none;
    color: white;
    font-weight: bold;
    font-size: 15px;
    border-radius: 20px; /* Pill shape */
}

QPushButton#startBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #55efc4, stop:1 #81ecec);
}

QPushButton#startBtn:pressed {
    background: #00b894;
    padding-left: 18px; /* Slight press nudge */
}

/* Stop Button - Vibrant Aurora Red */
QPushButton#stopBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #d63031, stop:1 #ff7675);
    border: none;
    color: white;
    font-weight: bold;
    font-size: 15px;
    border-radius: 20px;
}

QPushButton#stopBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff7675, stop:1 #fab1a0);
}

QPushButton#stopBtn:pressed {
    background: #d63031;
    padding-left: 18px;
}

/* Help Button */
QPushButton#helpBtn {
    background-color: rgba(9, 132, 227, 0.8);
    border: none;
    color: white;
    border-radius: 6px;
}
QPushButton#helpBtn:hover {
    background-color: #74b9ff;
}

/* Status Labels */
QLabel#statusLabel {
    font-size: 18px;
    font-weight: 800;
    color: #6C5CE7;
    padding: 12px;
}

QLabel#errorHint {
    color: #d63031;
    font-size: 12px;
    font-weight: 600;
}
"""
