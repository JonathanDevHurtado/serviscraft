"""Pruebas del cliente de Modrinth (sin conexion a internet)."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from serviscraft.core import modrinth
from serviscraft.core.models import ServerType


def _version(
    *,
    filename: str = "plugin-1.0.jar",
    primary: bool = True,
    sha512: str | None = "abc123",
    game_versions: tuple[str, ...] = ("1.21.4",),
    loaders: tuple[str, ...] = ("paper",),
    dependencies: tuple[dict, ...] = (),
    name: str = "Plugin 1.0",
    number: str = "1.0",
) -> dict:
    files = [
        {
            "url": f"https://cdn.modrinth.com/data/p/versions/1/{filename}",
            "filename": filename,
            "primary": primary,
            "size": 1234,
            "hashes": {"sha512": sha512} if sha512 else {},
        }
    ]
    return {
        "name": name,
        "version_number": number,
        "game_versions": list(game_versions),
        "loaders": list(loaders),
        "files": files,
        "dependencies": list(dependencies),
    }


class TestFiltros:
    def test_incluye_tipo_y_version(self) -> None:
        facets = json.loads(modrinth.search_facets("plugin", "1.21.4"))
        assert facets == [["project_type:plugin"], ["versions:1.21.4"]]

    def test_latest_no_filtra_por_version(self) -> None:
        facets = json.loads(modrinth.search_facets("mod", "latest"))
        assert facets == [["project_type:mod"]]

    def test_cargadores_por_tipo_de_servidor(self) -> None:
        assert "paper" in modrinth.loaders_for(ServerType.PAPER)
        assert modrinth.loaders_for(ServerType.FABRIC) == ("fabric",)
        assert modrinth.loaders_for(ServerType.FORGE) == ("forge",)
        assert modrinth.loaders_for(ServerType.VANILLA) == ()


class TestBusqueda:
    def test_descarta_los_mods_solo_de_cliente(self, monkeypatch: pytest.MonkeyPatch) -> None:
        visto: dict[str, str] = {}

        def falso_json(url: str):
            visto["url"] = url
            return {
                "hits": [
                    {
                        "project_id": "sirve",
                        "slug": "sirve",
                        "title": "Sirve",
                        "description": "Para el servidor",
                        "downloads": 10,
                        "project_type": "plugin",
                        "server_side": "required",
                    },
                    {
                        "project_id": "cliente",
                        "slug": "cliente",
                        "title": "Solo cliente",
                        "description": "No sirve",
                        "downloads": 99,
                        "project_type": "plugin",
                        "server_side": "unsupported",
                    },
                ]
            }

        monkeypatch.setattr(modrinth, "_request_json", falso_json)
        proyectos = modrinth.search_projects("mapa", project_type="plugin", game_version="1.21.4")

        assert [p.id for p in proyectos] == ["sirve"]
        consulta = parse_qs(urlsplit(visto["url"]).query)
        assert consulta["query"] == ["mapa"]
        assert json.loads(consulta["facets"][0]) == [
            ["project_type:plugin"],
            ["versions:1.21.4"],
        ]

    def test_el_orden_llega_a_modrinth_y_usa_descargas_sin_busqueda(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La lista de ordenes del catalogo se traduce en el parametro ``index``."""
        vistos: list[str] = []

        def falso_json(url: str):
            consulta = parse_qs(urlsplit(url).query)
            vistos.append(consulta["index"][0])
            return {"hits": []}

        monkeypatch.setattr(modrinth, "_request_json", falso_json)
        modrinth.search_projects("", project_type="plugin")
        modrinth.search_projects("mapa", project_type="plugin", index="updated")
        modrinth.search_projects("mapa", project_type="plugin", index="inventado")

        # Sin texto se muestran los mas descargados; un orden desconocido cae
        # en relevancia para que Modrinth no rechace la consulta.
        assert vistos == ["downloads", "updated", "relevance"]

    def test_devuelve_la_descripcion_y_las_descargas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            modrinth,
            "_request_json",
            lambda url: {
                "hits": [
                    {
                        "project_id": "p1",
                        "slug": "essentialsx",
                        "title": "EssentialsX",
                        "description": "Comandos esenciales",
                        "downloads": 1234567,
                        "project_type": "plugin",
                    }
                ]
            },
        )
        proyecto = modrinth.search_projects("", project_type="plugin")[0]
        assert proyecto.title == "EssentialsX"
        assert proyecto.downloads == 1234567
        assert proyecto.page_url == "https://modrinth.com/plugin/essentialsx"


