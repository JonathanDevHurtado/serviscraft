"""Pruebas de compatibilidad con servidores creados por versiones anteriores.

Regla del proyecto: actualizar Serviscraft nunca puede dejar un servidor
inservible ni, mucho menos, perder su mundo. Estas pruebas cargan definiciones
antiguas tal y como estarian en el disco y comprueban que:

* se completan los campos nuevos con valores sensatos,
* las claves que esta version no conoce se conservan al guardar,
* el contenido de ``data/`` (el mundo, los mods, los configs) no se toca.
"""

from __future__ import annotations

import json
from pathlib import Path

from serviscraft.core.store import META_VERSION, ServerStore, migrate_meta


def _write_old_meta(store: ServerStore, server_id: str, payload: dict) -> Path:
    """Escribe un ``meta.json`` como lo dejaria una version antigua."""
    carpeta = store.server_dir(server_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / "meta.json"
    destino.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return destino


#: Definicion tal y como la escribia la primera version publica: sin
#: ``meta_version``, sin Bedrock y sin ``java_tag``.
META_ANTIGUA = {
    "id": "viejo-111111",
    "name": "Mundo de toda la vida",
    "type": "PAPER",
    "version": "1.21.4",
    "memory_mb": 2048,
    "port": 25566,
    "rcon_port": 25576,
    "rcon_password": "contrasena-antigua-1234",
    "image": "docker.io/itzg/minecraft-server",
    "lan": True,
    "notes": "no borrar",
    "created_at": "2025-01-01T00:00:00+00:00",
    "last_started_at": None,
    "extra_env": {},
}


def test_una_definicion_antigua_se_carga_y_se_migra(store: ServerStore) -> None:
    _write_old_meta(store, "viejo-111111", META_ANTIGUA)

    spec = store.load("viejo-111111")

    assert spec.name == "Mundo de toda la vida"
    assert spec.port == 25566
    assert spec.bedrock is False
    assert spec.bedrock_port == 19132
    # Se le pone la etiqueta de Java que pide su version, no una al azar.
    assert spec.java_tag == "java21"
    # Y la migracion queda escrita para no repetirla en cada arranque.
    guardado = json.loads(store.meta_file("viejo-111111").read_text(encoding="utf-8"))
    assert guardado["meta_version"] == META_VERSION


def test_la_migracion_no_toca_el_mundo(store: ServerStore) -> None:
    _write_old_meta(store, "viejo-111111", META_ANTIGUA)
    data = store.data_dir("viejo-111111")
    (data / "world" / "region").mkdir(parents=True)
    (data / "world" / "level.dat").write_bytes(b"mi mundo")
    (data / "world" / "region" / "r.0.0.mca").write_bytes(b"x" * 128)
    (data / "server.properties").write_text("motd=Hola\n", encoding="utf-8")

    store.load("viejo-111111")

    assert (data / "world" / "level.dat").read_bytes() == b"mi mundo"
    assert (data / "world" / "region" / "r.0.0.mca").read_bytes() == b"x" * 128
    assert (data / "server.properties").read_text(encoding="utf-8") == "motd=Hola\n"


def test_las_claves_desconocidas_sobreviven_a_guardar(store: ServerStore) -> None:
    """Una version futura puede añadir campos: una anterior no debe borrarlos."""
    futuro = dict(META_ANTIGUA)
    futuro["meta_version"] = META_VERSION
    futuro["backup_schedule"] = {"cada_horas": 6}
    futuro["mods_favoritos"] = ["jei", "sodium"]
    _write_old_meta(store, "viejo-111111", futuro)

    spec = store.load("viejo-111111")
    store.save(spec)

    guardado = json.loads(store.meta_file("viejo-111111").read_text(encoding="utf-8"))
    assert guardado["backup_schedule"] == {"cada_horas": 6}
    assert guardado["mods_favoritos"] == ["jei", "sodium"]


def test_una_definicion_sin_java_tag_elige_la_de_su_version(store: ServerStore) -> None:
    antigua = dict(META_ANTIGUA)
    antigua["version"] = "26.3"
    antigua.pop("java_tag", None)
    _write_old_meta(store, "viejo-111111", antigua)

    assert store.load("viejo-111111").java_tag == "java25"


def test_el_puerto_de_bedrock_corrupto_se_corrige(store: ServerStore) -> None:
    rota = dict(META_ANTIGUA)
    rota["meta_version"] = META_VERSION
    rota["bedrock_port"] = "no es un numero"
    _write_old_meta(store, "viejo-111111", rota)

    assert store.load("viejo-111111").bedrock_port == 19132


def test_una_contrasena_de_rcon_antigua_se_renueva(store: ServerStore) -> None:
    """Sin esto el servidor se cargaria pero ya no se podria volver a guardar."""
    antigua = dict(META_ANTIGUA)
    antigua["rcon_password"] = "corta"
    _write_old_meta(store, "viejo-111111", antigua)

    spec = store.load("viejo-111111")

    assert len(spec.rcon_password) >= 8
    # Y se puede guardar sin errores, que es lo que fallaba antes.
    store.save(spec)


def test_la_migracion_es_idempotente(store: ServerStore) -> None:
    _write_old_meta(store, "viejo-111111", META_ANTIGUA)
    primera = store.load("viejo-111111")
    segunda = store.load("viejo-111111")
    assert primera.to_dict() == segunda.to_dict()


def test_una_definicion_sin_imagen_usa_la_de_por_defecto() -> None:
    datos, cambiado = migrate_meta(
        {
            "id": "x-111111",
            "name": "X",
            "type": "VANILLA",
            "version": "1.21.4",
            "image": "",
        }
    )
    assert cambiado
    assert datos["image"] == "docker.io/itzg/minecraft-server"


def test_guardar_conserva_la_version_del_esquema(store: ServerStore) -> None:
    """Sin esto, guardar un servidor borraba la marca de migracion."""
    _write_old_meta(store, "viejo-111111", META_ANTIGUA)
    spec = store.load("viejo-111111")
    store.save(spec)

    guardado = json.loads((store.meta_file("viejo-111111")).read_text(encoding="utf-8"))
    assert guardado["meta_version"] == META_VERSION
    # Y la migracion no se repite: ya esta al dia.
    assert store.load("viejo-111111").to_dict() == spec.to_dict()
