"""Pruebas de validacion de entradas y de las utilidades de rutas seguras."""

from __future__ import annotations

from pathlib import Path

import pytest

from serviscraft.core.errors import ValidationError
from serviscraft.core.validation import (
    ensure_within,
    format_memory,
    slugify,
    validate_basename,
    validate_image,
    validate_java_tag,
    validate_memory_mb,
    validate_minecraft_version,
    validate_name,
    validate_password,
    validate_port,
    validate_relative_subpath,
    validate_server_id,
)


class TestNombres:
    @pytest.mark.parametrize(
        "entrada, esperado",
        [
            ("Mi servidor", "Mi servidor"),
            ("  espacios   de   mas  ", "espacios de mas"),
            ("Paper-Creativo_2", "Paper-Creativo_2"),
            ("Servidor.1", "Servidor.1"),
        ],
    )
    def test_normaliza(self, entrada: str, esperado: str) -> None:
        assert validate_name(entrada) == esperado

    @pytest.mark.parametrize("entrada", ["", "   ", None])
    def test_rechaza_vacio(self, entrada) -> None:
        with pytest.raises(ValidationError):
            validate_name(entrada)

    @pytest.mark.parametrize("entrada", ["a" * 33, "servidor/../etc", "malo;rm -rf /", "salto\x00nulo"])
    def test_rechaza_peligrosos(self, entrada: str) -> None:
        with pytest.raises(ValidationError):
            validate_name(entrada)

    def test_los_saltos_de_linea_se_convierten_en_espacios(self) -> None:
        assert validate_name("dos\nlineas") == "dos lineas"

    @pytest.mark.parametrize(
        "nombre, esperado",
        [
            ("Mi Servidor de Prueba", "mi-servidor-de-prueba"),
            ("Acentos: ñandú", "acentos-nandu"),
            ("   ", "server"),
            ("---", "server"),
            ("SERVIDOR", "servidor"),
        ],
    )
    def test_slugify(self, nombre: str, esperado: str) -> None:
        assert slugify(nombre) == esperado

    def test_slugify_recorta(self) -> None:
        assert len(slugify("a" * 100)) <= 24

    @pytest.mark.parametrize("malo", ["", "MAYUS", "-empieza", "../fuera", "a" * 42, "espacio aqui"])
    def test_validate_server_id_rechaza(self, malo: str) -> None:
        with pytest.raises(ValidationError):
            validate_server_id(malo)

    def test_validate_server_id_acepta(self) -> None:
        assert validate_server_id("paper-creativo-0d0a8a") == "paper-creativo-0d0a8a"


class TestPuertos:
    def test_puerto_valido(self) -> None:
        assert validate_port(25565) == 25565
        assert validate_port(" 25600 ") == 25600

    @pytest.mark.parametrize("malo", [80, 1023, 65536, 0, -1, "abc", None, "25565; rm -rf /"])
    def test_puerto_invalido(self, malo) -> None:
        with pytest.raises(ValidationError):
            validate_port(malo)

    def test_puerto_reservado(self) -> None:
        with pytest.raises(ValidationError):
            validate_port(25565, reserved={25565, 25566})


class TestMemoria:
    def test_rango(self) -> None:
        assert validate_memory_mb(1024) == 1024
        with pytest.raises(ValidationError):
            validate_memory_mb(100)
        with pytest.raises(ValidationError):
            validate_memory_mb(999999)
        with pytest.raises(ValidationError):
            validate_memory_mb("dos gigas")

    @pytest.mark.parametrize(
        "mb, esperado",
        [(512, "512M"), (1024, "1G"), (2048, "2G"), (1536, "1536M")],
    )
    def test_formato_para_la_imagen(self, mb: int, esperado: str) -> None:
        assert format_memory(mb) == esperado


class TestVersionesEImagenes:
    @pytest.mark.parametrize("version", ["1.21.4", "latest", "1.20.1", "1.21.4-pre1", "24w45a"])
    def test_version_valida(self, version: str) -> None:
        assert validate_minecraft_version(version) == version

    @pytest.mark.parametrize("version", ["", " 1.21 ; rm", "$(whoami)", "a" * 40, "1.21/../etc"])
    def test_version_invalida(self, version: str) -> None:
        with pytest.raises(ValidationError):
            validate_minecraft_version(version)

    def test_imagen(self) -> None:
        assert validate_image("docker.io/itzg/minecraft-server") == "docker.io/itzg/minecraft-server"
        with pytest.raises(ValidationError):
            validate_image("imagen con espacios")
        with pytest.raises(ValidationError):
            validate_image("")

    def test_java_tag(self) -> None:
        assert validate_java_tag("java21") == "java21"
        with pytest.raises(ValidationError):
            validate_java_tag("java 21")


class TestContrasena:
    def test_valida(self) -> None:
        assert validate_password("contrasena-larga") == "contrasena-larga"

    @pytest.mark.parametrize("mala", ["corta", "con espacios aqui", "", "a" * 200])
    def test_invalida(self, mala: str) -> None:
        with pytest.raises(ValidationError):
            validate_password(mala)


class TestNombresDeFichero:
    def test_acepta(self) -> None:
        assert validate_basename("plugin.jar") == "plugin.jar"

    @pytest.mark.parametrize(
        "malo",
        ["../fuera.jar", "sub/dir.jar", "..", "", "a\\b.jar", "con\ttab"],
    )
    def test_rechaza_rutas(self, malo: str) -> None:
        with pytest.raises(ValidationError):
            validate_basename(malo)

    def test_sufijos(self) -> None:
        assert validate_basename("copia.tar.gz", allowed_suffixes=(".tar.gz", ".tgz")) == "copia.tar.gz"
        with pytest.raises(ValidationError):
            validate_basename("copia.zip", allowed_suffixes=(".tar.gz", ".tgz"))


class TestRutasSeguras:
    def test_ensure_within_acepta_dentro(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        (root / "sub").mkdir(parents=True)
        assert ensure_within(root / "sub", root) == (root / "sub").resolve()

    @pytest.mark.parametrize("salida", ["../fuera", "sub/../../fuera", "/etc/passwd"])
    def test_ensure_within_rechaza_fuera(self, tmp_path: Path, salida: str) -> None:
        root = tmp_path / "root"
        root.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValidationError):
            ensure_within(salida, root)

    def test_ensure_within_rechaza_enlace_simbolico(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "secreto"
        outside.mkdir()
        (root / "enlace").symlink_to(outside)
        with pytest.raises(ValidationError):
            ensure_within("enlace", root)

    def test_relative_subpath(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        (root / "plugins").mkdir(parents=True)
        assert validate_relative_subpath("plugins", root) == (root / "plugins").resolve()

    @pytest.mark.parametrize("malo", ["..", "../etc", "plugins/../../etc", "/absoluto", "~/fuera", "", "."])
    def test_relative_subpath_rechaza(self, tmp_path: Path, malo: str) -> None:
        root = tmp_path / "root"
        root.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValidationError):
            validate_relative_subpath(malo, root)
