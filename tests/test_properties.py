"""Pruebas del editor de ``server.properties``."""

from __future__ import annotations

from pathlib import Path

from serviscraft.core.properties import (
    KNOWN_PROPERTIES,
    ServerProperties,
    build_default_properties,
)

EJEMPLO = """#Minecraft server properties
#Thu Oct 18 12:00:00 UTC 2026
motd=Un servidor
level-name=world
max-players=20
difficulty=easy
enable-rcon=true
rcon.password=secreto
server-port=25565
clave-desconocida=42
"""


def test_parsea_y_conserva_comentarios(tmp_path: Path) -> None:
    props = ServerProperties.from_text(tmp_path / "server.properties", EJEMPLO)
    texto = props.to_text()
    assert texto.startswith("#Minecraft server properties\n")
    assert "#Thu Oct 18 12:00:00 UTC 2026" in texto
    assert "clave-desconocida=42" in texto


def test_lectura_de_valores(tmp_path: Path) -> None:
    props = ServerProperties.from_text(tmp_path / "server.properties", EJEMPLO)
    assert props.get("motd") == "Un servidor"
    assert props.get("no-existe", "defecto") == "defecto"
    assert props.get_int("max-players") == 20
    assert props.get_int("no-existe", 7) == 7
    assert props.get_bool("enable-rcon") is True
    assert props.get_bool("no-existe", True) is True
    assert props.as_dict()["difficulty"] == "easy"


def test_set_mantiene_la_posicion(tmp_path: Path) -> None:
    props = ServerProperties.from_text(tmp_path / "server.properties", EJEMPLO)
    props.set("motd", "Otro mensaje")
    lineas = props.to_text().splitlines()
    assert lineas[2] == "motd=Otro mensaje"
    assert lineas[3] == "level-name=world"


def test_set_anade_al_final(tmp_path: Path) -> None:
    props = ServerProperties.from_text(tmp_path / "server.properties", EJEMPLO)
    props.set("nueva-clave", "valor")
    assert props.to_text().rstrip().endswith("nueva-clave=valor")


def test_set_many_y_remove(tmp_path: Path) -> None:
    props = ServerProperties.from_text(tmp_path / "server.properties", EJEMPLO)
    props.set_many({"a": "1", "b": "2"})
    assert props.get("a") == "1" and props.get("b") == "2"
    props.remove("a")
    assert props.get("a") == ""


def test_lineas_invalidas_se_conservan(tmp_path: Path) -> None:
    props = ServerProperties.from_text(tmp_path / "server.properties", "esto no es una propiedad\nmotd=x\n")
    assert "esto no es una propiedad" in props.to_text()
    assert props.get("motd") == "x"


def test_guardar_y_leer(tmp_path: Path) -> None:
    destino = tmp_path / "data" / "server.properties"
    props = ServerProperties.from_text(destino, EJEMPLO)
    props.set("motd", "Guardado")
    props.save()
    assert destino.is_file()
    releido = ServerProperties.load(destino)
    assert releido.get("motd") == "Guardado"
    assert not destino.with_suffix(".properties.tmp").exists()


def test_guardar_es_estable(tmp_path: Path) -> None:
    destino = tmp_path / "server.properties"
    props = ServerProperties.from_text(destino, EJEMPLO)
    props.save()
    primero = destino.read_text(encoding="utf-8")
    props.save()
    assert destino.read_text(encoding="utf-8") == primero


def test_fichero_inexistente(tmp_path: Path) -> None:
    props = ServerProperties.load(tmp_path / "nada.properties")
    assert props.entries == []


def test_espacios_alrededor_del_igual(tmp_path: Path) -> None:
    props = ServerProperties.from_text(tmp_path / "server.properties", "motd = con espacios \n")
    assert props.get("motd") == "con espacios"
    assert props.to_text().splitlines()[0] == "motd=con espacios"


def test_valores_con_igual(tmp_path: Path) -> None:
    props = ServerProperties.from_text(tmp_path / "server.properties", "resource-pack=http://a/b?a=1&c=2\n")
    assert props.get("resource-pack") == "http://a/b?a=1&c=2"


def test_propiedades_por_defecto(tmp_path: Path) -> None:
    props = build_default_properties("Mi MOTD", level_name="mundo")
    assert props.get("motd") == "Mi MOTD"
    assert props.get("level-name") == "mundo"
    # Las propiedades gestionadas no se escriben nunca.
    for clave, meta in KNOWN_PROPERTIES.items():
        if meta.managed:
            assert props.get(clave) == ""
    # Y los valores por defecto conocidos si estan.
    assert props.get("max-players") == "20"


def test_gestionadas_incluyen_puerto_y_rcon() -> None:
    gestionadas = {k for k, m in KNOWN_PROPERTIES.items() if m.managed}
    assert {"server-port", "rcon.password", "rcon.port", "enable-rcon", "server-ip"} <= gestionadas


def test_catalogo_coherente() -> None:
    for clave, meta in KNOWN_PROPERTIES.items():
        assert meta.key == clave
        assert meta.label
        assert meta.kind in {"str", "int", "bool", "enum"}
        if meta.kind == "enum":
            assert meta.choices and meta.default in meta.choices
