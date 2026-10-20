"""Tema visual de Serviscraft.

Se respeta el estilo nativo de KDE (Breeze) y, si no esta disponible, se usa
Fusion. La hoja de estilos se construye a partir de la paleta activa, de modo
que la aplicacion se ve correcta tanto en modo claro como en modo oscuro.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

#: Paleta de acento propia (verde "cesped" de Minecraft) usada para el icono.
BRAND_GREEN = "#3FA34D"
BRAND_GREEN_DARK = "#2E7D3A"


def apply_theme(app: QApplication) -> None:
    """Aplica estilo, paleta de iconos y hoja de estilos."""
    available = QStyleFactory.keys()
    preferred = next((name for name in ("Breeze", "breeze") if name in available), None)
    if preferred:
        app.setStyle(preferred)
    elif "Fusion" in available:
        app.setStyle("Fusion")

    # En KDE el nombre del tema de iconos suele venir del escritorio; si no lo
    # tenemos (por ejemplo al ejecutar el AppImage), fijamos Breeze.
    if not QIcon.themeName():
        for theme in ("breeze", "breeze-dark", "hicolor"):
            if QIcon.hasThemeIcon("folder") or theme == "hicolor":
                QIcon.setThemeName(theme)
                break

    app.setStyleSheet(build_stylesheet(app.palette()))


def _rgba(color: QColor, alpha: float) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.3f})"


def build_stylesheet(palette: QPalette) -> str:
    """Genera la hoja de estilos a partir de la paleta del sistema."""
    window = palette.color(QPalette.ColorRole.Window)
    base = palette.color(QPalette.ColorRole.Base)
    text = palette.color(QPalette.ColorRole.WindowText)
    accent = palette.color(QPalette.ColorRole.Highlight)
    accent_text = palette.color(QPalette.ColorRole.HighlightedText)
    border = palette.color(QPalette.ColorRole.Mid)

    dark = window.lightness() < 128
    card_bg = QColor(base)

    return f"""
    QWidget {{
        font-size: 10pt;
    }}
    QMainWindow, QDialog {{
        background: {window.name()};
    }}

    /* ------------------------------------------------ barra lateral de servidores */
    #ServerSidebar {{
        background: {_rgba(QColor(base), 0.55)};
        border-right: 1px solid {_rgba(border, 0.5)};
    }}
    #ServerSidebarHeader {{
        padding: 10px 12px 6px 12px;
        font-weight: 600;
        color: {_rgba(text, 0.65)};
        text-transform: uppercase;
        font-size: 8.5pt;
        letter-spacing: 1px;
    }}
    QListView#ServerList {{
        background: transparent;
        border: none;
        padding: 4px 6px;
        outline: none;
    }}
    QListView#ServerList::item {{
        border-radius: 8px;
        padding: 2px;
        margin: 2px 0;
    }}
    QListView#ServerList::item:selected {{
        background: {_rgba(accent, 0.22)};
    }}
    QListView#ServerList::item:hover:!selected {{
        background: {_rgba(text, 0.06)};
    }}
    #ServerCard {{
        background: transparent;
    }}
    #ServerCardTitle {{
        font-weight: 600;
        font-size: 10.5pt;
    }}
    #ServerCardSubtitle {{
        color: {_rgba(text, 0.6)};
        font-size: 9pt;
    }}

    /* --------------------------------------------------------------- cabecera */
    #ServerHeader {{
        background: {_rgba(card_bg, 0.65)};
        border: 1px solid {_rgba(border, 0.45)};
        border-radius: 10px;
    }}
    #ServerTitle {{
        font-size: 16pt;
        font-weight: 600;
    }}
    #ServerSubtitle {{
        color: {_rgba(text, 0.65)};
    }}
    #SectionTitle {{
        font-weight: 600;
        color: {_rgba(text, 0.8)};
    }}
    #Hint {{
        color: {_rgba(text, 0.6)};
        font-size: 9pt;
    }}
    #PlatformText {{
        color: {_rgba(text, 0.75)};
        font-size: 9pt;
    }}
    #EmptyState {{
        color: {_rgba(text, 0.55)};
        font-size: 11pt;
    }}
    #MetricLabel {{
        color: {_rgba(text, 0.7)};
        font-size: 9pt;
    }}
    #MetricValue {{
        font-weight: 600;
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
    }}

    /* -------------------------------------------------- secciones con ayuda «?» */
    #SectionCard {{
        background: {_rgba(card_bg, 0.55)};
        border: 1px solid {_rgba(border, 0.45)};
        border-radius: 10px;
    }}
    #HelpTitle {{
        font-size: 13pt;
        font-weight: 600;
    }}
    #HelpButton {{
        min-width: 20px;
        max-width: 20px;
        min-height: 20px;
        max-height: 20px;
        padding: 0px;
        border-radius: 10px;
        border: 1px solid {_rgba(border, 0.7)};
        background: {_rgba(text, 0.07)};
        color: {_rgba(text, 0.75)};
        font-weight: 700;
    }}
    #HelpButton:hover {{
        background: {_rgba(accent, 0.3)};
        border-color: {_rgba(accent, 0.9)};
        color: {text.name()};
    }}
    #HelpButton:pressed {{
        background: {_rgba(accent, 0.5)};
    }}

    /* ------------------------------------------------ resumen de un vistazo (chips) */
    #Chip {{
        border-radius: 11px;
        border: 1px solid {_rgba(border, 0.45)};
        background: {_rgba(text, 0.06)};
    }}
    #Chip[tone="ok"] {{
        background: {_rgba(QColor("#2e7d32"), 0.20)};
        border-color: {_rgba(QColor("#2e7d32"), 0.55)};
    }}
    #Chip[tone="warn"] {{
        background: {_rgba(QColor("#b45309"), 0.20)};
        border-color: {_rgba(QColor("#b45309"), 0.55)};
    }}
    #Chip[tone="bad"] {{
        background: {_rgba(QColor("#b3261e"), 0.18)};
        border-color: {_rgba(QColor("#b3261e"), 0.5)};
    }}
    #Chip[tone="info"] {{
        background: {_rgba(accent, 0.18)};
        border-color: {_rgba(accent, 0.55)};
    }}
    #ChipText {{
        font-size: 9pt;
    }}

    /* ------------------------------------------------------- datos y pasos */
    #AddressText {{
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
        font-weight: 600;
        background: {_rgba(text, 0.05)};
        border: 1px solid {_rgba(border, 0.4)};
        border-radius: 6px;
        padding: 3px 8px;
    }}
    #StepNumber {{
        background: {_rgba(accent, 0.25)};
        border: 1px solid {_rgba(accent, 0.6)};
        border-radius: 10px;
        font-weight: 700;
        font-size: 9pt;
    }}

    /* -------------------------------------------------- mochila del jugador */
    #InventorySlot {{
        background: {("#1f2329" if dark else "#2b3038")};
        border: 1px solid {_rgba(border, 0.6)};
        border-radius: 5px;
    }}
    #InventorySlot QLabel#SlotName {{
        color: {("#e6e9ee" if dark else "#f2f4f8")};
        font-size: 7.5pt;
    }}
    #InventorySlot QLabel#SlotCount {{
        color: #f2c14e;
        font-size: 8pt;
        font-weight: 700;
    }}
    #InventorySlot QLabel#SlotEmpty {{
        color: rgba(255, 255, 255, 0.18);
    }}
    #SlotTitle {{
        color: {_rgba(text, 0.6)};
        font-size: 9pt;
        padding-top: 4px;
    }}
    #InventoryGrid {{
        background: transparent;
    }}

    /* ----------------------------------------------------------------- estado */
    #StatusBadge {{
        border-radius: 9px;
        padding: 2px 10px;
        font-weight: 600;
        font-size: 9pt;
    }}

    /* ----------------------------------------------------------------- botones */
    QPushButton {{
        background: {_rgba(text, 0.07)};
        border: 1px solid {_rgba(border, 0.6)};
        border-radius: 7px;
        padding: 6px 14px;
        min-height: 18px;
    }}
    QPushButton:hover {{
        background: {_rgba(text, 0.12)};
    }}
    QPushButton:pressed {{
        background: {_rgba(text, 0.18)};
    }}
    /* Botones que se quedan pulsados (por ejemplo «Seguir en vivo»): asi se ve
       de un vistazo si el seguimiento esta activado o no. */
    QPushButton:checked {{
        background: {_rgba(accent, 0.28)};
        border: 1px solid {_rgba(accent, 0.9)};
    }}
    QPushButton:checked:hover {{
        background: {_rgba(accent, 0.38)};
    }}
    QPushButton:disabled {{
        color: {_rgba(text, 0.35)};
        background: {_rgba(text, 0.03)};
        border-color: {_rgba(border, 0.3)};
    }}
    QPushButton[accent="true"] {{
        background: {accent.name()};
        color: {accent_text.name()};
        border: 1px solid {_rgba(accent.darker(120), 0.9)};
        font-weight: 600;
    }}
    QPushButton[accent="true"]:hover {{
        background: {accent.lighter(112).name()};
    }}
    QPushButton[accent="true"]:disabled {{
        background: {_rgba(accent, 0.35)};
        color: {_rgba(accent_text, 0.7)};
    }}
    QPushButton[danger="true"] {{
        color: #b3261e;
        border-color: {_rgba(QColor("#b3261e"), 0.5)};
    }}
    QPushButton[danger="true"]:hover {{
        background: {_rgba(QColor("#b3261e"), 0.14)};
    }}

    /* ---------------------------------------------------------------- entradas */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
        background: {base.name()};
        border: 1px solid {_rgba(border, 0.7)};
        border-radius: 7px;
        padding: 5px 8px;
        selection-background-color: {accent.name()};
        selection-color: {accent_text.name()};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
        border: 1px solid {accent.name()};
    }}
    QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
        color: {_rgba(text, 0.45)};
        background: {_rgba(text, 0.04)};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}

    /* ----------------------------------------------------------------- pestañas */
    QTabWidget::pane {{
        border: 1px solid {_rgba(border, 0.45)};
        border-radius: 10px;
        top: -1px;
        background: {_rgba(card_bg, 0.5)};
    }}
    QTabBar::tab {{
        background: transparent;
        padding: 8px 16px;
        margin-right: 4px;
        border: 1px solid transparent;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        color: {_rgba(text, 0.7)};
    }}
    QTabBar::tab:hover {{
        background: {_rgba(text, 0.07)};
    }}
    QTabBar::tab:selected {{
        background: {_rgba(card_bg, 0.9)};
        border-color: {_rgba(border, 0.45)};
        border-bottom-color: {_rgba(card_bg, 0.9)};
        color: {text.name()};
        font-weight: 600;
    }}

    /* ------------------------------------------------------------------ tablas */
    QTableView, QTreeView, QListView {{
        background: {base.name()};
        alternate-background-color: {_rgba(text, 0.035)};
        border: 1px solid {_rgba(border, 0.5)};
        border-radius: 8px;
        gridline-color: {_rgba(border, 0.3)};
        selection-background-color: {_rgba(accent, 0.65)};
        selection-color: {accent_text.name()};
    }}
    QHeaderView::section {{
        background: {_rgba(text, 0.06)};
        border: none;
        border-bottom: 1px solid {_rgba(border, 0.5)};
        padding: 6px 8px;
        font-weight: 600;
    }}

    /* --------------------------------------------------------------- consola */
    QPlainTextEdit#ConsoleOutput {{
        background: {("#14161a" if dark else "#1e2126")};
        color: #d7dbe0;
        border: 1px solid {_rgba(border, 0.6)};
        border-radius: 8px;
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
        font-size: 9.5pt;
        padding: 6px;
    }}
    QLineEdit#ConsoleInput {{
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
    }}

    /* ------------------------------------------------------------ barra lateral */
    QToolBar {{
        background: {_rgba(card_bg, 0.6)};
        border-bottom: 1px solid {_rgba(border, 0.45)};
        spacing: 6px;
        padding: 6px;
    }}
    QToolBar QToolButton {{
        border-radius: 7px;
        padding: 6px 10px;
    }}
    QToolBar QToolButton:hover {{
        background: {_rgba(text, 0.1)};
    }}
    QToolBar QToolButton:disabled {{
        color: {_rgba(text, 0.35)};
    }}
    QStatusBar {{
        background: {_rgba(card_bg, 0.6)};
        border-top: 1px solid {_rgba(border, 0.4)};
    }}
    QStatusBar::item {{
        border: none;
    }}
    #OperationBar {{
        background: {_rgba(accent, 0.12)};
        border-top: 1px solid {_rgba(border, 0.45)};
    }}

    /* ------------------------------------------------------------- progreso */
    QProgressBar {{
        border: 1px solid {_rgba(border, 0.6)};
        border-radius: 6px;
        background: {_rgba(text, 0.06)};
        text-align: center;
        min-height: 14px;
        font-size: 8.5pt;
    }}
    QProgressBar::chunk {{
        background: {accent.name()};
        border-radius: 5px;
    }}

    /* ------------------------------------------------------------------ varios */
    QGroupBox {{
        border: 1px solid {_rgba(border, 0.45)};
        border-radius: 9px;
        margin-top: 14px;
        padding: 12px 10px 8px 10px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
        color: {_rgba(text, 0.75)};
    }}
    QSplitter::handle {{
        background: {_rgba(border, 0.25)};
    }}
    QSplitter::handle:hover {{
        background: {_rgba(accent, 0.5)};
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {_rgba(border, 0.85)};
        background: {base.name()};
    }}
    QCheckBox::indicator {{
        border-radius: 4px;
    }}
    QRadioButton::indicator {{
        border-radius: 8px;
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        border-color: {accent.name()};
    }}
    /* Marcada: el color de acento llena la casilla, sin ambiguedad. */
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {accent.name()};
        border-color: {accent.darker(115).name()};
    }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
        background: {_rgba(text, 0.08)};
        border-color: {_rgba(border, 0.45)};
    }}
    QCheckBox::indicator:checked:disabled, QRadioButton::indicator:checked:disabled {{
        background: {_rgba(accent, 0.35)};
        border-color: {_rgba(accent, 0.4)};
    }}
    QToolTip {{
        border: 1px solid {_rgba(border, 0.6)};
        border-radius: 6px;
        padding: 4px 7px;
        background: {base.name()};
        color: {text.name()};
    }}
    """