class TestVersiones:
    def test_parsea_el_fichero_principal_y_las_dependencias(self) -> None:
        release = modrinth.parse_release(
            "p1",
            _version(dependencies=({"project_id": "dep", "dependency_type": "required"},)),
        )
        assert release is not None
        assert release.filename == "plugin-1.0.jar"
        assert release.sha512 == "abc123"
        assert release.dependencies == ("dep",)

    def test_fetch_releases_pide_version_y_cargadores(self, monkeypatch: pytest.MonkeyPatch) -> None:
        visto: dict[str, str] = {}

        def falso_json(url: str):
            visto["url"] = url
            return [
                _version(filename="nuevo.jar", name="Nuevo"),
                _version(filename="viejo.jar", name="Viejo"),
            ]

        monkeypatch.setattr(modrinth, "_request_json", falso_json)
        releases = modrinth.fetch_releases("proyecto/1", game_version="1.21.4", loaders=("paper", "spigot"))

        consulta = parse_qs(urlsplit(visto["url"]).query)
        assert json.loads(consulta["game_versions"][0]) == ["1.21.4"]
        assert json.loads(consulta["loaders"][0]) == ["paper", "spigot"]
        assert modrinth.choose_release(releases).filename == "nuevo.jar"

    def test_sin_versiones_compatibles_no_elige_ninguna(self) -> None:
        assert modrinth.choose_release([]) is None


