"""Pruebas de la gestion de ficheros, pluguins, mods y mundos."""

from __future__ import annotations

from pathlib import Path

import pytest

from serviscraft.core.errors import ValidationError
from serviscraft.core.models import ServerSpec
from serviscraft.core.server_files import FilesError, ServerFiles
from serviscraft.core.store import ServerStore


@pytest.fixture
def files(store: ServerStore, populated_server: ServerSpec) -> ServerFiles:
    return ServerFiles(store, populated_server.id)


@pytest.fixture
def files_con_dos_mundos(files: ServerFiles) -> ServerFiles:
    """Anade un segundo mundo activable (el fixture base solo tiene ``world``)."""
    otro = files.data_dir / "mundo-pruebas"
    otro.mkdir()
    (otro / "level.dat").write_bytes(b"otro mundo")
    return files


class TestListado:
    def test_lista_ficheros_y_carpetas(self, files: ServerFiles) -> None:
        entradas = {e.name: e for e in files.list_entries()}
        assert "world" in entradas
        assert entradas["world"].is_dir
        assert not entradas["server.properties"].is_dir

    def test_las_carpetas_van_primero(self, files: ServerFiles) -> None:
        entradas = files.list_entries()
        carpetas = [e for e in entradas if e.is_dir]
        assert entradas[: len(carpetas)] == carpetas

    def test_oculta_los_ficheros_ocultos(self, files: ServerFiles) -> None:
        (files.data_dir / ".oculto").write_text("x", encoding="utf-8")
        (files.data_dir / ".paper-remapped").mkdir()
        nombres = {e.name for e in files.list_entries()}
        assert ".oculto" not in nombres
        assert ".paper-remapped" not in nombres
        con_ocultos = {e.name for e in files.list_entries(include_hidden=True)}
        assert ".oculto" in con_ocultos and ".paper-remapped" in con_ocultos

    def test_lista_subcarpeta(self, files: ServerFiles) -> None:
        nombres = {e.name for e in files.list_entries("plugins")}
        assert nombres == {"ejemplo.jar"}

    def test_tamano_y_fecha(self, files: ServerFiles) -> None:
        entrada = next(e for e in files.list_entries() if e.name == "plugins")
        assert entrada.size_bytes > 0
        assert entrada.size_label
        assert entrada.modified > 0

    def test_ignora_lo_que_no_existe(self, files: ServerFiles) -> None:
        assert files.list_entries("no-existe") == []


class TestRutasSeguras:
    @pytest.mark.parametrize(
        "malo",
        ["..", "../vecino", "../../etc", "/etc/passwd", "plugins/../../../fuera"],
    )
    def test_no_se_puede_salir_de_la_carpeta(self, files: ServerFiles, malo: str) -> None:
        with pytest.raises(ValidationError):
            files.resolve(malo)

    def test_no_se_puede_borrar_fuera(
        self, files: ServerFiles, store: ServerStore, populated_server: ServerSpec
    ) -> None:
        with pytest.raises(ValidationError):
            files.delete_entry("../../meta.json")
        assert store.meta_file(populated_server.id).is_file()

    def test_no_se_puede_crear_carpeta_fuera(self, files: ServerFiles) -> None:
        with pytest.raises(ValidationError):
            files.create_folder("..", "mala")
        with pytest.raises(ValidationError):
            files.create_folder(".", "../../mala")

    def test_no_se_puede_importar_con_nombre_de_ruta(self, files: ServerFiles, tmp_path: Path) -> None:
        oculto = tmp_path / "sub" / ".." / "elegido.jar"
        oculto.parent.mkdir(parents=True, exist_ok=True)
        oculto.write_bytes(b"jar")
        (files.data_dir / "plugins").mkdir(exist_ok=True)
        # El nombre final siempre es un nombre simple, nunca una ruta.
        importados = files.import_files([oculto], "plugins")
        assert [p.name for p in importados] == ["elegido.jar"]
        assert importados[0].parent == (files.data_dir / "plugins").resolve()


