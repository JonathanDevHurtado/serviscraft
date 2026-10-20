"""Cliente del motor de contenedores (Podman) en modo rootless.

Principios de seguridad aplicados aqui:

* Se invoca el binario ``podman`` con listas de argumentos: nunca hay shell.
* Nunca se usa la API REST de Podman ni se activa ``podman.socket`` por TCP.
  Se eliminan ``CONTAINER_HOST`` y ``DOCKER_HOST`` del entorno de los procesos
  hijos para que un valor heredado no pueda desviar las ordenes a un socket o
  a un host remoto.
* Solo se manipulan contenedores con la etiqueta ``serviscraft.managed=true``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from .errors import EngineError, EngineNotFoundError
from .logging_setup import get_logger
from .models import ServerState

logger = get_logger("podman")

#: Etiqueta que marca los contenedores creados por Serviscraft.
MANAGED_LABEL = "serviscraft.managed"
MANAGED_LABEL_VALUE = "true"
#: Etiqueta con el identificador interno del servidor.
ID_LABEL = "serviscraft.id"

#: Un puerto publicado: ``(direccion, puerto_host, puerto_contenedor[, protocolo])``.
#: El protocolo es ``"tcp"`` por defecto; para Bedrock hace falta ``"udp"``.
PortMapping = tuple[str, int, int] | tuple[str, int, int, str]

#: Opciones comunes a todos los comandos.
_GLOBAL_FLAGS = ("--log-level=error",)


class PodmanClient:
    """Envoltorio tipado y seguro de la CLI de Podman."""

    def __init__(self, binary: str = "podman", *, default_timeout: float = 120.0) -> None:
        self.binary = binary
        self.default_timeout = default_timeout

    # ------------------------------------------------------------- entorno
    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        # Evitamos que un socket TCP o remoto heredado desvie las ordenes.
        for variable in ("CONTAINER_HOST", "DOCKER_HOST", "CONTAINER_CONNECTION"):
            env.pop(variable, None)
        env.setdefault("LC_ALL", "C.UTF-8")
        env.setdefault("LANG", "C.UTF-8")
        return env

    def is_installed(self) -> bool:
        return shutil.which(self.binary) is not None

    def ensure_available(self) -> str:
        """Comprueba que Podman existe y funciona; devuelve su version."""
        if not self.is_installed():
            raise EngineNotFoundError(
                "No se encontro Podman. Instalalo con: sudo dnf install podman"
            )
        try:
            result = self.run(("version", "--format", "{{.Client.Version}}"), check=False)
        except EngineError as exc:  # pragma: no cover - depende del entorno
            raise EngineNotFoundError(f"Podman no responde: {exc}") from exc
        if result.returncode != 0:
            raise EngineNotFoundError(
                "Podman no responde correctamente. Comprueba la instalacion rootless."
            )
        return (result.stdout or "").strip() or "desconocida"

    def is_rootless(self) -> bool:
        """Comprueba que Podman funciona sin privilegios (modo rootless)."""
        result = self.run(("info", "--format", "{{.Host.Security.Rootless}}"), check=False)
        return (result.stdout or "").strip().lower() == "true"

    # -------------------------------------------------- ejecucion de comandos
    def build_command(self, args: Sequence[str]) -> list[str]:
        return [self.binary, *_GLOBAL_FLAGS, *[str(a) for a in args]]

    def run(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
        timeout: float | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Ejecuta un subcomando de Podman y captura su salida."""
        command = self.build_command(args)
        logger.debug("Ejecutando: %s", " ".join(command))
        try:
            result = subprocess.run(  # noqa: S603 - argumentos en lista, sin shell
                command,
                capture_output=True,
                text=True,
                timeout=timeout if timeout is not None else self.default_timeout,
                env=self._environment(),
                input=input_text,
                check=False,
                cwd="/",
            )
        except FileNotFoundError as exc:
            raise EngineNotFoundError(f"No se encontro el ejecutable {self.binary!r}.") from exc
        except subprocess.TimeoutExpired as exc:
            raise EngineError(
                f"El comando de Podman tardo demasiado ({exc.timeout:.0f}s).",
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
            ) from exc

        if check and result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise EngineError(
                self._humanize_error(args, message),
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                returncode=result.returncode,
            )
        return result

    @staticmethod
    def _humanize_error(args: Sequence[str], message: str) -> str:
        lowered = message.lower()
        if "permission denied" in lowered:
            return (
                "Podman no tiene permisos sobre los ficheros del servidor. "
                f"Detalle: {message}"
            )
        if "address already in use" in lowered or "port is already allocated" in lowered:
            return f"El puerto indicado ya esta en uso. Detalle: {message}"
        if "no such container" in lowered:
            return f"El contenedor no existe. Detalle: {message}"
        return message or f"El comando 'podman {args[0] if args else ''}' fallo."

    # --------------------------------------------------------------- imagenes
    def image_exists(self, reference: str) -> bool:
        result = self.run(("image", "exists", reference), check=False)
        return result.returncode == 0

    def image_default_user(self, reference: str) -> str:
        """Devuelve el usuario por defecto de la imagen (``""`` si es root)."""
        result = self.run(
            ("image", "inspect", "--format", "{{.User}}", reference), check=False
        )
        return (result.stdout or "").strip()

    def pull_streaming(
        self,
        reference: str,
        *,
        on_line: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        """Descarga una imagen OCI mostrando el progreso linea a linea."""
        command = self.build_command(("pull", reference))
        logger.info("Descargando imagen %s", reference)
        process = subprocess.Popen(  # noqa: S603 - argumentos en lista, sin shell
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=self._environment(),
            cwd="/",
        )
        collected: list[str] = []
        try:
            assert process.stdout is not None
            for line in process.stdout:
                text = line.rstrip("\n")
                collected.append(text)
                if on_line is not None:
                    on_line(text)
                if should_cancel is not None and should_cancel():
                    process.terminate()
                    logger.warning("Descarga de %s cancelada por el usuario", reference)
                    raise EngineError("Descarga de la imagen cancelada.")
            returncode = process.wait(timeout=60)
        finally:
            if process.poll() is None:  # pragma: no cover - limpieza defensiva
                process.kill()
        if returncode != 0:
            raise EngineError(
                "No se pudo descargar la imagen.\n" + "\n".join(collected[-8:]),
                stdout="\n".join(collected),
            )
        logger.info("Imagen %s lista", reference)

    # ------------------------------------------------------------ contenedores
    def container_exists(self, name: str) -> bool:
        result = self.run(("container", "exists", name), check=False)
        return result.returncode == 0

    def inspect(self, name: str) -> dict[str, Any] | None:
        result = self.run(("container", "inspect", name), check=False)
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:  # pragma: no cover - salida inesperada
            logger.warning("Salida de inspect no interpretable para %s", name)
            return None
        if isinstance(data, list):
            return data[0] if data else None
        return data if isinstance(data, dict) else None

    def container_state(self, name: str) -> ServerState:
        """Traduce el estado del contenedor a :class:`ServerState`."""
        if not self.container_exists(name):
            return ServerState.MISSING
        result = self.run(("container", "inspect", "--format", "{{.State.Status}}", name), check=False)
        if result.returncode != 0:
            return ServerState.UNKNOWN
        status = (result.stdout or "").strip().lower()
        mapping = {
            "running": ServerState.RUNNING,
            "exited": ServerState.EXITED,
            "created": ServerState.CREATED,
            "configured": ServerState.CREATED,
            "stopped": ServerState.EXITED,
            "paused": ServerState.PAUSED,
        }
        return mapping.get(status, ServerState.UNKNOWN)

    def container_id(self, name: str) -> str:
        result = self.run(("container", "inspect", "--format", "{{.Id}}", name), check=False)
        return (result.stdout or "").strip()

    def create(
        self,
        *,
        name: str,
        image: str,
        env: dict[str, str],
        published_ports: Sequence["PortMapping"],
        volumes: Sequence[tuple[str, str, str]],
        labels: dict[str, str],
        userns: str | None = None,
        extra_args: Sequence[str] = (),
    ) -> str:
        """Crea (sin iniciar) un contenedor y devuelve su identificador.

        ``published_ports`` es una secuencia de ``(direccion_bind, puerto_host,
        puerto_contenedor)``; si el cuarto elemento es ``"udp"`` el puerto se
        publica en UDP (lo necesita Bedrock). ``volumes`` de ``(ruta_host,
        ruta_contenedor, sufijo_selinux)``.
        """
        args: list[str] = [
            "create",
            "--name",
            name,
            "--restart=no",
            # Contenedor aislado: sin privilegios extra.
            "--security-opt=no-new-privileges",
            # Un servidor de Minecraft (Java) no necesita ninguna capability:
            # sin ellas, un fallo o un plugin malicioso no puede tocar la red,
            # montar sistemas de ficheros ni depurar procesos del host.
            "--cap-drop=ALL",
            # Tope de procesos: un plugin descontrolado no puede agotar el
            # sistema creando hilos hasta el infinito.
            "--pids-limit=1024",
        ]
        if userns:
            args.append(f"--userns={userns}")
        for key, value in labels.items():
            args += ["--label", f"{key}={value}"]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        for mapping in published_ports:
            bind_address, host_port, container_port = mapping[0], mapping[1], mapping[2]
            protocol = mapping[3] if len(mapping) > 3 else "tcp"
            suffix = "" if protocol == "tcp" else f"/{protocol}"
            args += ["-p", f"{bind_address}:{host_port}:{container_port}{suffix}"]
        for host_path, container_path, selinux in volumes:
            suffix = f":{selinux}" if selinux else ""
            args += ["-v", f"{host_path}:{container_path}{suffix}"]
        args += list(extra_args)
        args.append(image)
        result = self.run(args, timeout=180.0)
        return (result.stdout or "").strip()

    def start(self, name: str) -> None:
        self.run(("start", name), timeout=180.0)

    def stop(self, name: str, *, timeout: int = 90) -> None:
        """Detiene el servidor de forma ordenada.

        Enviamos ``stop`` por stdin del proceso principal del contenedor para que
        Minecraft guarde el mundo y se apague limpiamente; si no responde en el
        tiempo indicado, Podman termina el contenedor.
        """
        self.run(("stop", f"--time={max(5, int(timeout))}", name), timeout=timeout + 60.0)

    def kill(self, name: str) -> None:
        self.run(("kill", name), check=False)

    def restart(self, name: str, *, timeout: int = 90) -> None:
        self.run(("restart", f"--time={max(5, int(timeout))}", name), timeout=timeout + 90.0)

    def remove(self, name: str, *, force: bool = False, volumes: bool = False) -> None:
        args = ["rm"]
        if force:
            args.append("--force")
        if volumes:
            args.append("--volumes")
        args.append(name)
        self.run(args, timeout=120.0)

    def wait_healthy(self, name: str, *, timeout: float = 300.0, interval: float = 2.0) -> bool:
        """Espera a que el contenedor indique que el servidor esta listo.

        La imagen escribe ``Done (`` en el registro cuando el servidor termina de
        arrancar. Se comprueba tambien el estado del contenedor para detectar
        salidas prematuras.
        """
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.container_state(name)
            if state is ServerState.EXITED:
                return False
            if state is ServerState.RUNNING:
                logs = self.run(("logs", "--tail", "200", name), check=False)
                output = (logs.stdout or "") + (logs.stderr or "")
                if "Done (" in output or ']: Done' in output:
                    return True
            time.sleep(interval)
        return False

    # ------------------------------------------------------------------ logs
    def logs_text(self, name: str, *, tail: int = 200) -> str:
        result = self.run(("logs", "--tail", str(max(1, tail)), name), check=False)
        return (result.stdout or "") + (result.stderr or "")

    def logs_args(self, name: str, *, tail: int = 300, follow: bool = True) -> list[str]:
        """Argumentos para seguir el registro con ``QProcess`` en la interfaz."""
        args = ["logs", "--tail", str(max(1, tail))]
        if follow:
            args.append("--follow")
        args.append(name)
        return self.build_command(args)

    # ----------------------------------------------------------------- stats
    def stats(self, name: str) -> dict[str, Any] | None:
        """Estadisticas instantaneas del contenedor (CPU, memoria, red, E/S)."""
        result = self.run(
            ("stats", "--no-stream", "--format", "json", name),
            check=False,
            timeout=30.0,
        )
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data:
            return data[0]
        return None

    def managed_containers(self) -> list[dict[str, Any]]:
        """Lista los contenedores creados por Serviscraft."""
        result = self.run(
            (
                "ps",
                "--all",
                "--filter",
                f"label={MANAGED_LABEL}={MANAGED_LABEL_VALUE}",
                "--format",
                "json",
            ),
            check=False,
        )
        if result.returncode != 0:
            return []
        try:
            data = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------- utilidades
    def run_command_interactive(self, name: str, command: Sequence[str]) -> str:
        """Ejecuta un comando dentro del contenedor (uso interno puntual)."""
        result = self.run(("exec", name, *command), check=False, timeout=60.0)
        return (result.stdout or "") + (result.stderr or "")

    def engine_version(self) -> str:
        return (self.run(("version", "--format", "{{.Client.Version}}"), check=False).stdout or "").strip()

    def iter_podman_processes(self) -> Iterator[str]:
        """Itera por los procesos de Podman que contienen el prefijo gestionado."""
        result = self.run(("ps", "--all", "--format", "{{.Names}}"), check=False)
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if line:
                yield line
