# Componentes de terceros

Serviscraft es propietario, pero se apoya en software y servicios de terceros que
mantienen **sus propias licencias**. Esta página los resume; los textos completos
están en cada proyecto y en los paquetes instalados en el sistema.

## Bibliotecas y programas

| Componente | Uso en Serviscraft | Licencia |
| --- | --- | --- |
| **Python** (3.10 o superior) | Lenguaje de la aplicación. El AppImage incluye una copia de *python-build-standalone*. | PSF License |
| **PySide6 / Qt 6** | Interfaz gráfica. En el RPM y el DEB se usa el paquete del sistema; el AppImage incluye las ruedas oficiales. | LGPL-3.0 (o GPL-3.0 / comercial, según la distribución de Qt) |
| **Podman** | Motor de contenedores. **No se incluye**: es una dependencia externa que debe estar instalada y en modo rootless. | Apache-2.0 |
| **pytest / pytest-qt** | Pruebas (solo desarrollo). | MIT |
| **setuptools / wheel** | Empaquetado (solo desarrollo). | MIT |

Los paquetes oficiales de PySide6/Qt incluyen sus propios avisos de licencia. Si
distribuyes el AppImage, conserva esos avisos y ten en cuenta las obligaciones de
la LGPL-3.0 sobre la biblioteca Qt (entre ellas, permitir su sustitución). El
código fuente de Qt y PySide6 está disponible en sus repositorios oficiales.

## Servicios que se consultan en tiempo de ejecución

Ninguno de estos servicios se distribuye con el programa; solo se consultan por
HTTPS cuando usas una función que los necesita.

| Servicio | Para qué | Condiciones |
| --- | --- | --- |
| **Modrinth** (`api.modrinth.com`) | Catálogo de mods, plugins y modpacks; descarga de `.jar`. | Términos y API de Modrinth |
| **Mojang** (`piston-meta.mojang.com`) | Lista de versiones de Minecraft. | Términos de Mojang |
| **DuckDNS** (`www.duckdns.org`) | Nombre para entrar en el servidor y actualización de IP. | Términos de DuckDNS |
| **mc-heads.net** | Skins de jugadores para el inventario. | Términos del servicio |
| **raw.githubusercontent.com** (espejo de recursos de Minecraft) | Texturas de objetos para el inventario. | Licencia del repositorio de recursos |
| **GitHub** | Iconos de proyectos de Modrinth, cuando el catálogo los enlaza. | Términos de GitHub |

Serviscraft **no** envía datos personales a estos servicios: solo hace la consulta
necesaria (por ejemplo, el nombre del jugador para pedir su skin o el nombre del
mod para buscar su icono). Puedes desactivar toda descarga con
`SERVISCRAFT_OFFLINE=1`.

## Marcas

«Minecraft» es una marca registrada de Mojang AB. «Podman» es una marca de Red
Hat, Inc. «KDE» y «Plasma» son marcas de KDE e.V. Serviscraft **no está afiliado,
patrocinado ni respaldado** por Mojang, Microsoft, Red Hat ni KDE.

Los iconos y bloques dibujados a mano de `ui/mc_icons.py` son originales de
Serviscraft y se inspiran en el estilo visual del juego sin copiar sus texturas.
Las texturas reales se descargan en tiempo de ejecución y no forman parte de este
repositorio.
