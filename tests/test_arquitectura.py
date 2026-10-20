"""Pruebas de arquitectura.

Garantizan dos cosas que sostienen el diseno de Serviscraft:

* el nucleo (``serviscraft.core``) es independiente de la interfaz grafica y de
  Qt, de modo que toda la logica se pueda probar sin pantalla;
* la version de la aplicacion se declara en un unico sitio y los paquetes no se
  desincronizan.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

PROGRAMA = """
import importlib
import pkgutil
import sys

import serviscraft.core as core

for modulo in pkgutil.iter_modules(core.__path__):
    importlib.import_module(f"serviscraft.core.{modulo.name}")

prohibidos = sorted(
    nombre
    for nombre in sys.modules
    if nombre.split(".")[0] == "PySide6" or nombre.startswith("serviscraft.ui")
)
for nombre in prohibidos:
    print(nombre)
sys.exit(1 if prohibidos else 0)
"""


def test_el_nucleo_no_importa_qt_ni_la_interfaz() -> None:
    """``serviscraft.core`` debe poder importarse sin Qt ni la capa de interfaz."""
    resultado = subprocess.run(
        [sys.executable, "-c", PROGRAMA],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode == 0, (
        "El nucleo no debe importar PySide6 ni serviscraft.ui; se encontraron:\n"
        f"{resultado.stdout}{resultado.stderr}"
    )


def test_la_version_es_coherente_en_todos_los_sitios() -> None:
    """Versión en el código, en pyproject.toml y en la especificación RPM."""
    from serviscraft import __version__
    from serviscraft.core import paths

    assert __version__ == paths.APP_VERSION

    pyproject = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__

    spec = (RAIZ / "packaging" / "rpm" / "serviscraft.spec").read_text(encoding="utf-8")
    coincidencia = re.search(r"^Version:\s*(\S+)", spec, re.MULTILINE)
    assert coincidencia is not None, "la especificacion RPM no declara Version"
    assert coincidencia.group(1) == __version__


def test_el_lanzador_de_usuario_funciona_desde_cualquier_carpeta(tmp_path: Path) -> None:
    """``make install-user`` debe dejar un lanzador que arranque fuera del proyecto.

    Regresion: el lanzador hacia ``-m serviscraft`` sin decir donde estaba el
    paquete, asi que solo funcionaba si lo ejecutabas desde la carpeta del
    proyecto (y desde el menu, que arranca en ``$HOME``, fallaba).
    """
    import os
    import shutil

    import pytest

    if shutil.which("make") is None:  # pragma: no cover - depende del sistema
        pytest.skip("hace falta 'make'")
    if not (RAIZ / ".venv" / "bin" / "python").is_file():  # pragma: no cover
        pytest.skip("hace falta el entorno virtual de desarrollo (.venv)")

    casa = tmp_path / "casa"
    casa.mkdir()
    entorno = {**os.environ, "HOME": str(casa)}

    instalacion = subprocess.run(
        ["make", "install-user"], cwd=RAIZ, env=entorno, capture_output=True, text=True
    )
    assert instalacion.returncode == 0, instalacion.stderr
    lanzador = casa / ".local" / "bin" / "serviscraft"
    assert lanzador.is_file()
    assert (casa / ".local/share/applications/serviscraft.desktop").is_file()

    # Se ejecuta desde otra carpeta: es lo que hace el menu del escritorio.
    prueba = subprocess.run(
        [str(lanzador), "--self-test"],
        cwd=tmp_path,
        env=entorno,
        capture_output=True,
        text=True,
    )
    assert prueba.returncode == 0, prueba.stdout + prueba.stderr
    assert "Todo listo." in prueba.stdout, prueba.stdout


def test_los_modulos_de_la_interfaz_se_importan() -> None:
    """Todos los modulos de ``serviscraft.ui`` son importables (sin abrir ventanas)."""
    import importlib
    import os
    import pkgutil

    import pytest

    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    import serviscraft.ui as ui

    for modulo in pkgutil.iter_modules(ui.__path__):
        importlib.import_module(f"serviscraft.ui.{modulo.name}")
