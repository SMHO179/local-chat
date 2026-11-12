"""Dark theme for the application."""

BG = "#0e1117"
SURFACE = "#161b24"
BORDER = "#222a38"
TEXT = "#e7e9ef"
MUTED = "#8b93a7"
ACCENT = "#4f7cff"
GOOD = "#3ddc97"
WARN = "#f5b948"
BAD = "#ff6b7a"

APP_STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 10pt;
}}
QLabel {{ background: transparent; }}
QLabel#brand {{ font-size: 26pt; font-weight: bold; }}
QLabel#tagline, QLabel#muted {{ color: {MUTED}; }}
QLabel#section {{ color: {MUTED}; font-size: 9pt; }}
QLabel#value {{ font-size: 13pt; }}
QLabel#code {{
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 24pt;
    font-weight: bold;
}}
QLabel#heading {{ font-size: 14pt; font-weight: bold; }}
QLabel#avatar {{
    background: {ACCENT};
    color: white;
    border-radius: 26px;
    font-size: 18pt;
    font-weight: bold;
    min-width: 52px; max-width: 52px;
    min-height: 52px; max-height: 52px;
    qproperty-alignment: AlignCenter;
}}
QLabel#dot {{ color: {MUTED}; font-size: 14pt; }}
QLabel#dot[state="connected"] {{ color: {GOOD}; }}
QLabel#dot[state="waiting"] {{ color: {WARN}; }}
QLabel#dot[state="connecting"] {{ color: {ACCENT}; }}
QLabel#quality[level="Good"] {{ color: {GOOD}; }}
QLabel#quality[level="Fair"] {{ color: {WARN}; }}
QLabel#quality[level="Poor"] {{ color: {BAD}; }}
QLabel#notice {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 10px 12px;
    color: {MUTED};
}}
QLabel#notice[level="warning"] {{ color: {WARN}; }}
QLabel#notice[level="error"] {{ color: {BAD}; }}
QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLineEdit, QComboBox {{
    background: #0b0f15;
    border: 1px solid #2a3344;
    border-radius: 8px;
    padding: 9px 12px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid #2a3344;
    selection-background-color: {ACCENT};
}}
QPushButton {{
    background: #1d2431;
    border: 1px solid #2a3344;
    border-radius: 10px;
    padding: 10px 18px;
}}
QPushButton:hover {{ background: #252e3f; }}
QPushButton:pressed {{ background: #1a202b; }}
QPushButton:disabled {{ color: #4d5566; background: #161b24; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: white; font-weight: bold; }}
QPushButton#primary:hover {{ background: #6289ff; }}
QPushButton#primary:disabled {{ background: #2a3450; color: #7a84a0; }}
QPushButton#danger {{ background: #3a1d24; border: 1px solid #5c2a35; color: #ff9aa5; }}
QPushButton#danger:hover {{ background: #4a2029; }}
QPushButton#toggle:checked {{ background: {WARN}; color: #1b1405; border: none; font-weight: bold; }}
QPushButton#ptt {{ min-width: 150px; }}
QPushButton#ptt:pressed, QPushButton#ptt:checked {{ background: {GOOD}; color: #062316; border: none; font-weight: bold; }}
QCheckBox {{ color: {MUTED}; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid #2a3344; background: #0b0f15; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QProgressBar {{ background: #0b0f15; border: none; border-radius: 4px; }}
"""
