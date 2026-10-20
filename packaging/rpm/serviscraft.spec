# Especificacion RPM de Serviscraft.
#
# No compila nada: el paquete es Python puro (``BuildArch: noarch``). Los bytes
# compilados (.pyc) los genera automaticamente la macro brp-python-bytecompile
# de Fedora al final de %install.
#
# Construccion (no requiere root):
#     packaging/build-rpm.sh
#
# Todo el trabajo intermedio se hace en una carpeta SIN espacios (por defecto
# ~/.cache/serviscraft/build/rpm): rpmbuild no soporta rutas con espacios.

%global appname serviscraft

Name:           serviscraft
Version:        0.8.0
Release:        1%{?dist}
Summary:        Gestor grafico de servidores de Minecraft sobre Podman rootless

License:        Proprietary
URL:            https://github.com/JonathanDevHurtado/serviscraft
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

# Podman es una dependencia externa obligatoria: se usa siempre en modo
# rootless y nunca con sudo (la aplicacion lo comprueba al arrancar).
Requires:       podman
Requires:       python3-pyside6

BuildRequires:  python3-rpm-macros
BuildRequires:  desktop-file-utils

%description
Serviscraft es una aplicacion de escritorio para KDE que crea y administra
servidores de Minecraft (Vanilla, Paper, Fabric y Forge) usando contenedores
Podman sin privilegios.

Cada servidor corre en su propio contenedor rootless, con su mundo persistente
en una carpeta del usuario. La interfaz permite iniciar, detener y reiniciar
servidores, seguir la consola en tiempo real, enviar comandos, editar
server.properties, gestionar pluguins, mods y mundos, crear copias de
seguridad y ver el consumo de CPU y memoria.

Seguridad: nunca se ejecuta Podman con sudo, la API de Podman no se expone por
TCP, el cortafuegos no se modifica y ninguna accion destructiva se ejecuta sin
confirmacion explicita.

%prep
%autosetup -n %{name}-%{version}

%build
# Python puro: no hay nada que compilar.

%install
install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{python3_sitelib}
install -d %{buildroot}%{_datadir}/applications
install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps

install -pm0755 scripts/serviscraft %{buildroot}%{_bindir}/serviscraft
cp -a serviscraft %{buildroot}%{python3_sitelib}/
find %{buildroot}%{python3_sitelib} -name '__pycache__' -type d -prune -exec rm -rf {} +
find %{buildroot}%{python3_sitelib} -name '*.py[co]' -delete

install -pm0644 packaging/serviscraft.desktop \
    %{buildroot}%{_datadir}/applications/serviscraft.desktop
install -pm0644 serviscraft/resources/icons/serviscraft.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/serviscraft.svg

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/serviscraft.desktop
%{__python3} -m compileall -q serviscraft

%files
%license LICENSE
%doc README.md CHANGELOG.md TERCEROS.md
%doc docs
%{_bindir}/serviscraft
%{python3_sitelib}/serviscraft
%{_datadir}/applications/serviscraft.desktop
%{_datadir}/icons/hicolor/scalable/apps/serviscraft.svg

%changelog
* Mon Oct 19 2026 Jonathan Hurtado <JonathanHurtadoDev@proton.me> - 0.8.0-1
- Importar servidores existentes (carpeta o .zip de Aternos), texturas y skins
  en el inventario, gestion unificada de listas de jugadores, renombrar copias,
  monitor de CPU y estado real de los servidores.

* Mon Oct 19 2026 Jonathan Hurtado <JonathanHurtadoDev@proton.me> - 0.7.0-1
- Nombre para entrar: un nombre de DuckDNS en vez de una IP, con comprobacion
  de que resuelve y actualizacion automatica de la IP al arrancar.
- Imagen y descripcion del servidor: el icono de 64x64 y las dos lineas de la
  lista de Minecraft, con los 16 colores del juego, vista previa y ocho bloques
  ya dibujados.
- Cabecera adaptable: con poco ancho los botones bajan a su propia linea para
  que el nombre del servidor nunca desaparezca.
- Aspecto: se endurecen la validacion del icono y del texto, y el guardado
  atomico de ambos.

* Mon Oct 19 2026 Jonathan Hurtado <JonathanHurtadoDev@proton.me> - 0.6.0-1
- Jugadores: fichas de resumen (conectados, lista blanca, operadores,
  bloqueados), cara del jugador en la tabla y colores en los «Si».
- Inventario del jugador: ventana con la mochila, la armadura y la barra rapida
  tal y como las ve el jugador, con vida, comida y nivel. Se lee del servidor
  por la consola, sin instalar nada ni tocar el mundo.
- Consola con mas personalidad: punto de estado, leyenda de colores, filtro
  «Solo problemas», «Copiar todo».
- Botones «?» con la explicacion de cada seccion en Consola, Jugadores, Mods y
  Unirse; etiquetas cortas y tooltips en las acciones de jugadores.

