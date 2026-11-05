"""الألوان الرسمية وأنماط الواجهة."""

PRIMARY = "#0B3C5D"      # كحلي رسمي
PRIMARY_DARK = "#072A42"
ACCENT = "#B08D57"       # ذهبي هادئ
BG = "#F4F6F8"
SURFACE = "#FFFFFF"
TEXT = "#1F2933"
MUTED = "#6B7785"
SUCCESS = "#2E7D32"
WARNING = "#B26A00"
DANGER = "#B3261E"
BORDER = "#D5DBE1"

FONT_FAMILY = "Segoe UI, Tahoma, Arial"

QSS = f"""
* {{ font-family: {FONT_FAMILY}; font-size: 10.5pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#Sidebar {{ background: {PRIMARY}; }}
QWidget#Sidebar QLabel {{ color: white; }}
QListWidget#Nav {{ background: transparent; border: none; color: white; outline: 0; }}
QListWidget#Nav::item {{ padding: 11px 14px; border-radius: 6px; margin: 2px 8px; color: #E6EDF3; }}
QListWidget#Nav::item:hover {{ background: rgba(255,255,255,0.08); }}
QListWidget#Nav::item:selected {{ background: {ACCENT}; color: white; font-weight: bold; }}
QFrame#Header {{ background: {SURFACE}; border-bottom: 3px solid {ACCENT}; }}
QLabel#Title {{ font-size: 15pt; font-weight: bold; color: {PRIMARY}; }}
QLabel#Subtitle {{ color: {MUTED}; }}
QLabel#Disclaimer {{ background: #FFF4E5; border: 1px solid #F0C27B; border-radius: 6px; padding: 8px; color: {WARNING}; }}
QLabel#NotFound {{ background: #FDECEA; border: 1px solid #F5B7B1; border-radius: 6px; padding: 10px; color: {DANGER}; font-weight: bold; }}
QGroupBox {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px; padding: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; color: {PRIMARY}; font-weight: bold; }}
QPushButton {{ background: {PRIMARY}; color: white; border: none; border-radius: 6px; padding: 7px 16px; }}
QPushButton:hover {{ background: {PRIMARY_DARK}; }}
QPushButton:disabled {{ background: #9AA5B1; }}
QPushButton[kind="secondary"] {{ background: {SURFACE}; color: {PRIMARY}; border: 1px solid {PRIMARY}; }}
QPushButton[kind="danger"] {{ background: {DANGER}; }}
QPushButton[kind="accent"] {{ background: {ACCENT}; }}
QLineEdit, QComboBox, QSpinBox, QDateEdit, QTextEdit, QPlainTextEdit {{
    background: white; border: 1px solid {BORDER}; border-radius: 5px; padding: 5px; }}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{ border: 1px solid {PRIMARY}; }}
QTableView, QTableWidget {{ background: white; gridline-color: #E7EBEF; border: 1px solid {BORDER};
    selection-background-color: #DCE8F2; selection-color: {TEXT}; alternate-background-color: #F8FAFB; }}
QHeaderView::section {{ background: {PRIMARY}; color: white; padding: 6px; border: none; font-weight: bold; }}
QTabBar::tab {{ background: #E4E9EE; padding: 7px 16px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-left: 2px; }}
QTabBar::tab:selected {{ background: {PRIMARY}; color: white; }}
QStatusBar {{ background: {SURFACE}; color: {MUTED}; }}
QProgressBar {{ border: 1px solid {BORDER}; border-radius: 5px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; }}
"""
