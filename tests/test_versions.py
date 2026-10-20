"""Pruebas de la lista de versiones y de la recomendacion de Java."""

from __future__ import annotations

import pytest

from serviscraft.core.versions import (
    VersionInfo,
    parse_manifest,
    recommended_java_tag,
    version_choices,
)


@pytest.mark.parametrize(
    ("version", "java"),
    [
        # ``latest`` ya apunta a Minecraft 26.x, que exige Java 25: elegir
        # java21 hacia que el servidor arrancara y muriera al instante.
        ("latest", "java25"),
        ("26.3", "java25"),
        ("26.1", "java25"),
        ("25.4", "java25"),
        ("26w01a", "java25"),
        ("1.21.4", "java21"),
        ("1.21", "java21"),
        ("1.20.5", "java21"),
        ("1.20.4", "java17"),
        ("1.20.1", "java17"),
        ("1.18.2", "java17"),
        ("1.17.1", "java17"),
        ("1.16.5", "java8"),
        ("1.12.2", "java8"),
        ("1.8.9", "java8"),
        ("24w14a", "java21"),
    ],
)
def test_java_recomendado(version: str, java: str) -> None:
    assert recommended_java_tag(version) == java


def test_java_disponible_cubre_lo_pedido() -> None:
    """La etiqueta elegida nunca se queda corta respecto a lo que pide Java."""
    from serviscraft.core.paths import JAVA_TAGS
    from serviscraft.core.versions import java_major_of_tag, java_tag_for_major

    for major in (8, 11, 17, 21, 25):
        tag = java_tag_for_major(major)
        assert tag in JAVA_TAGS
        assert java_major_of_tag(tag) >= major

def test_parse_manifest_extrae_las_versiones() -> None:
    payload = """
    {"versions": [
        {"id": "1.21.4", "type": "release"},
        {"id": "24w14a", "type": "snapshot"}
    ]}
    """
    versions = parse_manifest(payload)
    assert [v.id for v in versions] == ["1.21.4", "24w14a"]
    assert "snapshot" in versions[1].label


def test_version_choices_pone_latest_primero() -> None:
    choices = version_choices([VersionInfo("1.21.4", "release")])
    assert choices == ["latest", "1.21.4"]