* Mon Oct 19 2026 Jonathan Hurtado <JonathanHurtadoDev@proton.me> - 0.5.0-1
- Los servidores antiguos que murieron por llevar el Java equivocado se
  reparan solos al arrancar (se explica el motivo y se cambia la etiqueta de
  Java sin tocar el mundo).
- Compatibilidad de datos: los ficheros de servidores de versiones anteriores se
  migran conservando todas las claves y sin perder mundos.
- Seguimiento en vivo de la consola activado por defecto, conmutable y sin
  bloquear la ventana.
- Nueva pestana Unirse paso a paso, con la IP publica y la guia para jugar desde
  fuera de casa.
- Jugadores de Bedrock (movil, tablet y consola) con Geyser y Floodgate en
  servidores Paper: puerto UDP propio y ajuste automatico de Floodgate.
- Iconos junto al nombre del servidor para distinguir Java (cesped) y Bedrock
  (piedra), y el icono real de cada mod o pluguin en las listas.
- Los textos de ayuda se adaptan a ventanas estrechas (mosaico) sin recortarse
  ni solaparse con lo que viene debajo.
- Las actualizaciones nunca borran datos ni reinician servidores.

* Mon Oct 19 2026 Jonathan Hurtado <JonathanHurtadoDev@proton.me> - 0.4.0-1
- El selector de modpacks muestra cargador, versiones de Minecraft, descargas y
  ultima actualizacion de cada pack, con filtros por cargador y por lado.
- El catalogo de mods y pluguins ensena los mismos datos y solo ofrece contenido
  de los cargadores que entiende el servidor.
- La version de Minecraft deja de ser un campo de texto: solo se eligen versiones
  de la lista publicada (con boton para actualizarla).
- Los ajustes del servidor se organizan por secciones y la memoria y Java de un
  servidor ya creado se pueden cambiar (memoria con deslizador).
- Nueva pestana Mods: activar y desactivar sin borrar, eliminar, y anadir desde
  el catalogo de Modrinth, desde un .jar del equipo o desde una URL.
- Nueva pestana Registros, con filtro por texto, seguimiento automatico y boton
  para buscar los mods que faltan.
- Nueva pestana Unirse: direccion y puerto para conectarse, y cambio del modo de
  cuentas (premium o sin licencia) con aviso de seguridad y confirmacion.
- Detecta en el registro los mods que el modpack no pudo descargar, muestra su
  enlace de Modrinth, los marca en verde cuando ya estan y copia el .jar
  descargado dentro del servidor.
- Corrige las cajas de numeros (memoria y puerto): al escribir encima ya no se
  mezcla el valor anterior y la rueda del raton no los cambia por accidente.
- Las tareas de fondo ya no avisan a ventanas que se han cerrado.

* Sun Oct 18 2026 Jonathan Hurtado <JonathanHurtadoDev@proton.me> - 0.3.0-1
- Anade copia de seguridad automatica al detener cada servidor, guardada en la
  carpeta de copias del propio servidor y con su origen bien visible.
- Anade copias programadas cada cierto numero de minutos para los servidores en
  marcha, con retencion configurable (solo afecta a las copias automaticas).
- Cada copia guarda su origen (al detener, programada, manual, automatica o
  importada) y la limpieza automatica nunca borra las copias manuales.
- Anade la pestana Jugadores: conectados, lista blanca, operadores y bloqueados,
  con acciones de OP, expulsion, bloqueo y perdon (por consola RCON).
- Anade soporte de modpacks de Modrinth con su cargador (Fabric, Forge o Quilt)
  y aviso claro cuando el pack solo existe para NeoForge.
- Reiniciar pasa a ser una parada ordenada (con su copia) mas un arranque.
- Dos copias hechas en el mismo segundo ya no se pisan.

* Sun Oct 18 2026 Jonathan Hurtado <JonathanHurtadoDev@proton.me> - 0.2.0-1
- Corrige el fallo que impedia abrir el asistente de creacion de servidores
  (se comprobaba el puerto antes de crear el boton «Crear servidor»).
- Anade cambio de version de Minecraft a un servidor existente, con Java
  recomendado automatico y aviso de compatibilidad del mundo.
- Anade catalogo Modrinth para buscar e instalar pluguins y mods con un clic,
  con verificacion SHA-512 de las descargas.
- Anade botones y acciones para abrir la carpeta de datos y la de copias.
- Paper queda seleccionado por defecto en el asistente (admite pluguins).
- Las pruebas cubren el flujo principal completo: crear, ajustar y cambiar
  de version sin lanzar contenedores reales.

* Sun Oct 18 2026 Jonathan Hurtado <JonathanHurtadoDev@proton.me> - 0.1.0-1
- Version inicial: creacion y gestion de servidores de Minecraft con Podman
  rootless, consola en tiempo real, propiedades, pluguins/mods, mundos,
  copias de seguridad y estadisticas de CPU y memoria.
