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

    # Colores de las acciones de jugadores. Los rellenos usan texto blanco u
    # oscuro segun su luminosidad; los botones solo con borde cambian de tono
    # para seguir leyendose en claro y en oscuro.
    green_fill = "#2E7D3A"
    green_dark = "#1F5A29"
    green_text = "#8FE39B" if dark else "#256B31"
    gold_fill = "#C79A3A"
    gold_dark = "#8A6A1E"
    gold_text = "#F0CB72" if dark else "#7A5C16"
    red_fill = "#B3261E"
    red_dark = "#7D1A15"
    orange_fill = "#B06018"
    orange_dark = "#7A3F0D"
    blue_fill = "#2C739B"
    blue_dark = "#1E5472"
    blue_text = "#8CCBEA" if dark else "#24617F"
    teal_fill = "#1F6F6B"
    teal_dark = "#134A47"
    teal_text = "#85D6D0" if dark else "#1B5F5B"
    stone_text = _rgba(text, 0.84)

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

    /* ----------------------------------------------- jugadores (estilo bloque) */
    QFrame#PlayersHero {{
        background-color: {BRAND_GREEN};
        border: 2px solid #1b4d24;
        border-radius: 2px;
    }}
    QLabel#PlayersHeroTitle {{
        color: #ffffff;
        font-size: 17pt;
        font-weight: 800;
        letter-spacing: 1px;
    }}
    QLabel#PlayersHeroSubtitle {{
        color: rgba(255, 255, 255, 0.84);
        font-size: 9.5pt;
    }}
    QLabel#PlayersHeroIcon {{
        background: transparent;
    }}
    QFrame#WhitelistBanner {{
        background: {_rgba(text, 0.035)};
        border: 2px solid {_rgba(border, 0.55)};
        border-radius: 2px;
    }}
    QFrame#WhitelistBanner[active="true"] {{
        background: {_rgba(QColor(BRAND_GREEN), 0.12)};
        border-color: {_rgba(QColor(BRAND_GREEN_DARK), 0.70)};
    }}
    QFrame#WhitelistBanner[active="false"] {{
        background: {_rgba(QColor("#C79A3A"), 0.10)};
        border-color: {_rgba(QColor("#8A6A1E"), 0.55)};
    }}
    QLabel#WhitelistTitle {{
        font-weight: 700;
        font-size: 11.5pt;
    }}
    QLabel#WhitelistState {{
        color: {_rgba(text, 0.72)};
        font-size: 9pt;
    }}
    QPushButton#WhitelistToggle {{
        background: {_rgba(text, 0.06)};
        border: 2px solid {_rgba(QColor("#8A6A1E"), 0.65)};
        border-radius: 2px;
        color: {_rgba(text, 0.88)};
        font-weight: 800;
        padding: 8px 16px;
    }}
    QPushButton#WhitelistToggle:hover {{
        background: {_rgba(text, 0.11)};
    }}
    QPushButton#WhitelistToggle:pressed {{
        background: {_rgba(text, 0.16)};
    }}
    QPushButton#WhitelistToggle:checked {{
        background: {green_fill};
        border: 2px solid {green_dark};
        color: #ffffff;
    }}
    QPushButton#WhitelistToggle:checked:hover {{
        background: {QColor(green_fill).lighter(110).name()};
    }}
    QPushButton#WhitelistToggle:checked:pressed {{
        background: {QColor(green_fill).darker(112).name()};
    }}
    QPushButton#WhitelistToggle:disabled {{
        background: {_rgba(text, 0.03)};
        border-color: {_rgba(border, 0.40)};
        color: {_rgba(text, 0.45)};
    }}
    QPushButton#InviteButton {{
        background: {green_fill};
        border: 2px solid {green_dark};
        border-radius: 2px;
        color: #ffffff;
        font-weight: 800;
        padding: 7px 16px;
    }}
    QPushButton#InviteButton:hover {{
        background: {QColor(green_fill).lighter(110).name()};
    }}
    QPushButton#InviteButton:pressed {{
        background: {QColor(green_fill).darker(112).name()};
    }}
    QPushButton#InviteButton:disabled {{
        background: {_rgba(QColor(green_fill), 0.30)};
        border-color: {_rgba(QColor(green_dark), 0.45)};
        color: rgba(255, 255, 255, 0.62);
    }}
    #PlayersPanel QPushButton {{
        border-radius: 2px;
        padding: 7px 14px;
        min-height: 20px;
    }}
    #PlayersPanel QPushButton[panelRole="stone"] {{
        background: {_rgba(text, 0.045)};
        border: 2px solid {_rgba(border, 0.62)};
        color: {stone_text};
        font-weight: 700;
    }}
    #PlayersPanel QPushButton[panelRole="stone"]:hover {{
        background: {_rgba(text, 0.10)};
    }}
    #PlayersPanel QPushButton[panelRole="stone"]:pressed {{
        background: {_rgba(text, 0.15)};
    }}
    #PlayersPanel QPushButton[panelRole="stone"]:disabled {{
        background: {_rgba(text, 0.02)};
        border-color: {_rgba(border, 0.32)};
        color: {_rgba(text, 0.40)};
    }}
    #PlayersPanel QPushButton[panelRole="list"] {{
        background: {_rgba(QColor("#3C8FBF"), 0.10)};
        border: 2px solid {_rgba(QColor("#2C739B"), 0.60)};
        color: {blue_text};
        font-weight: 700;
    }}
    #PlayersPanel QPushButton[panelRole="list"]:hover {{
        background: {_rgba(QColor("#3C8FBF"), 0.18)};
    }}
    #PlayersPanel QPushButton[panelRole="list"]:pressed {{
        background: {_rgba(QColor("#3C8FBF"), 0.24)};
    }}
    #PlayersPanel QPushButton[panelRole="list"]:disabled {{
        background: {_rgba(text, 0.02)};
        border-color: {_rgba(border, 0.32)};
        color: {_rgba(text, 0.40)};
    }}
    /* Cada accion lleva su color: permisos (oro), acceso (verde), sanciones
       (naranja/rojo) e inventario (azul). La fila deja de ser un bloque verde
       uniforme y cada boton se reconoce por su tono. */
    #PlayersPanel QPushButton[playerAction="op"] {{
        background: {gold_fill};
        border: 2px solid {gold_dark};
        color: #241b07;
        font-weight: 800;
    }}
    #PlayersPanel QPushButton[playerAction="op"]:hover {{
        background: {QColor(gold_fill).lighter(110).name()};
    }}
    #PlayersPanel QPushButton[playerAction="op"]:pressed {{
        background: {QColor(gold_fill).darker(112).name()};
    }}
    #PlayersPanel QPushButton[playerAction="deop"] {{
        background: {_rgba(QColor(gold_fill), 0.14)};
        border: 2px solid {_rgba(QColor(gold_fill), 0.70)};
        color: {gold_text};
        font-weight: 700;
    }}
    #PlayersPanel QPushButton[playerAction="deop"]:hover {{
        background: {_rgba(QColor(gold_fill), 0.22)};
    }}
    #PlayersPanel QPushButton[playerAction="deop"]:pressed {{
        background: {_rgba(QColor(gold_fill), 0.30)};
    }}
    #PlayersPanel QPushButton[playerAction="whitelist_add"] {{
        background: {green_fill};
        border: 2px solid {green_dark};
        color: #ffffff;
        font-weight: 800;
    }}
    #PlayersPanel QPushButton[playerAction="whitelist_add"]:hover {{
        background: {QColor(green_fill).lighter(110).name()};
    }}
    #PlayersPanel QPushButton[playerAction="whitelist_add"]:pressed {{
        background: {QColor(green_fill).darker(112).name()};
    }}
    #PlayersPanel QPushButton[playerAction="whitelist_remove"] {{
        background: {_rgba(QColor(BRAND_GREEN), 0.14)};
        border: 2px solid {_rgba(QColor(BRAND_GREEN_DARK), 0.65)};
        color: {green_text};
        font-weight: 700;
    }}
    #PlayersPanel QPushButton[playerAction="whitelist_remove"]:hover {{
        background: {_rgba(QColor(BRAND_GREEN), 0.22)};
    }}
    #PlayersPanel QPushButton[playerAction="whitelist_remove"]:pressed {{
        background: {_rgba(QColor(BRAND_GREEN), 0.30)};
    }}
    #PlayersPanel QPushButton[playerAction="kick"] {{
        background: {orange_fill};
        border: 2px solid {orange_dark};
        color: #ffffff;
        font-weight: 800;
    }}
    #PlayersPanel QPushButton[playerAction="kick"]:hover {{
        background: {QColor(orange_fill).lighter(110).name()};
    }}
    #PlayersPanel QPushButton[playerAction="kick"]:pressed {{
        background: {QColor(orange_fill).darker(112).name()};
    }}
    #PlayersPanel QPushButton[playerAction="ban"] {{
        background: {red_fill};
        border: 2px solid {red_dark};
        color: #ffffff;
        font-weight: 800;
    }}
    #PlayersPanel QPushButton[playerAction="ban"]:hover {{
        background: {QColor(red_fill).lighter(110).name()};
    }}
    #PlayersPanel QPushButton[playerAction="ban"]:pressed {{
        background: {QColor(red_fill).darker(112).name()};
    }}
    #PlayersPanel QPushButton[playerAction="pardon"] {{
        background: {teal_fill};
        border: 2px solid {teal_dark};
        color: #ffffff;
        font-weight: 800;
    }}
    #PlayersPanel QPushButton[playerAction="pardon"]:hover {{
        background: {QColor(teal_fill).lighter(110).name()};
    }}
    #PlayersPanel QPushButton[playerAction="pardon"]:pressed {{
        background: {QColor(teal_fill).darker(112).name()};
    }}
    #PlayersPanel QPushButton[playerAction="inventario"] {{
        background: {blue_fill};
        border: 2px solid {blue_dark};
        color: #ffffff;
        font-weight: 800;
    }}
    #PlayersPanel QPushButton[playerAction="inventario"]:hover {{
        background: {QColor(blue_fill).lighter(110).name()};
    }}
    #PlayersPanel QPushButton[playerAction="inventario"]:pressed {{
        background: {QColor(blue_fill).darker(112).name()};
    }}
    #PlayersPanel QPushButton[playerAction="op"]:disabled,
    #PlayersPanel QPushButton[playerAction="deop"]:disabled,
    #PlayersPanel QPushButton[playerAction="whitelist_add"]:disabled,
    #PlayersPanel QPushButton[playerAction="whitelist_remove"]:disabled,
    #PlayersPanel QPushButton[playerAction="kick"]:disabled,
    #PlayersPanel QPushButton[playerAction="ban"]:disabled,
    #PlayersPanel QPushButton[playerAction="pardon"]:disabled,
    #PlayersPanel QPushButton[playerAction="inventario"]:disabled {{
        background: {_rgba(text, 0.055)};
        border-color: {_rgba(border, 0.35)};
        color: {_rgba(text, 0.42)};
    }}
    #PlayersPanel QTableWidget {{
        border: 2px solid {_rgba(border, 0.55)};
        border-radius: 2px;
    }}

    /* ------------------------------------------- unirse: cabecera y direcciones */
    QToolButton#JoinHeroHelp {{
        background: rgba(255, 255, 255, 0.16);
        border: 1px solid rgba(255, 255, 255, 0.60);
        color: #ffffff;
        font-weight: 700;
    }}
    QToolButton#JoinHeroHelp:hover {{
        background: rgba(255, 255, 255, 0.30);
        border-color: rgba(255, 255, 255, 0.90);
    }}
    QFrame#PrimaryAddressCard {{
        background: {_rgba(QColor(BRAND_GREEN), 0.10)};
        border: 2px solid {_rgba(QColor(BRAND_GREEN_DARK), 0.55)};
        border-radius: 4px;
    }}
    QFrame#AddressCard {{
        background: {_rgba(text, 0.035)};
        border: 1px solid {_rgba(border, 0.45)};
        border-radius: 4px;
    }}
    QLabel#AddressCardTitle {{
        font-weight: 700;
        color: {_rgba(text, 0.82)};
    }}
    QLabel#PrimaryAddressText {{
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
        font-size: 13pt;
        font-weight: 700;
        background: {_rgba(base, 0.55)};
        border: 1px solid {_rgba(QColor(BRAND_GREEN_DARK), 0.45)};
        border-radius: 2px;
        padding: 8px 12px;
    }}
    QPushButton#CopyPrimary {{
        background: {BRAND_GREEN};
        border: 2px solid {BRAND_GREEN_DARK};
        border-radius: 2px;
        color: #ffffff;
        font-weight: 800;
        padding: 9px 18px;
    }}
    QPushButton#CopyPrimary:hover {{
        background: {QColor(BRAND_GREEN).lighter(112).name()};
    }}
    QPushButton#CopyPrimary:pressed {{
        background: {BRAND_GREEN_DARK};
    }}
    QPushButton#CopyPrimary:disabled {{
        background: {_rgba(QColor(BRAND_GREEN), 0.35)};
        border-color: {_rgba(QColor(BRAND_GREEN_DARK), 0.40)};
        color: rgba(255, 255, 255, 0.70);
    }}
    QPushButton#CopyButton {{
        border-radius: 2px;
        padding: 6px 12px;
    }}
    QPushButton#TokenToggle {{
        border-radius: 2px;
        padding: 5px 14px;
    }}
    QLineEdit#DdnsPreview {{
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
        font-size: 11pt;
        font-weight: 700;
        color: {text.name()};
        placeholder-text-color: {_rgba(text, 0.42)};
        background: {_rgba(QColor(BRAND_GREEN), 0.10)};
        border: 1px solid {_rgba(QColor(BRAND_GREEN_DARK), 0.55)};
        border-radius: 4px;
        padding: 7px 10px;
    }}
    QLabel#FieldError {{
        color: #b3261e;
        font-size: 9pt;
    }}
    QPushButton#ApplyAccounts {{
        background: {BRAND_GREEN};
        border: 2px solid {BRAND_GREEN_DARK};
        border-radius: 2px;
        color: #ffffff;
        font-weight: 800;
        padding: 8px 16px;
    }}
    QPushButton#ApplyAccounts:hover {{
        background: {QColor(BRAND_GREEN).lighter(112).name()};
    }}
    QPushButton#ApplyAccounts:pressed {{
        background: {BRAND_GREEN_DARK};
    }}
    QPushButton#ApplyAccounts:disabled {{
        background: {_rgba(QColor(BRAND_GREEN), 0.35)};
        border-color: {_rgba(QColor(BRAND_GREEN_DARK), 0.45)};
        color: rgba(255, 255, 255, 0.70);
    }}

    /* ------------------------------------------ propiedades: tarjetas y mandos */
    QFrame#PropertiesHero {{
        background: transparent;
        border: none;
    }}
    QLabel#PropertiesHeroTitle {{
        color: #ffffff;
        font-size: 16pt;
        font-weight: 800;
        letter-spacing: 1px;
    }}
    QLabel#PropertiesHeroSubtitle {{
        color: rgba(255, 255, 255, 0.88);
        font-size: 9.5pt;
    }}
    QLabel#PropertiesHeroIcon {{
        background: transparent;
    }}
    QToolButton#PropertiesHeroHelp {{
        background: rgba(255, 255, 255, 0.16);
        border: 2px solid rgba(255, 255, 255, 0.62);
        border-radius: 2px;
        color: #ffffff;
        font-weight: 700;
    }}
    QToolButton#PropertiesHeroHelp:hover {{
        background: rgba(255, 255, 255, 0.30);
        border-color: rgba(255, 255, 255, 0.92);
    }}
    QFrame#PropertyCard {{
        background: {_rgba(card_bg, 0.70)};
        border: 2px solid {_rgba(border, 0.50)};
        border-radius: 3px;
    }}
    QFrame#PropertyCard[accent="green"] {{
        border-color: {_rgba(QColor("#2E7D3A"), 0.60)};
    }}
    QFrame#PropertyCard[accent="gold"] {{
        border-color: {_rgba(QColor("#A87B24"), 0.62)};
    }}
    QFrame#PropertyCard[accent="blue"] {{
        border-color: {_rgba(QColor("#2C739B"), 0.62)};
    }}
    QFrame#PropertyCard[accent="brown"] {{
        border-color: {_rgba(QColor("#8A5A2B"), 0.62)};
    }}
    QFrame#PropertyCard QLabel#SectionTitle {{
        font-size: 12.5pt;
        font-weight: 800;
        color: {_rgba(text, 0.92)};
    }}
    QLabel#PropertyName {{
        color: {text.name()};
        font-size: 10.5pt;
        font-weight: 700;
    }}
    QLabel#PropertyHint {{
        color: {_rgba(text, 0.60)};
        font-size: 8.8pt;
        padding-top: 1px;
    }}
    QWidget#PropertiesBasicPage,
    QWidget#PropertiesBasicContent {{
        background: transparent;
    }}
    QTabWidget#PropertiesTabs::pane {{
        background: {_rgba(card_bg, 0.38)};
        border: 2px solid {_rgba(border, 0.50)};
        border-radius: 3px;
        top: -2px;
    }}
    QTabWidget#PropertiesTabs QTabBar::tab {{
        background: {_rgba(text, 0.06)};
        border: 2px solid {_rgba(border, 0.45)};
        border-bottom: none;
        border-top-left-radius: 3px;
        border-top-right-radius: 3px;
        color: {_rgba(text, 0.72)};
        font-weight: 600;
        padding: 7px 18px;
        margin-right: 4px;
    }}
    QTabWidget#PropertiesTabs QTabBar::tab:hover {{
        background: {_rgba(text, 0.13)};
        color: {text.name()};
    }}
    QTabWidget#PropertiesTabs QTabBar::tab:selected {{
        background: {BRAND_GREEN};
        border-color: #1b4d24;
        color: #ffffff;
        font-weight: 800;
    }}
    QTabWidget#PropertiesTabs QTabBar::tab:selected:hover {{
        background: {QColor(BRAND_GREEN).lighter(108).name()};
    }}
    #PropertiesPanel #Chip {{
        background: {_rgba(text, 0.05)};
        border: 2px solid {_rgba(border, 0.45)};
        border-radius: 2px;
    }}
    #PropertiesPanel #Chip[tone="ok"] {{
        background: {_rgba(QColor("#2e7d32"), 0.20)};
        border-color: {_rgba(QColor("#2e7d32"), 0.60)};
    }}
    #PropertiesPanel #Chip[tone="warn"] {{
        background: {_rgba(QColor("#b45309"), 0.20)};
        border-color: {_rgba(QColor("#b45309"), 0.60)};
    }}
    #PropertiesPanel #Chip[tone="info"] {{
        background: {_rgba(accent, 0.16)};
        border-color: {_rgba(accent, 0.55)};
    }}
    #PropertiesPanel QLineEdit,
    #PropertiesPanel QComboBox,
    #PropertiesPanel QSpinBox {{
        background: {base.name()};
        border: 2px solid {_rgba(border, 0.62)};
        border-radius: 2px;
        padding: 5px 9px;
        min-height: 19px;
    }}
    #PropertiesPanel QLineEdit:focus,
    #PropertiesPanel QComboBox:focus,
    #PropertiesPanel QSpinBox:focus {{
        border: 2px solid {BRAND_GREEN};
    }}
    #PropertiesPanel QLineEdit:disabled,
    #PropertiesPanel QComboBox:disabled,
    #PropertiesPanel QSpinBox:disabled {{
        color: {_rgba(text, 0.45)};
        background: {_rgba(text, 0.04)};
        border-color: {_rgba(border, 0.35)};
    }}
    QLineEdit#PropertiesSearch {{
        background: {base.name()};
        border: 2px solid {_rgba(border, 0.55)};
        border-radius: 2px;
        padding: 7px 10px;
        font-size: 10pt;
    }}
    QTableWidget#PropertiesTable {{
        background: {base.name()};
        alternate-background-color: {_rgba(text, 0.035)};
        border: 2px solid {_rgba(border, 0.55)};
        border-radius: 2px;
        gridline-color: {_rgba(border, 0.30)};
        selection-background-color: {_rgba(accent, 0.65)};
        selection-color: {accent_text.name()};
    }}
    QTableWidget#PropertiesTable QHeaderView::section {{
        background: {_rgba(QColor(BRAND_GREEN), 0.20)};
        border: none;
        border-bottom: 2px solid {_rgba(QColor(BRAND_GREEN_DARK), 0.55)};
        padding: 6px 8px;
        font-weight: 700;
    }}
    QPlainTextEdit#PropertiesTextEditor {{
        background: {("#14161a" if dark else "#f7f8fa")};
        color: {("#d7dbe0" if dark else "#22262b")};
        border: 2px solid {_rgba(border, 0.55)};
        border-radius: 2px;
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
        font-size: 9.5pt;
        padding: 8px;
    }}
    #PropertiesPanel QPushButton {{
        border-radius: 2px;
        padding: 7px 15px;
    }}
    #PropertiesPanel QPushButton[accent="true"] {{
        background: {BRAND_GREEN};
        border: 2px solid {BRAND_GREEN_DARK};
        border-radius: 2px;
        color: #ffffff;
        font-weight: 800;
        padding: 7px 16px;
    }}
    #PropertiesPanel QPushButton[accent="true"]:hover {{
        background: {QColor(BRAND_GREEN).lighter(110).name()};
    }}
    #PropertiesPanel QPushButton[accent="true"]:pressed {{
        background: {BRAND_GREEN_DARK};
    }}
    #PropertiesPanel QPushButton[accent="true"]:disabled {{
        background: {_rgba(QColor(BRAND_GREEN), 0.35)};
        border-color: {_rgba(QColor(BRAND_GREEN_DARK), 0.45)};
        color: rgba(255, 255, 255, 0.70);
    }}

    /* ------------------------------------- detalles y mods: tarjetas de bloque */
    QToolButton#MinecraftHeroHelp {{
        background: rgba(255, 255, 255, 0.16);
        border: 2px solid rgba(255, 255, 255, 0.62);
        border-radius: 2px;
        color: #ffffff;
        font-weight: 700;
    }}
    QToolButton#MinecraftHeroHelp:hover {{
        background: rgba(255, 255, 255, 0.30);
        border-color: rgba(255, 255, 255, 0.92);
    }}
    QFrame#SectionCard[accent] {{
        border-radius: 3px;
        border-width: 2px;
    }}
    QFrame#SectionCard[accent="green"] {{
        border-color: {_rgba(QColor("#2E7D3A"), 0.62)};
    }}
    QFrame#SectionCard[accent="gold"] {{
        border-color: {_rgba(QColor("#A87B24"), 0.64)};
    }}
    QFrame#SectionCard[accent="blue"] {{
        border-color: {_rgba(QColor("#2C739B"), 0.64)};
    }}
    QFrame#SectionCard[accent="brown"] {{
        border-color: {_rgba(QColor("#8A5A2B"), 0.64)};
    }}
    QFrame#SectionCard[accent] QLabel#SectionTitle {{
        font-size: 12.5pt;
        font-weight: 800;
        color: {_rgba(text, 0.92)};
    }}

    /* ------------------------------------------------------- pestana Detalles */
    #DetailsPanel QLabel#DetailKey {{
        color: {_rgba(text, 0.62)};
        font-weight: 600;
    }}
    #DetailsPanel QLabel#DetailValue {{
        color: {text.name()};
        font-weight: 600;
    }}
    #DetailsPanel QFrame#DetailSlot {{
        background: {_rgba(text, 0.045)};
        border: 1px solid {_rgba(border, 0.35)};
        border-radius: 2px;
    }}
    QLineEdit#DetailsPath {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {_rgba(border, 0.35)};
        border-radius: 0px;
        padding: 1px 1px 2px 1px;
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
        font-size: 9.5pt;
    }}
    QLineEdit#DetailsPath:focus {{
        border-bottom: 1px solid {BRAND_GREEN};
    }}
    #DetailsPanel QPlainTextEdit {{
        background: {base.name()};
        border: 2px solid {_rgba(border, 0.55)};
        border-radius: 2px;
        padding: 6px;
    }}
    #DetailsPanel QPushButton {{
        border-radius: 2px;
        padding: 7px 15px;
    }}
    #DetailsPanel QPushButton[accent="true"] {{
        background: {BRAND_GREEN};
        border: 2px solid {BRAND_GREEN_DARK};
        color: #ffffff;
        font-weight: 800;
    }}
    #DetailsPanel QPushButton[accent="true"]:hover {{
        background: {QColor(BRAND_GREEN).lighter(110).name()};
    }}
    #DetailsPanel QPushButton[accent="true"]:pressed {{
        background: {BRAND_GREEN_DARK};
    }}

    /* ----------------------------------------------------------- pestana Mods */
    #ModsPanel QPushButton {{
        border-radius: 2px;
        padding: 7px 15px;
    }}
    #ModsPanel QPushButton[accent="true"] {{
        background: {QColor("#C79A3A").name()};
        border: 2px solid #8A6A1E;
        border-radius: 2px;
        color: #241b07;
        font-weight: 800;
    }}
    #ModsPanel QPushButton[accent="true"]:hover {{
        background: {QColor("#C79A3A").lighter(110).name()};
    }}
    #ModsPanel QPushButton[accent="true"]:pressed {{
        background: {QColor("#C79A3A").darker(112).name()};
    }}
    #ModsPanel QPushButton[accent="true"]:disabled {{
        background: {_rgba(QColor("#C79A3A"), 0.35)};
        border-color: {_rgba(QColor("#8A6A1E"), 0.45)};
        color: rgba(36, 27, 7, 0.65);
    }}
    #ModsPanel QPushButton[danger="true"] {{
        color: #b3261e;
        border-color: {_rgba(QColor("#b3261e"), 0.55)};
    }}
    #ModsPanel QPushButton[danger="true"]:hover {{
        background: {_rgba(QColor("#b3261e"), 0.14)};
    }}
    QTableWidget#ModsTable,
    QTableWidget#MissingModsTable {{
        background: {base.name()};
        alternate-background-color: {_rgba(text, 0.035)};
        border: 2px solid {_rgba(border, 0.55)};
        border-radius: 2px;
        gridline-color: {_rgba(border, 0.30)};
        selection-background-color: {_rgba(QColor("#C79A3A"), 0.55)};
        selection-color: #241b07;
    }}
    QTableWidget#ModsTable QHeaderView::section {{
        background: {_rgba(QColor("#C79A3A"), 0.22)};
        border: none;
        border-bottom: 2px solid {_rgba(QColor("#8A6A1E"), 0.58)};
        padding: 6px 8px;
        font-weight: 700;
    }}
    QTableWidget#MissingModsTable QHeaderView::section {{
        background: {_rgba(QColor("#3C8FBF"), 0.20)};
        border: none;
        border-bottom: 2px solid {_rgba(QColor("#2C739B"), 0.58)};
        padding: 6px 8px;
        font-weight: 700;
    }}
    QTableWidget#ModsTable::item:hover,
    QTableWidget#MissingModsTable::item:hover {{
        background: {_rgba(text, 0.06)};
    }}
    QFrame#ModsInstalledSeparator {{
        background: {_rgba(QColor("#C79A3A"), 0.35)};
        border: none;
    }}
    QFrame#ModsMissingSeparator {{
        background: {_rgba(QColor("#3C8FBF"), 0.35)};
        border: none;
    }}

    /* ------------------------------------------ jugadores: tabla y acciones */
    QTableWidget#PlayersTable {{
        background: {base.name()};
        alternate-background-color: {_rgba(text, 0.030)};
        border: 2px solid {_rgba(border, 0.50)};
        border-radius: 2px;
        gridline-color: transparent;
        selection-background-color: {_rgba(accent, 0.58)};
        selection-color: {accent_text.name()};
    }}
    QTableWidget#PlayersTable QHeaderView::section {{
        background: {_rgba(QColor("#3C8FBF"), 0.18)};
        border: none;
        border-bottom: 2px solid {_rgba(QColor("#2C739B"), 0.55)};
        padding: 7px 8px;
        font-weight: 700;
    }}
    QTableWidget#PlayersTable::item {{
        padding: 2px 4px;
    }}
    QFrame#PlayerActionsPanel {{
        background: {_rgba(text, 0.035)};
        border: 1px solid {_rgba(border, 0.45)};
        border-left: 3px solid {_rgba(QColor("#3C8FBF"), 0.65)};
        border-radius: 3px;
    }}

    /* ------------------------------------------- catalogo de Modrinth */
    QLineEdit#CatalogSearch {{
        background: {base.name()};
        border: 2px solid {_rgba(border, 0.55)};
        border-radius: 2px;
        padding: 7px 10px;
    }}
    QLineEdit#CatalogSearch:focus {{
        border-color: #3C8FBF;
    }}
    QFrame#CatalogToolbar {{
        background: {_rgba(text, 0.035)};
        border: 1px solid {_rgba(border, 0.45)};
        border-radius: 3px;
    }}
    QTableWidget#CatalogTable {{
        background: {base.name()};
        color: {text.name()};
        alternate-background-color: {_rgba(text, 0.030)};
        border: 2px solid {_rgba(border, 0.50)};
        border-radius: 2px;
        gridline-color: transparent;
        selection-background-color: {_rgba(accent, 0.58)};
        selection-color: {accent_text.name()};
    }}
    QTableWidget#CatalogTable QHeaderView::section {{
        background: {_rgba(QColor("#3C8FBF"), 0.18)};
        border: none;
        border-bottom: 2px solid {_rgba(QColor("#2C739B"), 0.58)};
        padding: 7px 8px;
        font-weight: 700;
    }}
    QTableWidget#CatalogTable[catalogMode="mods"] QHeaderView::section {{
        background: {_rgba(QColor("#C79A3A"), 0.20)};
        border-bottom-color: {_rgba(QColor("#8A6A1E"), 0.58)};
    }}
    QFrame#CatalogDetails {{
        background: {_rgba(text, 0.032)};
        border: 1px solid {_rgba(border, 0.45)};
        border-left: 3px solid {_rgba(QColor("#3C8FBF"), 0.72)};
        border-radius: 3px;
    }}
    QFrame#CatalogDetails[catalogMode="mods"] {{
        border-left-color: {_rgba(QColor("#C79A3A"), 0.80)};
    }}
    QLabel#CatalogDetailsTitle {{
        font-size: 11pt;
        font-weight: 800;
        color: {_rgba(text, 0.92)};
    }}
    QLabel#CatalogDetailsMeta {{
        color: {_rgba(text, 0.62)};
        font-size: 8.8pt;
    }}
    QLabel#CatalogDetailsText {{
        color: {_rgba(text, 0.78)};
        font-size: 9pt;
    }}

    /* --------------------------------- versiones publicadas y contenido elegido */
    QFrame#CatalogVersions {{
        background: {_rgba(text, 0.028)};
        border: 1px solid {_rgba(border, 0.42)};
        border-left: 3px solid {_rgba(QColor("#3C8FBF"), 0.58)};
        border-radius: 3px;
    }}
    QFrame#CatalogVersions[catalogMode="mods"] {{
        border-left-color: {_rgba(QColor("#C79A3A"), 0.72)};
    }}
    QLabel#CatalogVersionsTitle {{
        color: {_rgba(text, 0.82)};
        font-size: 9.2pt;
        font-weight: 700;
    }}
    QTableWidget#CatalogVersionsTable {{
        background: {base.name()};
        color: {text.name()};
        alternate-background-color: {_rgba(text, 0.030)};
        border: 1px solid {_rgba(border, 0.42)};
        border-radius: 2px;
        gridline-color: transparent;
        selection-background-color: {_rgba(QColor("#3C8FBF"), 0.42)};
        selection-color: {_rgba(text, 0.95)};
    }}
    QTableWidget#CatalogVersionsTable QHeaderView::section {{
        background: {_rgba(QColor("#3C8FBF"), 0.14)};
        border: none;
        border-bottom: 1px solid {_rgba(border, 0.50)};
        padding: 4px 6px;
        font-size: 8.6pt;
        font-weight: 700;
        color: {_rgba(text, 0.76)};
    }}
    QTableWidget#CatalogVersionsTable[catalogMode="mods"] QHeaderView::section {{
        background: {_rgba(QColor("#C79A3A"), 0.16)};
    }}
    QTableWidget#CatalogVersionsTable::item {{
        padding: 3px 5px;
    }}
    QPushButton#CatalogInstall {{
        background: {QColor("#3C8FBF").name()};
        border: 2px solid #2C739B;
        border-radius: 2px;
        color: #ffffff;
        font-weight: 800;
        padding: 7px 16px;
    }}
    QPushButton#CatalogInstall:hover {{
        background: {QColor("#3C8FBF").lighter(110).name()};
    }}
    QPushButton#CatalogInstall:pressed {{
        background: {QColor("#3C8FBF").darker(112).name()};
    }}
    QPushButton#CatalogInstall[catalogMode="mods"] {{
        background: {QColor("#C79A3A").name()};
        border-color: #8A6A1E;
        color: #241b07;
    }}
    QPushButton#CatalogInstall[catalogMode="mods"]:hover {{
        background: {QColor("#C79A3A").lighter(110).name()};
    }}
    QPushButton#CatalogInstall[catalogMode="mods"]:pressed {{
        background: {QColor("#C79A3A").darker(112).name()};
    }}
    QPushButton#CatalogInstall:disabled {{
        background: {_rgba(text, 0.10)};
        border-color: {_rgba(border, 0.45)};
        color: {_rgba(text, 0.38)};
    }}
    QListWidget#ContentSelectedList {{
        background: {base.name()};
        color: {text.name()};
        border: 1px solid {_rgba(border, 0.50)};
        border-left: 3px solid {_rgba(QColor(BRAND_GREEN), 0.72)};
        border-radius: 3px;
        padding: 3px;
        outline: none;
    }}
    QListWidget#ContentSelectedList::item {{
        padding: 4px 6px;
        border-radius: 2px;
    }}
    QListWidget#ContentSelectedList::item:hover:!selected {{
        background: {_rgba(text, 0.05)};
    }}
    QListWidget#ContentSelectedList::item:selected {{
        background: {_rgba(accent, 0.30)};
        color: {text.name()};
    }}
    #PluginsPanel {{
        background: transparent;
    }}

    /* -------------------------------------- ranuras, avisos y zona de arrastre */
    QFrame#MinecraftEmpty {{
        background: {_rgba(text, 0.035)};
        border: 2px dashed {_rgba(border, 0.55)};
        border-radius: 3px;
    }}
    QLabel#MinecraftEmptyTitle {{
        font-size: 10.5pt;
        font-weight: 800;
        color: {_rgba(text, 0.88)};
    }}
    QLabel#MinecraftEmptyText {{
        color: {_rgba(text, 0.64)};
        font-size: 9pt;
    }}
    QFrame#MinecraftDropZone {{
        background: {_rgba(QColor("#C79A3A"), 0.10)};
        border: 2px dashed {_rgba(QColor("#A87B24"), 0.62)};
        border-radius: 3px;
    }}
    QFrame#MinecraftDropZone:hover {{
        background: {_rgba(QColor("#C79A3A"), 0.18)};
        border-color: {_rgba(QColor("#C79A3A"), 0.90)};
    }}
    QFrame#MinecraftDropZone[dragActive="true"] {{
        background: {_rgba(QColor("#3FA34D"), 0.20)};
        border: 2px solid {BRAND_GREEN};
    }}
    QFrame#MinecraftDropZone:disabled {{
        background: {_rgba(text, 0.03)};
        border-color: {_rgba(border, 0.35)};
    }}
    QLabel#MinecraftDropTitle {{
        font-size: 10.5pt;
        font-weight: 800;
        color: {_rgba(text, 0.90)};
    }}
    QLabel#MinecraftDropHint {{
        color: {_rgba(text, 0.64)};
        font-size: 9pt;
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
    QFrame#ConsoleStatusBar {{
        background: #1b1e24;
        border: 1px solid #0d0f12;
        border-radius: 3px;
    }}
    QLabel#ConsoleStatusText {{
        color: #c6ccd4;
        font-size: 9pt;
    }}
    QLabel#ConsoleCounter {{
        color: #8d95a1;
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
        font-size: 8.5pt;
    }}
    QLabel#ConsoleStateBadge {{
        background: #2a2f37;
        border: 1px solid #3b424d;
        border-radius: 3px;
        color: #aab1bc;
        font-size: 7.8pt;
        font-weight: 800;
        letter-spacing: 1px;
        padding: 2px 7px;
    }}
    QLabel#ConsoleStateBadge[tone="running"] {{
        background: {_rgba(QColor(BRAND_GREEN), 0.22)};
        border-color: {_rgba(QColor("#7fd6a2"), 0.65)};
        color: #8fe39b;
    }}
    QLabel#ConsoleStateBadge[tone="paused"] {{
        background: {_rgba(QColor("#b45309"), 0.22)};
        border-color: {_rgba(QColor("#ffcc66"), 0.55)};
        color: #ffcc66;
    }}
    QLabel#ConsoleStateBadge[tone="stopped"] {{
        background: {_rgba(QColor("#78808c"), 0.16)};
        border-color: {_rgba(QColor("#a8adb5"), 0.40)};
        color: #c2c8d0;
    }}
    QLabel#ConsoleStateBadge[tone="none"] {{
        background: {_rgba(QColor("#78808c"), 0.12)};
        border-color: {_rgba(QColor("#a8adb5"), 0.25)};
        color: #9aa2ad;
    }}
    QFrame#ConsoleToolbar {{
        background: {_rgba(text, 0.030)};
        border: 1px solid {_rgba(border, 0.42)};
        border-radius: 3px;
    }}
    QLineEdit#ConsoleFilter {{
        background: {base.name()};
        border: 2px solid {_rgba(border, 0.55)};
        border-radius: 2px;
        padding: 6px 9px;
    }}
    QLineEdit#ConsoleFilter:focus {{
        border-color: {BRAND_GREEN};
    }}
    QFrame#ConsoleTerminal {{
        background: #121418;
        border: 2px solid #080a0d;
        border-radius: 4px;
    }}
    QFrame#ConsoleTerminalBar {{
        background: #1b1e24;
        border-bottom: 1px solid #080a0d;
    }}
    QLabel#ConsoleTerminalTitle {{
        color: #9aa2ad;
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
        font-size: 8pt;
        font-weight: 700;
        letter-spacing: 1px;
    }}
    QLabel#ConsoleLegend {{
        color: #8d95a1;
        font-size: 8pt;
    }}
    QPlainTextEdit#ConsoleOutput {{
        background: #121418;
        color: #d7dbe0;
        border: none;
        border-radius: 0;
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
        font-size: 9.5pt;
        padding: 8px;
        selection-background-color: {BRAND_GREEN_DARK};
    }}
    QFrame#ConsoleCommandBar {{
        background: #1b1e24;
        border-top: 1px solid #080a0d;
    }}
    QLabel#ConsolePrompt {{
        color: #7fd6a2;
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
        font-size: 13pt;
        font-weight: 700;
        padding: 0 2px;
    }}
    QLineEdit#ConsoleInput {{
        background: #0e1014;
        color: #e6e9ee;
        border: 1px solid #2b313a;
        border-radius: 3px;
        padding: 6px 9px;
        font-family: "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace;
        selection-background-color: {BRAND_GREEN_DARK};
    }}
    QLineEdit#ConsoleInput:focus {{
        border: 1px solid {BRAND_GREEN};
    }}
    QLineEdit#ConsoleInput:disabled {{
        background: #121419;
        color: #6c737d;
        border-color: #242930;
    }}
    QFrame#ConsoleCommandBar QComboBox {{
        background: #0e1014;
        color: #d7dbe0;
        border: 1px solid #2b313a;
        border-radius: 3px;
        padding: 5px 8px;
    }}
    QFrame#ConsoleCommandBar QComboBox:disabled {{
        background: #121419;
        color: #6c737d;
        border-color: #242930;
    }}
    QFrame#ConsoleCommandBar QComboBox QAbstractItemView {{
        background: #1b1e24;
        color: #d7dbe0;
        selection-background-color: {BRAND_GREEN_DARK};
        selection-color: #ffffff;
    }}
    QFrame#ConsoleCommandBar QPushButton {{
        background: {BRAND_GREEN};
        border: 2px solid #1b4d24;
        border-radius: 2px;
        color: #ffffff;
        font-weight: 700;
        padding: 6px 12px;
    }}
    QFrame#ConsoleCommandBar QPushButton:hover {{
        background: {QColor(BRAND_GREEN).lighter(110).name()};
    }}
    QFrame#ConsoleCommandBar QPushButton:pressed {{
        background: {BRAND_GREEN_DARK};
    }}
    QFrame#ConsoleCommandBar QPushButton:disabled {{
        background: #2b3138;
        border-color: #20252b;
        color: #6c737d;
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