class TestMundos:
    def test_detecta_los_mundos(self, files_con_dos_mundos: ServerFiles) -> None:
        nombres = [w.name for w in files_con_dos_mundos.list_worlds()]
        assert nombres == ["mundo-pruebas", "world"]

    def test_las_dimensiones_no_aparecen_por_separado(self, files: ServerFiles) -> None:
        # ``world_nether`` pertenece a ``world``: se agrupa y no se lista aparte.
        assert [w.name for w in files.list_worlds()] == ["world"]

    def test_mundo_activo(self, files: ServerFiles) -> None:
        assert files.active_world() == "world"
        assert [w.active for w in files.list_worlds()] == [True]

    def test_cambiar_mundo_activo(self, files_con_dos_mundos: ServerFiles) -> None:
        files_con_dos_mundos.set_active_world("mundo-pruebas")
        assert files_con_dos_mundos.active_world() == "mundo-pruebas"
        props = (files_con_dos_mundos.data_dir / "server.properties").read_text(encoding="utf-8")
        assert "level-name=mundo-pruebas" in props

    def test_no_activar_un_mundo_inexistente(self, files: ServerFiles) -> None:
        with pytest.raises(FilesError):
            files.set_active_world("no-existe")

    def test_renombrar_mundo(self, files: ServerFiles) -> None:
        files.rename_world("world_nether", "inframundo")
        assert (files.data_dir / "inframundo" / "level.dat").is_file()
        assert not (files.data_dir / "world_nether").exists()

    def test_renombrar_actualiza_el_mundo_activo(self, files_con_dos_mundos: ServerFiles) -> None:
        files_con_dos_mundos.set_active_world("mundo-pruebas")
        files_con_dos_mundos.rename_world("mundo-pruebas", "renombrado")
        assert files_con_dos_mundos.active_world() == "renombrado"
        assert (files_con_dos_mundos.data_dir / "renombrado" / "level.dat").is_file()

    def test_no_renombrar_sobre_otro_mundo(self, files: ServerFiles) -> None:
        with pytest.raises(FilesError):
            files.rename_world("world_nether", "world")

    @pytest.mark.parametrize("malo", ["../fuera", "/etc/passwd", ""])
    def test_renombrar_rechaza_nombres_malos(self, files: ServerFiles, malo: str) -> None:
        with pytest.raises((FilesError, ValidationError)):
            files.rename_world("world_nether", malo)

    def test_copiar_mundo(self, files: ServerFiles) -> None:
        nombre = files.copy_world("world_nether")
        copia = files.data_dir / nombre
        assert copia.is_dir()
        assert (copia / "level.dat").read_bytes() == b"inframundo"
        assert (files.data_dir / "world_nether").is_dir()

    def test_copiar_un_mundo_inexistente(self, files: ServerFiles) -> None:
        with pytest.raises(FilesError):
            files.copy_world("no-existe")

    def test_borrar_mundo(self, files: ServerFiles) -> None:
        liberado = files.delete_world("world_nether")
        assert liberado > 0
        assert not (files.data_dir / "world_nether").exists()

    def test_no_borrar_el_mundo_activo(self, files: ServerFiles) -> None:
        with pytest.raises(FilesError):
            files.delete_world("world")
        assert (files.data_dir / "world").is_dir()

    def test_borrar_un_mundo_borra_sus_dimensiones(self, files_con_dos_mundos: ServerFiles) -> None:
        files_con_dos_mundos.set_active_world("mundo-pruebas")
        files_con_dos_mundos.delete_world("world")
        assert not (files_con_dos_mundos.data_dir / "world").exists()
        assert not (files_con_dos_mundos.data_dir / "world_nether").exists()
        # El mundo activo y el resto del servidor siguen intactos.
        assert (files_con_dos_mundos.data_dir / "mundo-pruebas").is_dir()
        assert (files_con_dos_mundos.data_dir / "plugins" / "ejemplo.jar").is_file()

    def test_borrar_un_mundo_inexistente(self, files: ServerFiles) -> None:
        with pytest.raises(FilesError):
            files.delete_world("no-existe")


