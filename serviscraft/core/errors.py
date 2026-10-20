"""Excepciones propias de Serviscraft."""

from __future__ import annotations


class ServiscraftError(Exception):
    """Error base de la aplicacion.

    El mensaje esta pensado para mostrarse al usuario, por lo que debe estar en
    espanol, ser conciso y no incluir trazas internas.
    """


class ValidationError(ServiscraftError):
    """Una entrada del usuario no cumple las reglas de validacion."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class EngineNotFoundError(ServiscraftError):
    """El motor de contenedores (podman) no esta instalado o no es accesible."""


class EngineError(ServiscraftError):
    """Un comando del motor de contenedores fallo.

    Conserva la salida estandar y el error para poder registrarlos en el log.
    """

    def __init__(self, message: str, *, stdout: str = "", stderr: str = "", returncode: int | None = None) -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class ServerNotFoundError(ServiscraftError):
    """El servidor solicitado no existe en el almacen local."""


class ServerStateError(ServiscraftError):
    """La operacion no es valida para el estado actual del servidor."""


class RconError(ServiscraftError):
    """Fallo al comunicarse con la consola del servidor por RCON."""


class DdnsError(ServiscraftError):
    """Fallo al consultar o actualizar el nombre personalizado (DuckDNS)."""


class BackupError(ServiscraftError):
    """Fallo al crear o restaurar una copia de seguridad."""
