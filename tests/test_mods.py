"""Pruebas del inventario de mods, los registros y los mods que faltan."""

from __future__ import annotations

import json

import pytest

from serviscraft.core import logs, mods
from serviscraft.core.missing_mods import MissingMod, parse_missing_mods
from serviscraft.core.models import ServerType
from serviscraft.core.store import ServerStore


@pytest.fixture
def inventario(tmp_path, monkeypatch) -> mods.ModsInventory:
    store = ServerStore(tmp_path / "datos")
    store.prepare_dirs("srv-ab12cd")
    return mods.ModsInventory(store, "srv-ab12cd", folder="mods", modpack=True)


class TestInventarioDeMods:
    def test_lista_activos_y_desactivados(self, inventario) -> None:
        carpeta = inventario.folder_path
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "create-1.0.jar").write_bytes(b"PK\x03\x04datos")
        (carpeta / "sodium.jar.desactivado").write_bytes(b"PK\x03\x04datos")
        (carpeta / "notas.txt").write_text("no es un mod")

        entradas = inventario.list_mods()

        assert [entrada.filename for entrada in entradas] == [
            "create-1.0.jar",
            "sodium.jar.desactivado",
        ]
        activo, desactivado = entradas
        assert activo.enabled and not desactivado.enabled
        assert activo.base_name == "create-1.0"
        assert desactivado.base_name == "sodium"
        # En un servidor con modpack, lo que no esta en el manifiesto es del pack.
        assert activo.custom is False
        assert activo.origin_label == "del modpack"

    def test_desactivar_y_volver_a_activar_no_borra(self, inventario) -> None:
        carpeta = inventario.folder_path
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "create.jar").write_bytes(b"PK\x03\x04")

        inventario.set_enabled("create.jar", False)
        assert (carpeta / "create.jar.desactivado").is_file()
        assert not (carpeta / "create.jar").exists()

        inventario.set_enabled("create.jar.desactivado", True)
        assert (carpeta / "create.jar").is_file()
        assert not (carpeta / "create.jar.desactivado").exists()

    def test_no_permite_salir_de_la_carpeta(self, inventario) -> None:
        from serviscraft.core.errors import ValidationError

        with pytest.raises(ValidationError):
            inventario.set_enabled("../server.properties", False)

    def test_anotar_y_olvidar_los_personalizados(self, inventario) -> None:
        inventario.mark_custom("mi-mod.jar")
        assert json.loads(inventario.manifest_path.read_text()) == {"personalizados": ["mi-mod.jar"]}

        inventario.forget_custom("mi-mod.jar")
        assert json.loads(inventario.manifest_path.read_text()) == {"personalizados": []}

    def test_un_servidor_sin_modpack_tiene_todo_como_propio(self, tmp_path) -> None:
        store = ServerStore(tmp_path / "datos")
        store.prepare_dirs("fabric-ab12cd")
        inventario = mods.ModsInventory(store, "fabric-ab12cd", folder="mods", modpack=False)
        inventario.folder_path.mkdir(parents=True, exist_ok=True)
        (inventario.folder_path / "lithium.jar").write_bytes(b"PK\x03\x04")

        entrada = inventario.list_mods()[0]
        assert entrada.custom is True
        assert entrada.origin_label == "personalizado"

    def test_añadir_un_fichero_local_lo_copia_y_lo_anota(self, inventario, tmp_path) -> None:
        origen = tmp_path / "mi-mod.jar"
        origen.write_bytes(b"PK\x03\x04contenido")

        destino = inventario.add_file(origen)

        assert destino.is_file()
        assert destino.read_bytes() == b"PK\x03\x04contenido"
        assert [entrada.custom for entrada in inventario.list_mods()] == [True]

    def test_no_se_pisa_un_mod_existente(self, inventario, tmp_path) -> None:
        origen = tmp_path / "create.jar"
        origen.write_bytes(b"PK\x03\x04")
        inventario.add_file(origen)

        with pytest.raises(mods.ModsError):
            inventario.add_file(origen)

    def test_solo_se_admiten_ficheros_de_contenido(self, inventario, tmp_path) -> None:
        from serviscraft.core.errors import ValidationError

        origen = tmp_path / "guion.sh"
        origen.write_text("#!/bin/sh")

        with pytest.raises(ValidationError):
            inventario.add_file(origen)

    def test_eliminar(self, inventario) -> None:
        carpeta = inventario.folder_path
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "viejo.jar").write_bytes(b"PK\x03\x04")
        inventario.mark_custom("viejo.jar")

        inventario.delete("viejo.jar")

        assert not (carpeta / "viejo.jar").exists()
        assert json.loads(inventario.manifest_path.read_text()) == {"personalizados": []}

    def test_la_carpeta_depende_del_tipo_de_servidor(self) -> None:
        from serviscraft.core.models import ServerSpec

        def spec(tipo: ServerType):
            return ServerSpec(
                id="srv-ab12cd",
                name="Servidor",
                type=tipo,
                version="1.21.4",
                memory_mb=2048,
                port=25565,
                rcon_port=25575,
                rcon_password="secreto",
                image="docker.io/itzg/minecraft-server",
            )

        assert mods.folder_for(spec(ServerType.PAPER)) == "plugins"
        assert mods.folder_for(spec(ServerType.FABRIC)) == "mods"
        assert mods.folder_for(spec(ServerType.MODRINTH)) == "mods"

    def test_find_installed_encuentra_por_nombre(self) -> None:
        ficheros = ["journeymap-1.21.1-6.0.0.jar", "fabric-api-0.100.jar"]

        assert mods.find_installed("JourneyMap", ficheros) == "journeymap-1.21.1-6.0.0.jar"
        assert mods.find_installed("fabric api", ficheros) == "fabric-api-0.100.jar"
        assert mods.find_installed("create", ficheros) is None
        # Nombres demasiado cortos no valen (evitan falsos positivos).
        assert mods.find_installed("fa", ficheros) is None


