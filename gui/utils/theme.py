"""Consistent light colors for Windows native, selected and disabled controls."""
from PyQt5.QtGui import QColor, QPalette


def light_palette():
    palette = QPalette()
    colors = {
        QPalette.Window: '#f6f8fb', QPalette.WindowText: '#1f2933',
        QPalette.Base: '#ffffff', QPalette.AlternateBase: '#f1f5f9',
        QPalette.Text: '#1f2933', QPalette.Button: '#e5ecf7',
        QPalette.ButtonText: '#1f2933', QPalette.ToolTipBase: '#ffffff',
        QPalette.ToolTipText: '#1f2933', QPalette.Highlight: '#dbeafe',
        QPalette.HighlightedText: '#0f172a', QPalette.Link: '#1d4ed8',
        QPalette.Light: '#ffffff', QPalette.Mid: '#cbd5e1', QPalette.Dark: '#64748b',
    }
    if hasattr(QPalette, 'PlaceholderText'):
        colors[QPalette.PlaceholderText] = '#64748b'
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        for role, color in colors.items():
            palette.setColor(group, role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.HighlightedText):
        palette.setColor(QPalette.Disabled, role, QColor('#475569'))
    for role in (QPalette.Base, QPalette.Button):
        palette.setColor(QPalette.Disabled, role, QColor('#f1f5f9'))
    return palette


def apply_light_theme(app):
    app.setStyle('Fusion')
    app.setPalette(light_palette())
