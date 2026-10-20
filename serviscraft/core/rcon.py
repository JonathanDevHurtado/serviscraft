"""Cliente RCON (Source RCON) en Python puro.

La imagen del servidor expone RCON en ``127.0.0.1`` dentro del contenedor; la
aplicacion publica ese puerto **solo en la direccion de bucle local del host**,
de modo que la consola nunca queda accesible desde la red.
"""

from __future__ import annotations

import socket
import struct

from .errors import RconError, ValidationError
from .logging_setup import get_logger

logger = get_logger("rcon")

#: Tipos de paquete del protocolo Source RCON.
SERVERDATA_AUTH = 3
SERVERDATA_EXECCOMMAND = 2

MAX_COMMAND_LENGTH = 1000
_MAX_PACKET_SIZE = 4 * 1024 * 1024
#: Tope de la respuesta completa de un comando. El servidor (o un plugin
#: malicioso) podria encadenar paquetes validos sin parar y agotar la memoria.
_MAX_RESPONSE_SIZE = 8 * 1024 * 1024
#: Numero maximo de paquetes que se aceptan como respuesta de un comando.
_MAX_RESPONSE_PACKETS = 512


def validate_console_command(command: str) -> str:
    """Valida un comando de consola antes de enviarlo por RCON.

    Se rechazan saltos de linea y caracteres de control: evita que un comando
    "colado" ejecute varias ordenes de golpe (``stop\\nop ...``).
    """
    cleaned = str(command or "")
    if not cleaned.strip():
        raise ValidationError("command", "El comando esta vacio.")
    if "\n" in cleaned or "\r" in cleaned:
        raise ValidationError("command", "El comando no puede contener saltos de linea.")
    if any(ord(ch) < 32 and ch != "\t" for ch in cleaned):
        raise ValidationError("command", "El comando contiene caracteres no permitidos.")
    if len(cleaned) > MAX_COMMAND_LENGTH:
        raise ValidationError("command", f"El comando es demasiado largo (maximo {MAX_COMMAND_LENGTH}).")
    return cleaned


class RconClient:
    """Conexion RCON reutilizable, usada desde un hilo de trabajo."""

    def __init__(self, host: str, port: int, password: str, *, timeout: float = 5.0) -> None:
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._id = 0

    # ------------------------------------------------------------- conexion
    def connect(self) -> None:
        if self._socket is not None:
            return
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise RconError(
                "No se pudo conectar con la consola del servidor. "
                "Comprueba que el servidor esta en ejecucion."
            ) from exc
        sock.settimeout(self.timeout)
        self._socket = sock
        try:
            self._authenticate()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:  # pragma: no cover - cierre defensivo
                pass
            self._socket = None

    def __enter__(self) -> "RconClient":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- protocolo
    def _next_id(self) -> int:
        self._id = (self._id % 2_000_000_000) + 1
        return self._id

    def _send(self, packet_id: int, packet_type: int, body: str) -> None:
        assert self._socket is not None
        payload = struct.pack("<ii", packet_id, packet_type) + body.encode("utf-8") + b"\x00\x00"
        self._socket.sendall(struct.pack("<i", len(payload)) + payload)

    def _recv_exact(self, count: int) -> bytes:
        assert self._socket is not None
        chunks = bytearray()
        while len(chunks) < count:
            chunk = self._socket.recv(count - len(chunks))
            if not chunk:
                raise RconError("La conexion con la consola se cerro inesperadamente.")
            chunks.extend(chunk)
        return bytes(chunks)

    def _receive(self) -> tuple[int, int, str]:
        (length,) = struct.unpack("<i", self._recv_exact(4))
        if length < 10 or length > _MAX_PACKET_SIZE:
            raise RconError("Respuesta RCON con tamano invalido.")
        data = self._recv_exact(length)
        packet_id, packet_type = struct.unpack("<ii", data[:8])
        body = data[8:-2] if length >= 10 else b""
        return packet_id, packet_type, body.decode("utf-8", errors="replace")

    def _authenticate(self) -> None:
        """Autentica la sesion RCON.

        El servidor responde con un paquete cuyo identificador coincide con la
        peticion si la contrasena es correcta, o con ``-1`` si es incorrecta.
        Algunas versiones envian antes un paquete vacio, por eso se leen hasta
        dos respuestas.
        """
        packet_id = self._next_id()
        self._send(packet_id, SERVERDATA_AUTH, self.password)
        assert self._socket is not None
        for _ in range(2):
            try:
                response_id, _, _ = self._receive()
            except (socket.timeout, TimeoutError):
                break
            if response_id == -1:
                raise RconError("Contrasena de consola (RCON) incorrecta.")
            if response_id == packet_id:
                logger.debug("Sesion RCON autenticada en %s:%s", self.host, self.port)
                return
        raise RconError("No se pudo autenticar la consola del servidor (RCON).")

    def command(self, command: str) -> str:
        """Envia un comando y devuelve la respuesta completa."""
        cleaned = validate_console_command(command)
        if self._socket is None:
            self.connect()
        assert self._socket is not None
        packet_id = self._next_id()
        self._send(packet_id, SERVERDATA_EXECCOMMAND, cleaned)

        parts: list[str] = []
        total = 0
        recibidos = 0
        self._socket.settimeout(self.timeout)
        while True:
            try:
                response_id, _, body = self._receive()
            except (socket.timeout, TimeoutError):
                break
            # Se cuentan *todos* los paquetes recibidos, no solo los que encajan
            # con el identificador: un servidor (o un plugin) que responda en
            # bucle con identificadores que no tocan mantendria esto girando
            # para siempre.
            recibidos += 1
            if recibidos > _MAX_RESPONSE_PACKETS:
                raise RconError(
                    "La consola envio demasiados paquetes seguidos; se corta la lectura."
                )
            if response_id == -1:
                raise RconError("La consola rechazo la peticion (autenticacion perdida).")
            if response_id != packet_id:
                continue
            total += len(body)
            if total > _MAX_RESPONSE_SIZE:
                raise RconError(
                    "La respuesta de la consola es demasiado grande y se ha cortado."
                )
            parts.append(body)
            # Tras el primer paquete esperamos poco por si la respuesta viene en varios.
            self._socket.settimeout(0.25)
        return "".join(parts)
