"""Punto de entrada de la aplicacion Serviscraft."""

from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .core import paths
from .core.appconfig import AppConfig
from .core.logging_setup import get_logger, install_excepthook, setup_logging
from .core.manager import ServerManager
from .ui.dialogs import show_error
from .ui.main_window import MainWindow
from .ui.theme import apply_theme

logger = get_logger("app")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serviscraft",
        description="Gestor grafico de servidores de Minecraft sobre Podman rootless.",
    )
    parser.add_argument("--version", action="version", version=f"Serviscraft {__version__}")
    parser.add_argument("--debug", action="store_true", help="activa el registro detallado")
    parser.add_argument(
        "--data-dir",
        metavar="RUTA",
        help="usa otra carpeta de datos (equivale a SERVISCRAFT_HOME)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="comprueba dependencias y termina (util para diagnosticos)",
    )
    return parser


def run_self_test() -> int:
    """Comprueba que el entorno tiene todo lo necesario."""
    from .core.podman import PodmanClient

    print(f"Serviscraft {__version__}")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"Datos: {paths.data_root()}")
    print(f"Configuracion: {paths.config_file()}")

    try:
        import PySide6

        print(f"PySide6: {PySide6.__version__}")
    except ImportError:
        print("PySide6: NO INSTALADO")
        return 2

    client = PodmanClient()
    if not client.is_installed():
        print("Podman: NO ENCONTRADO (instala podman con 'sudo dnf install podman')")
        return 3
    try:
        version = client.ensure_available()
        rootless = client.is_rootless()
    except Exception as exc:  # noqa: BLE001
        print(f"Podman: error ({exc})")
        return 3
    print(f"Podman: {version} (rootless={rootless})")
    if not rootless:
        print("AVISO: Podman no esta en modo rootless; Serviscraft no lo usara con sudo.")
        return 4
    print("Todo listo.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.data_dir:
        os.environ["SERVISCRAFT_HOME"] = args.data_dir

    if args.self_test:
        return run_self_test()

    config = AppConfig.load().validated()
    setup_logging(debug=args.debug or config.debug_logging)
    paths.ensure_base_dirs()
    logger.info("Iniciando Serviscraft %s", __version__)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Serviscraft")
    app.setApplicationDisplayName("Serviscraft")
    app.setOrganizationName("Serviscraft")
    app.setApplicationVersion(__version__)
    # Necesario para que Wayland asocie la ventana con su icono y su .desktop.
    app.setDesktopFileName("serviscraft")
    icon = QIcon()
    for candidate in (paths.bundled_resource("icons", "serviscraft.svg"),):
        if candidate.is_file():
            icon = QIcon(str(candidate))
            break
    if not icon.isNull():
        app.setWindowIcon(icon)
    else:  # pragma: no cover - sin recursos empaquetados
        app.setWindowIcon(QIcon.fromTheme("minecraft", QIcon.fromTheme("applications-games")))

    apply_theme(app)

    manager = ServerManager(config=config)
    window = MainWindow(manager, config)

    def on_unexpected_error(summary: str, details: str) -> None:
        show_error(window, "Ha ocurrido un error inesperado", summary, details)

    install_excepthook(on_unexpected_error)

    window.show()
    QTimer.singleShot(0, window.start)
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