class TestModpacks:
    def test_la_busqueda_pide_solo_modpacks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        visto: dict[str, str] = {}

        def falso_json(url: str):
            visto["url"] = url
            return {
                "hits": [
                    {
                        "project_id": "cobblemon",
                        "slug": "cobblemon-fabric",
                        "title": "Cobblemon",
                        "description": "Pokemon en Minecraft",
                        "downloads": 5000,
                        "project_type": "modpack",
                        # Modrinth marca casi todos los packs como «solo cliente»:
                        # no deben descartarse, la imagen los instala igualmente.
                        "server_side": "unsupported",
                    }
                ]
            }

        monkeypatch.setattr(modrinth, "_request_json", falso_json)
        proyectos = modrinth.search_modpacks("cobblemon")

        consulta = parse_qs(urlsplit(visto["url"]).query)
        assert json.loads(consulta["facets"][0]) == [["project_type:modpack"]]
        assert [p.slug for p in proyectos] == ["cobblemon-fabric"]

    def test_los_mods_de_cliente_se_siguen_descartando(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def falso_json(url: str):
            return {
                "hits": [
                    {"project_id": "sodium", "slug": "sodium", "title": "Sodium", "server_side": "unsupported"},
                    {"project_id": "lithium", "slug": "lithium", "title": "Lithium", "server_side": "optional"},
                ]
            }

        monkeypatch.setattr(modrinth, "_request_json", falso_json)

        mods = modrinth.search_projects(
            "rendimiento", project_type=modrinth.PROJECT_TYPE_MOD, game_version="1.21.4"
        )
        assert [p.slug for p in mods] == ["lithium"]

    def test_parsea_la_version_interna_y_el_tipo(self) -> None:
        datos = _version(loaders=("fabric",), game_versions=("1.21.1",))
        datos["id"] = "Oa9ZDzZq"
        datos["version_type"] = "release"
        release = modrinth.parse_release("cobblemon", datos)

        assert release is not None
        assert release.version_id == "Oa9ZDzZq"
        assert release.version_type == "release"

    def test_el_plan_elige_cargador_y_minecraft_mas_nuevo(self) -> None:
        proyecto = modrinth.Project(
            id="p1", slug="cobblemon-fabric", title="Cobblemon", description="", downloads=1
        )
        release = modrinth.Release(
            project_id="p1",
            name="Cobblemon 1.6",
            version_number="1.6.0",
            game_versions=("1.21", "1.21.1"),
            loaders=("forge", "fabric"),
            download_url="https://cdn.modrinth.com/x.mrpack",
            filename="pack.mrpack",
            version_id="Oa9ZDzZq",
        )

        plan = modrinth.plan_modpack(proyecto, release)

        assert plan is not None
        assert plan.loader == "forge"
        assert plan.minecraft_version == "1.21.1"
        assert plan.installable
        assert plan.extra_env() == {
            "MODRINTH_MODPACK": "cobblemon-fabric",
            "MODRINTH_VERSION": "Oa9ZDzZq",
            "MODRINTH_LOADER": "forge",
        }

    def test_un_pack_solo_de_neoforge_no_se_puede_instalar(self) -> None:
        proyecto = modrinth.Project(
            id="p1", slug="pack-neo", title="Pack Neo", description="", downloads=1
        )
        release = modrinth.Release(
            project_id="p1",
            name="Pack Neo",
            version_number="2.0",
            game_versions=("1.21.4",),
            loaders=("neoforge",),
            download_url="https://cdn.modrinth.com/x.mrpack",
            filename="pack.mrpack",
        )

        assert modrinth.plan_modpack(proyecto, release) is None

    def test_se_elige_la_primera_version_instalable(self) -> None:
        no_valida = modrinth.Release(
            project_id="p1",
            name="Solo NeoForge",
            version_number="2.0",
            game_versions=("1.21.4",),
            loaders=("neoforge",),
            download_url="u",
            filename="a.mrpack",
        )
        valida = modrinth.Release(
            project_id="p1",
            name="Fabric",
            version_number="1.9",
            game_versions=("1.21.1",),
            loaders=("fabric",),
            download_url="u",
            filename="b.mrpack",
        )

        assert modrinth.choose_modpack_version([no_valida, valida]) is valida
        assert modrinth.choose_modpack_version([]) is None

    def test_se_prefiere_una_version_estable_antes_que_una_beta(self) -> None:
        beta = modrinth.Release(
            project_id="p1",
            name="Beta",
            version_number="15.0.0-beta.1",
            game_versions=("1.21.4",),
            loaders=("fabric",),
            download_url="u",
            filename="beta.mrpack",
            version_type="beta",
        )
        estable = modrinth.Release(
            project_id="p1",
            name="Estable",
            version_number="14.1.1",
            game_versions=("1.21.1",),
            loaders=("fabric",),
            download_url="u",
            filename="estable.mrpack",
            version_type="release",
        )

        assert modrinth.choose_modpack_version([beta, estable]) is estable
        # Si solo hay betas, se usa la mas nueva.
        assert modrinth.choose_modpack_version([beta]) is beta

    def test_los_cargadores_del_servidor_con_modpack_son_los_del_pack(self) -> None:
        from serviscraft.core.models import ServerSpec

        spec = ServerSpec(
            id="pack-test01",
            name="Pack",
            type=ServerType.MODRINTH,
            version="1.21.1",
            memory_mb=4096,
            port=25565,
            rcon_port=25575,
            rcon_password="contrasena-larga",
            image="docker.io/itzg/minecraft-server",
            extra_env={"MODRINTH_LOADER": "quilt"},
        ).validated()

        assert modrinth.loaders_for_spec(spec) == ("quilt",)
        assert modrinth.project_type_for(spec) == modrinth.PROJECT_TYPE_MOD
        assert ServerType.MODRINTH.supports_mods
        assert not ServerType.MODRINTH.supports_plugins


class TestDescarga:
    def test_pasa_la_suma_de_comprobacion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pathlib import Path

        recibido: dict = {}

        class FalsoFiles:
            def download(self, url, destination, **kwargs):
                recibido.update({"url": url, "destination": destination, **kwargs})
                return Path("/tmp/plugin.jar")

        release = modrinth.Release(
            project_id="p1",
            name="Plugin",
            version_number="1.0",
            game_versions=("1.21.4",),
            loaders=("paper",),
            download_url="https://cdn.modrinth.com/x.jar",
            filename="plugin.jar",
            size=10,
            sha512="deadbeef",
        )
        modrinth.download_release(FalsoFiles(), release, "plugins")

        assert recibido["filename"] == "plugin.jar"
        assert recibido["expected_sha512"] == "deadbeef"


class TestInformacionDeLosResultados:
    """La busqueda trae cargador, versiones de Minecraft, lado y fecha."""

    def _hit(self, **extra) -> dict:
        datos = {
            "project_id": "cobblemon",
            "slug": "cobblemon-fabric",
            "title": "Cobblemon",
            "description": "Pokemon en Minecraft",
            "downloads": 11393653,
            "project_type": "modpack",
            "categories": ["adventure", "fabric", "forge", "mobs"],
            "versions": ["1.21.1", "1.20.1", "1.19.2"],
            "client_side": "required",
            "server_side": "required",
            "date_modified": "2025-03-04T12:00:00Z",
            "follows": 4321,
            "author": "Cobblemon",
        }
        datos.update(extra)
        return datos

    def test_extrae_cargadores_versiones_y_fecha(self) -> None:
        proyecto = modrinth.parse_project(self._hit())

        assert proyecto.loaders == ("fabric", "forge")
        assert proyecto.minecraft_label == "1.21.1, 1.20.1 (+1)"
        assert proyecto.updated_label == "04/03/2025"
        assert proyecto.side_label == "servidor y cliente"
        assert proyecto.works_on_server is True
        assert proyecto.follows == 4321
        assert proyecto.author == "Cobblemon"

    def test_un_proyecto_de_cliente_se_marca_como_tal(self) -> None:
        proyecto = modrinth.parse_project(self._hit(server_side="unsupported"))

        assert proyecto.works_on_server is False
        assert proyecto.side_label == "solo cliente"

    def test_las_etiquetas_aguantan_datos_incompletos(self) -> None:
        proyecto = modrinth.Project("p", "s", "T", "", 0)

        assert proyecto.loader_label == "sin datos"
        assert proyecto.minecraft_label == "sin datos"
        assert proyecto.updated_label == "sin datos"
        assert proyecto.side_label == "sin datos"
        # Sin datos de lado se deja ver: Modrinth no siempre lo rellena.
        assert proyecto.works_on_server is True

    def test_los_cargadores_van_en_el_filtro_de_modrinth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        visto: dict[str, str] = {}

        def falso_json(url: str):
            visto["url"] = url
            return {"hits": []}

        monkeypatch.setattr(modrinth, "_request_json", falso_json)
        modrinth.search_projects(
            "mapa", project_type="plugin", game_version="1.21.4", loaders=("paper", "spigot")
        )

        facets = json.loads(parse_qs(urlsplit(visto["url"]).query)["facets"][0])
        assert facets == [
            ["project_type:plugin"],
            ["versions:1.21.4"],
            ["categories:paper", "categories:spigot"],
        ]

    def test_la_busqueda_de_modpacks_admite_cargador(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        visto: dict[str, str] = {}

        def falso_json(url: str):
            visto["url"] = url
            return {"hits": []}

        monkeypatch.setattr(modrinth, "_request_json", falso_json)
        modrinth.search_modpacks("cobblemon", loaders=("forge",))

        consulta = parse_qs(urlsplit(visto["url"]).query)
        assert json.loads(consulta["facets"][0]) == [
            ["project_type:modpack"],
            ["categories:forge"],
        ]
        assert consulta["limit"] == ["40"]

    def test_los_cargadores_se_deducen_solo_de_las_categorias_conocidas(self) -> None:
        proyecto = modrinth.parse_project(
            self._hit(categories=["optimization", "quilt", "neoforge", "utility"])
        )

        assert proyecto.loaders == ("quilt", "neoforge")


class TestSiguientesPaginasYCompatibilidad:
    def test_offset_y_categoria_llegan_a_modrinth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        visto: dict[str, str] = {}

        def falso_json(url: str):
            visto["url"] = url
            return {"hits": []}

        monkeypatch.setattr(modrinth, "_request_json", falso_json)
        modrinth.search_projects(
            "mapa",
            project_type="plugin",
            game_version="1.21.4",
            loaders=("paper",),
            category="utility",
            offset=40,
        )

        consulta = parse_qs(urlsplit(visto["url"]).query)
        assert consulta["offset"] == ["40"]
        assert json.loads(consulta["facets"][0]) == [
            ["project_type:plugin"],
            ["versions:1.21.4"],
            ["categories:paper"],
            ["categories:utility"],
        ]

    def test_una_version_incompatible_no_se_confunde_con_la_buena(self) -> None:
        buena = modrinth.parse_release(
            "p",
            _version(filename="buena.jar", game_versions=("1.21.4",), loaders=("paper",)),
        )
        otra = modrinth.parse_release(
            "p",
            _version(filename="otra.jar", game_versions=("1.20.1",), loaders=("paper",)),
        )
        assert buena is not None and otra is not None

        assert modrinth.release_is_compatible(
            buena, game_version="1.21.4", loaders=("paper", "spigot")
        )
        assert not modrinth.release_is_compatible(
            buena, game_version="1.20.1", loaders=("paper",)
        )
        assert not modrinth.release_is_compatible(
            buena, game_version="1.21.4", loaders=("fabric",)
        )
        # Sin version concreta (latest) solo manda el cargador.
        assert modrinth.release_is_compatible(
            buena, game_version="latest", loaders=("paper",)
        )

        assert (
            modrinth.choose_compatible_release(
                [otra, buena], game_version="1.21.4", loaders=("paper",)
            )
            is buena
        )
        assert (
            modrinth.choose_compatible_release(
                [otra], game_version="1.21.4", loaders=("paper",)
            )
            is None
        )

    def test_una_version_sin_cargadores_anunciados_se_acepta(self) -> None:
        release = modrinth.parse_release(
            "p",
            _version(game_versions=("1.21.4",), loaders=()),
        )
        assert release is not None
        assert modrinth.release_is_compatible(
            release, game_version="1.21.4", loaders=("paper",)
        )
