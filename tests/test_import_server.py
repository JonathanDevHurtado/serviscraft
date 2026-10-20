"""Pruebas de la importacion de servidores existentes (carpeta o .zip)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from serviscraft.core.errors import ValidationError
from serviscraft.core.import_server import (
    ImportCancelled,
    ImportSourceError,
    copy_source,
    inspect_source,
)
from serviscraft.core.manager import ServerManager
from serviscraft.core.models import ServerType
from serviscraft.core.store import ServerStore

from .conftest import make_spec


@pytest.fixture
def manager(store: ServerStore, config) -> ServerManager:
    """Gestor real con un motor que no se llega a usar (la importacion no lo toca)."""
    return ServerManager(store=store, config=config)


def _crear_servidor_aternos(base: Path) -> Path:
    """Un servidor con la pinta de los que exporta Aternos."""
    root = base / "aternos-export"
    (root / "world" / "region").mkdir(parents=True)
    (root / "world_nether").mkdir(parents=True)
    (root / "plugins").mkdir(parents=True)
    (root / "logs").mkdir(parents=True)
    (root / "libraries").mkdir(parents=True)
    (root / "world" / "level.dat").write_bytes(b"nivel" * 100)
    (root / "world" / "region" / "r.0.0.mca").write_bytes(b"x" * 4096)
    (root / "world_nether" / "level.dat").write_bytes(b"inframundo")
    (root / "plugins" / "EssentialsX.jar").write_bytes(b"jar")
    (root / "plugins" / "config.yml").write_text("ajustes: si\n", encoding="utf-8")
    (root / "libraries" / "grande.jar").write_bytes(b"x" * 1024)
    (root / "logs" / "latest.log").write_text(
        "[12:00:00] [Server thread/INFO]: Starting minecraft server version 1.20.4\n"
        "[12:00:01] [Server thread/INFO]: This server is hosted by Aternos\n",
        encoding="utf-8",
    )
    (root / "version_history.json").write_text(
        json.dumps({"currentVersion": "git-Paper-196 (MC: 1.20.4)"}), encoding="utf-8"
    )
    (root / "server.properties").write_text(
        "motd=El reino de Ana\nlevel-name=world\nserver-port=25565\nwhite-list=true\n",
        encoding="utf-8",
    )
    (root / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (root / "server-icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return root


class TestReconocer:
    def test_reconoce_un_servidor_exportado_de_aternos(self, tmp_path: Path) -> None:
        info = inspect_source(_crear_servidor_aternos(tmp_path))
        assert info.origin == "Aternos"
        assert info.server_type is ServerType.PAPER
        assert info.version == "1.20.4"
        assert info.version_known
        assert info.port == 25565
        assert info.world == "world"
        assert "world" in info.worlds and "world_nether" in info.worlds
        assert info.plugins == 1
        assert info.mods == 0
        assert info.has_icon
        assert info.has_eula
        assert "Aternos" in info.origin_label
        # Las librerias y los registros no cuentan para el tamano copiado.
        assert info.total_bytes < 20_000

    def test_reconoce_la_carpeta_de_dentro_de_otra(
        self, tmp_path: Path
    ) -> None:
        """Al descomprimir, el servidor suele quedar dentro de una subcarpeta."""
        root = _crear_servidor_aternos(tmp_path)
        padre = tmp_path / "descargas"
        padre.mkdir()
        destino = padre / "Mi servidor"
        root.rename(destino)

        info = inspect_source(padre)
        assert info.version == "1.20.4"
        assert info.worlds
        assert info.name == "Mi servidor"

    def test_una_carpeta_que_no_es_un_servidor(self, tmp_path: Path) -> None:
        (tmp_path / "vacaciones").mkdir()
        (tmp_path / "vacaciones" / "foto.jpg").write_bytes(b"jpg")
        with pytest.raises(ImportSourceError):
            inspect_source(tmp_path / "vacaciones")

    def test_un_archivo_que_no_es_zip(self, tmp_path: Path) -> None:
        archivo = tmp_path / "notas.txt"
        archivo.write_text("hola", encoding="utf-8")
        with pytest.raises(ImportSourceError):
            inspect_source(archivo)

    def test_dos_servidores_en_la_misma_carpeta(self, tmp_path: Path) -> None:
        uno = _crear_servidor_aternos(tmp_path)
        dos = tmp_path / "otro"
        dos.mkdir()
        (dos / "server.properties").write_text("server-port=25566\n", encoding="utf-8")
        with pytest.raises(ImportSourceError):
            inspect_source(tmp_path)
        assert uno.is_dir()


class TestZip:
    def _zip(self, base: Path) -> Path:
        root = _crear_servidor_aternos(base)
        archivo = base / "mi-servidor.zip"
        with zipfile.ZipFile(archivo, "w") as zf:
            for path in root.rglob("*"):
                if path.is_file():
                    zf.write(path, ("Mi servidor/" + path.relative_to(root).as_posix()))
            # Ruta maliciosa: no puede salir de la carpeta de destino.
            zf.writestr("../../fuera.txt", "malo")
            # Enlace simbolico: tampoco se copia.
            info = zipfile.ZipInfo("Mi servidor/enlace")
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, "/etc/passwd")
        return archivo

    def test_reconoce_el_zip_y_copia_sin_salirse(self, tmp_path: Path) -> None:
        archivo = self._zip(tmp_path)
        info = inspect_source(archivo)
        assert info.is_archive
        assert info.prefix == "Mi servidor"
        assert info.server_type is ServerType.PAPER
        assert info.origin == "Aternos"
        assert info.plugins == 1
        destino = tmp_path / "destino"
        copiados = copy_source(info, destino)
        assert copiados > 0
        assert (destino / "world" / "level.dat").is_file()
        assert (destino / "plugins" / "EssentialsX.jar").is_file()
        assert not (destino / "logs").exists()
        assert not (tmp_path / "fuera.txt").exists()
        assert not (destino / "enlace").exists()

    def test_cancelar_la_copia(self, tmp_path: Path) -> None:
        info = inspect_source(self._zip(tmp_path))
        with pytest.raises(ImportCancelled):
            copy_source(info, tmp_path / "destino", should_cancel=lambda: True)


class TestImportarEnElGestor:
    def test_importa_y_ajusta_la_configuracion(
        self, manager: ServerManager, store: ServerStore, tmp_path: Path
    ) -> None:
        origen = _crear_servidor_aternos(tmp_path)
        spec, info = manager.import_server(origen, name="Reino importado", memory_mb=2048)

        assert spec.name == "Reino importado"
        assert spec.version == "1.20.4"
        assert spec.type is ServerType.PAPER
        assert info.origin == "Aternos"
        assert store.load(spec.id).port == spec.port

        data = store.data_dir(spec.id)
        assert (data / "world" / "level.dat").is_file()
        assert (data / "plugins" / "EssentialsX.jar").is_file()
        assert not (data / "logs").exists()
        assert not (data / "libraries").exists()

        propiedades = (data / "server.properties").read_text(encoding="utf-8")
        assert "server-port=25565" in propiedades
        assert "rcon.port=25575" in propiedades
        assert f"rcon.password={spec.rcon_password}" in propiedades
        # La configuracion del servidor original se conserva.
        assert "white-list=true" in propiedades
        assert "level-name=world" in propiedades
        assert (data / "eula.txt").read_text(encoding="utf-8").startswith("eula=true")
        # El icono importado queda solo para su dueno.
        assert (data / "server-icon.png").stat().st_mode & 0o777 == 0o600

    def test_conserva_el_puerto_si_esta_libre(
        self, manager: ServerManager, store: ServerStore, tmp_path: Path
    ) -> None:
        origen = _crear_servidor_aternos(tmp_path)
        spec, _info = manager.import_server(origen)
        assert spec.port == 25565

        # Un segundo servidor igual ya no puede usar el mismo puerto.
        origen2 = tmp_path / "otro-export"
        origen2.mkdir()
        (origen2 / "server.properties").write_text(
            "server-port=25565\nlevel-name=world\n", encoding="utf-8"
        )
        (origen2 / "world").mkdir()
        (origen2 / "world" / "level.dat").write_bytes(b"nivel")
        spec2, _info2 = manager.import_server(origen2, name="Segundo")
        assert spec2.port != 25565

    def test_si_se_cancela_no_queda_nada(
        self, manager: ServerManager, store: ServerStore, tmp_path: Path
    ) -> None:
        origen = _crear_servidor_aternos(tmp_path)
        with pytest.raises(ImportCancelled):
            manager.import_server(origen, should_cancel=lambda: True)
        assert store.list_ids() == []

    def test_nombre_invalido_no_deja_restos(
        self, manager: ServerManager, store: ServerStore, tmp_path: Path
    ) -> None:
        origen = _crear_servidor_aternos(tmp_path)
        with pytest.raises(ValidationError):
            manager.import_server(origen, name="a/b")
        assert store.list_ids() == []

    def test_importar_no_choca_con_otro_servidor(
        self, manager: ServerManager, store: ServerStore, tmp_path: Path
    ) -> None:
        existente = make_spec()
        store.prepare_dirs(existente.id)
        store.save(existente)
        origen = _crear_servidor_aternos(tmp_path)
        spec, _info = manager.import_server(origen)
        assert spec.id != existente.id
        assert {s.id for s in store.load_all()} == {existente.id, spec.id}