class TestRegistros:
    def _files(self, tmp_path):
        from serviscraft.core.server_files import ServerFiles

        store = ServerStore(tmp_path / "datos")
        store.prepare_dirs("srv-ab12cd")
        files = ServerFiles(store, "srv-ab12cd")
        (files.data_dir / "logs").mkdir(parents=True, exist_ok=True)
        (files.data_dir / "crash-reports").mkdir(parents=True, exist_ok=True)
        return files

    def test_lista_los_registros_mas_recientes_primero(self, tmp_path) -> None:
        files = self._files(tmp_path)
        (files.data_dir / "logs" / "latest.log").write_text("hola\n")
        (files.data_dir / "logs" / "2025-01-01-1.log.gz").write_bytes(b"\x1f\x8b")
        (files.data_dir / "crash-reports" / "crash-2025.txt").write_text("fallo\n")

        encontrados = logs.list_logs(files)

        nombres = {log.name for log in encontrados}
        assert nombres == {"latest.log", "2025-01-01-1.log.gz", "crash-2025.txt"}

    def test_lee_el_final_del_fichero(self, tmp_path) -> None:
        files = self._files(tmp_path)
        ruta = files.data_dir / "logs" / "latest.log"
        ruta.write_text("linea vieja\nlinea nueva\n")

        assert "linea nueva" in logs.read_log(files, "logs/latest.log")

    def test_avisa_si_el_fichero_es_enorme(self, tmp_path) -> None:
        files = self._files(tmp_path)
        ruta = files.data_dir / "logs" / "latest.log"
        ruta.write_text(("x" * 99 + "\n") * 50)

        texto = logs.read_log(files, "logs/latest.log", max_bytes=200)

        assert "se muestran los ultimos" in texto
        assert len(texto) < 2000

    def test_no_deja_leer_fuera_del_servidor(self, tmp_path) -> None:
        files = self._files(tmp_path)
        with pytest.raises(logs.LogsError):
            logs.read_log(files, "../../etc/passwd")

    def test_un_registro_que_no_existe(self, tmp_path) -> None:
        files = self._files(tmp_path)
        with pytest.raises(logs.LogsError):
            logs.read_log(files, "logs/no-existe.log")


class TestModsFaltantes:
    def test_bloque_de_dependencias_de_fabric(self) -> None:
        texto = (
            "[12:00:00] [main/ERROR]: Missing or unsupported mandatory dependencies:\n"
            "\tMod ID: 'fabric-api', Requested by: 'cobblemon', Expected range: '>=0.92.2', "
            "Actual version: '[MISSING]'\n"
            "\tMod ID: 'architectury', Requested by: 'cobblemon', Actual version: '[MISSING]'\n"
            "[12:00:01] [main/INFO]: Stopping the server\n"
        )

        faltan = parse_missing_mods(texto)

        assert [mod.name for mod in faltan] == ["fabric-api", "architectury"]
        assert faltan[0].url == ""
        assert "modrinth.com/mods?q=fabric-api" in faltan[0].link

    def test_descarga_fallida_con_enlace_de_modrinth(self) -> None:
        texto = (
            "[init] Failed to download "
            "https://cdn.modrinth.com/data/AANobbMI/versions/abc/sodium-0.6.jar (404)\n"
            "[init] ERROR: no se pudo descargar https://modrinth.com/mod/sodium\n"
        )

        faltan = parse_missing_mods(texto)
        por_nombre = {mod.name.lower(): mod for mod in faltan}

        assert "aanobbmi" in por_nombre
        assert por_nombre["aanobbmi"].url == "https://modrinth.com/project/AANobbMI"
        assert por_nombre["sodium"].url == "https://modrinth.com/mod/sodium"

    def test_frase_de_mod_faltante(self) -> None:
        texto = "[init] Failed to download mod create-1.20.1.jar\n"

        faltan = parse_missing_mods(texto)

        assert [mod.name for mod in faltan] == ["create-1.20.1"]

    def test_el_mismo_mod_no_se_duplica(self) -> None:
        texto = (
            "Failed to download https://modrinth.com/mod/sodium\n"
            "ERROR: unable to download sodium\n"
        )

        faltan = parse_missing_mods(texto)

        assert len(faltan) == 1
        assert faltan[0].url == "https://modrinth.com/mod/sodium"

    def test_un_registro_normal_no_enciende_avisos(self) -> None:
        texto = (
            "[12:00:00] [Server thread/INFO]: Starting minecraft server version 1.21.1\n"
            "[12:00:01] [Server thread/INFO]: Preparing level \"world\"\n"
            "[12:00:02] [Server thread/INFO]: Done (3.2s)! For help, type \"help\"\n"
        )

        assert parse_missing_mods(texto) == []

    def test_el_enlace_de_busqueda_escapa_el_nombre(self) -> None:
        mod = MissingMod(name="journey map")

        assert mod.search_url == "https://modrinth.com/mods?q=journey+map"
        assert mod.link == mod.search_url
        assert MissingMod(name="x", url="https://modrinth.com/mod/x").link == "https://modrinth.com/mod/x"
