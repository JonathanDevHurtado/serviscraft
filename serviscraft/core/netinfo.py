"""Direcciones de red para explicar como se conectan los jugadores.

Todo esto es opcional: si no hay red, se devuelve una cadena vacia y la interfaz
simplemente no muestra el dato. La IP publica se consulta solo cuando el usuario
pulsa el boton (una peticion HTTP a un servicio conocido, sin enviar nada mas).
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from .logging_setup import get_logger

logger = get_logger("netinfo")

#: Servicios que devuelven la IP publica en texto plano (se prueban en orden).
PUBLIC_IP_URLS: tuple[str, ...] = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
)
_TIMEOUT = 8


def local_ipv4() -> str:
    """IP del equipo en la red local (``""`` si no se puede deducir).

    No se envia ningun paquete: solo se pregunta al sistema que interfaz usaria
    para salir a la red.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            direccion = str(sock.getsockname()[0])
    except OSError:
        return ""
    return "" if direccion.startswith("127.") else direccion


def public_ip(*, timeout: int = _TIMEOUT) -> str:
    """IP publica del equipo, segun un servicio externo (``""`` si falla).

    Solo se llama cuando el usuario lo pide expresamente desde la pestana
    «Unirse»: es la unica peticion que hace la aplicacion fuera de Modrinth y de
    las descargas de Minecraft.
    """
    for url in PUBLIC_IP_URLS:
        try:
            peticion = urllib.request.Request(
                url, headers={"User-Agent": "Serviscraft"}
            )
            with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
                texto = respuesta.read(200).decode("utf-8", "replace").strip()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.debug("No se pudo consultar la IP publica en %s: %s", url, exc)
            continue
        # Algunos servicios responden JSON: se acepta cualquiera de los dos.
        if texto.startswith("{"):
            try:
                texto = str(json.loads(texto).get("ip", "")).strip()
            except (ValueError, AttributeError):
                texto = ""
        if texto and len(texto) <= 45 and " " not in texto:
            return texto
    return ""


__all__ = ["PUBLIC_IP_URLS", "local_ipv4", "public_ip"]