class TestImportarYDescargar:
    def test_importar_ficheros(self, files: ServerFiles, tmp_path: Path) -> None:
        origen = tmp_path / "mi-plugin.jar"
        origen.write_bytes(b"jar de prueba")
        importados = files.import_files([origen], "plugins")
        assert [p.name for p in importados] == ["mi-plugin.jar"]
        assert (files.data_dir / "plugins" / "mi-plugin.jar").read_bytes() == b"jar de prueba"

    def test_importar_reemplaza_si_ya_existe(self, files: ServerFiles, tmp_path: Path) -> None:
        origen = tmp_path / "ejemplo.jar"
        origen.write_bytes(b"version nueva")
        files.import_files([origen], "plugins")
        assert (files.data_dir / "plugins" / "ejemplo.jar").read_bytes() == b"version nueva"

    def test_importar_ignora_carpetas(self, files: ServerFiles, tmp_path: Path) -> None:
        carpeta = tmp_path / "carpeta"
        carpeta.mkdir()
        assert files.import_files([carpeta], "plugins") == []

    def test_importar_varios(self, files: ServerFiles, tmp_path: Path) -> None:
        origenes = []
        for nombre in ("uno.jar", "dos.jar", "tres.jar"):
            fichero = tmp_path / nombre
            fichero.write_bytes(b"x")
            origenes.append(fichero)
        importados = files.import_files(origenes, "plugins")
        assert sorted(p.name for p in importados) == ["dos.jar", "tres.jar", "uno.jar"]

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/plugin.jar",
            "http://localhost:8080/x.jar",
            "http://[::1]/x.jar",
            "file:///etc/passwd",
            "ftp://ejemplo.com/x.jar",
            "",
            "no-es-una-url",
            "http://usuario:clave@ejemplo.com/x.jar",
        ],
    )
    def test_urls_no_permitidas(self, files: ServerFiles, url: str) -> None:
        with pytest.raises(ValidationError):
            files.validate_download_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://cdn.modrinth.com/data/xyz/versions/1/plugin.jar",
            "http://descargas.ejemplo.com/mods/x.jar",
        ],
    )
    def test_urls_permitidas(self, files: ServerFiles, url: str) -> None:
        assert files.validate_download_url(url) == url

    def test_nombre_desde_la_url(self, files: ServerFiles) -> None:
        url = "https://ejemplo.com/ruta/plugin-1.2.jar?token=abc"
        assert files.filename_from_url(url) == "plugin-1.2.jar"

    def test_nombre_desde_la_url_con_override(self, files: ServerFiles) -> None:
        url = "https://ejemplo.com/x.jar"
        assert files.filename_from_url(url, "otro.jar") == "otro.jar"

    @pytest.mark.parametrize("malo", ["../fuera.jar", "/etc/passwd", "sub/x.jar"])
    def test_nombre_override_malo(self, files: ServerFiles, malo: str) -> None:
        with pytest.raises(ValidationError):
            files.filename_from_url("https://ejemplo.com/x.jar", malo)

    def test_rechaza_descargas_que_no_son_jar(self, files: ServerFiles) -> None:
        with pytest.raises(ValidationError):
            files.filename_from_url("https://ejemplo.com/pagina.html")


class TestBorradoDeEntradas:
    def test_borra_un_fichero(self, files: ServerFiles) -> None:
        files.delete_entry("plugins/ejemplo.jar")
        assert not (files.data_dir / "plugins" / "ejemplo.jar").exists()

    def test_borra_una_carpeta_entera(self, files: ServerFiles) -> None:
        files.delete_entry("world")
        assert not (files.data_dir / "world").exists()

    def test_no_borra_la_carpeta_del_servidor(self, files: ServerFiles) -> None:
        with pytest.raises(ValidationError):
            files.delete_entry("")

    def test_borrar_algo_inexistente(self, files: ServerFiles) -> None:
        with pytest.raises(FilesError):
            files.delete_entry("no-existe.jar")


class TestTotales:
    def test_tamano_total(self, files: ServerFiles) -> None:
        assert files.total_size() > 0

    def test_crear_y_abrir_carpetas(self, files: ServerFiles) -> None:
        creada = files.create_folder("", "mi-carpeta")
        assert creada.is_dir()
        with pytest.raises(FilesError):
            files.create_folder("", "mi-carpeta")
        assert files.plugins_dir(create=True).is_dir()
        assert files.mods_dir(create=True).is_dir()
