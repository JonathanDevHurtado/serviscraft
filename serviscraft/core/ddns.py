"""Nombres personalizados para entrar al servidor (DuckDNS).

El problema: para jugar desde otra ciudad hay que dar a los amigos una direccion,
y una direccion numerica (``83.54.12.7:25565``) es fea, cambia sola cuando el
operador la renueva y revela donde vives.

La solucion: un **nombre** (``reinotrebol.duckdns.org:25565``) que apunta a tu IP
publica. El nombre lo resuelve internet (DNS) y DuckDNS, un servicio gratuito,
se encarga de mantener ese nombre apuntando a la IP que tengas en cada momento.
La aplicacion solo habla con DuckDNS cuando el usuario lo pide o cuando el
servidor arranca con la actualizacion automatica activada.

Aviso honesto que hay que tener presente: un nombre no abre puertas. Si el router
no reenvia el puerto del juego, el nombre resuelve pero nadie entra. Tampoco se
puede esconder el puerto sin un dominio propio con un registro SRV: DuckDNS solo
publica la direccion (registro ``A``/``AAAA``), asi que el puerto se sigue
escribiendo. Serviscraft lo explica en la pestana «Unirse».

El token de DuckDNS es una contrasena: se guarda con los demas datos privados del
servidor, **nunca** se registra en el log (el registro depura ``token=...``) y no
se muestra en la interfaz una vez guardado.
"""

from __future__ import annotations

import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .errors import DdnsError, ValidationError
from .logging_setup import get_logger

logger = get_logger("ddns")

#: Dominio que regala DuckDNS: el nombre completo es ``<subdominio>.duckdns.org``.
DUCKDNS_DOMAIN = "duckdns.org"

#: Direccion de actualizacion de DuckDNS (protocolo documentado por ellos).
UPDATE_URL = "https://www.duckdns.org/update"

#: Etiqueta DNS valida: minusculas, numeros y guiones, sin empezar ni acabar en
#: guion. Es mas estricta que la de DuckDNS a proposito.
_SUBDOMINIO = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
#: Los tokens de DuckDNS son identificadores tipo UUID (letras, numeros y guiones).
_TOKEN = re.compile(r"^[A-Za-z0-9-]{8,64}$")

_TIEMPO_ESPERA = 10


# ------------------------------------------------------------------ validacion
def validate_subdomain(value: str) -> str:
    """Valida y normaliza el subdominio elegido (``ReinoTrebol`` → ``reinotrebol``)."""
    limpio = str(value or "").strip().lower()
    if not limpio:
        raise ValidationError("ddns", "Escribe el nombre que quieras usar.")
    # Se admite escribir el nombre completo y quedarse solo con la etiqueta.
    if limpio.endswith("." + DUCKDNS_DOMAIN):
        limpio = limpio[: -len(DUCKDNS_DOMAIN) - 1]
    if limpio.endswith(DUCKDNS_DOMAIN) and "." not in limpio[: -len(DUCKDNS_DOMAIN)]:
        limpio = limpio[: -len(DUCKDNS_DOMAIN)].rstrip(".")
    if not _SUBDOMINIO.match(limpio):
        raise ValidationError(
            "ddns",
            "El nombre solo puede tener letras, numeros y guiones (sin espacios ni "
            "acentos), y no puede empezar ni acabar en guion.",
        )
    return limpio


def validate_token(value: str, *, obligatorio: bool = False) -> str:
    """Valida el token de DuckDNS (una contrasena)."""
    limpio = str(value or "").strip()
    if not limpio:
        if obligatorio:
            raise ValidationError(
                "ddns", "Falta el token de DuckDNS: sin el no se puede actualizar la direccion."
            )
        return ""
    if not _TOKEN.match(limpio):
        raise ValidationError(
            "ddns",
            "El token de DuckDNS no tiene el formato esperado (letras, numeros y guiones).",
        )
    return limpio


def mdns_hostname(nombre: str) -> str:
    """Nombre para la red local (mDNS): ``mundo`` → ``mundo.local``.

    Se genera a partir del nombre del servidor, quitando acentos y simbolos, para
    que los equipos de casa puedan entrar sin mirar la IP.
    """
    base = str(nombre or "").strip().lower()
    import unicodedata

    base = unicodedata.normalize("NFKD", base)
    base = "".join(ch for ch in base if not unicodedata.combining(ch))
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    base = base[:63].strip("-")
    return f"{base or 'serviscraft'}.local"


def hostname(subdomain: str) -> str:
    """Nombre completo que se escribe en Minecraft."""
    limpio = validate_subdomain(subdomain)
    return f"{limpio}.{DUCKDNS_DOMAIN}"


# ------------------------------------------------------------------ consultas
def resolve(name: str, *, timeout: float = 5.0) -> set[str]:
    """Direcciones a las que apunta un nombre (conjunto vacio si no resuelve)."""
    limpio = str(name or "").strip()
    if not limpio:
        return set()
    anterior = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        infos = socket.getaddrinfo(limpio, None)
        return {info[4][0] for info in infos}
    except (OSError, UnicodeError):
        return set()
    finally:
        socket.setdefaulttimeout(anterior)


@dataclass
class DdnsStatus:
    """Resultado de comprobar el nombre: lo que la interfaz enseña."""

    subdomain: str = ""
    hostname: str = ""
    addresses: set[str] = field(default_factory=set)
    public_ip: str = ""
    state: str = "sin-configurar"  # ok | otra-ip | sin-resolver | sin-ip | sin-configurar
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    @property
    def direccion(self) -> str:
        """Direccion que se copia en Minecraft (sin puerto: lo añade quien la use)."""
        return self.hostname


def check(subdomain: str, *, public_ip: str = "", puerto: int | None = None) -> DdnsStatus:
    """Comprueba si el nombre existe y si apunta a la IP publica actual.

    ``public_ip`` es opcional: si no se conoce, la comprobacion dice solo si el
    nombre resuelve (sin prometer que la direccion sea la correcta).
    """
    if not str(subdomain or "").strip():
        return DdnsStatus(
            state="sin-configurar",
            detail=(
                "Aun no hay un nombre: se entra con la IP publica y el puerto. "
                "Configura uno para no tener que dar tu IP."
            ),
        )
    try:
        nombre = hostname(subdomain)
    except ValidationError as exc:
        return DdnsStatus(state="sin-configurar", detail=str(exc))

    estado = DdnsStatus(subdomain=subdomain, hostname=nombre, public_ip=public_ip)
    direcciones = resolve(nombre)
    estado.addresses = direcciones
    etiqueta = f"{nombre}:{puerto}" if puerto else nombre
    if not direcciones:
        estado.state = "sin-resolver"
        estado.detail = (
            f"El nombre {nombre} no responde todavia. Si acabas de crearlo, espera "
            "unos minutos; si no, revisa el subdominio y el token."
        )
        return estado
    if not public_ip:
        estado.state = "sin-ip"
        estado.detail = (
            f"{nombre} resuelve a {', '.join(sorted(direcciones))}. Pulsa «Consultar mi "
            f"IP publica» para comprobar que es la de este equipo antes de compartir {etiqueta}."
        )
        return estado
    if public_ip in direcciones:
        estado.state = "ok"
        estado.detail = (
            f"Listo: {etiqueta} apunta a este equipo. Ya se puede compartir esa "
            "direccion (el puerto tiene que estar abierto en el router)."
        )
        return estado
    estado.state = "otra-ip"
    estado.detail = (
        f"{nombre} apunta a {', '.join(sorted(direcciones))}, pero tu IP publica ahora "
        f"es {public_ip}. Pulsa «Actualizar» para corregirlo."
    )
    return estado


# ------------------------------------------------------------------ actualizar
def update(subdomain: str, token: str, *, ip: str = "", timeout: int = _TIEMPO_ESPERA) -> str:
    """Pide a DuckDNS que apunte el nombre a ``ip`` (o a la IP de salida).

    Devuelve la respuesta de DuckDNS (``OK`` si todo fue bien) y lanza
    ``DdnsError`` con un mensaje en español si no se pudo. El token viaja en la
    direccion, asi que **nunca** se registra ni se muestra.
    """
    limpio = validate_subdomain(subdomain)
    clave = validate_token(token, obligatorio=True)
    parametros = {"domains": limpio, "token": clave, "ip": str(ip or "").strip()}
    consulta = urllib.parse.urlencode(parametros)
    peticion = urllib.request.Request(
        f"{UPDATE_URL}?{consulta}",
        headers={"User-Agent": "Serviscraft"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:  # noqa: S310 - direccion fija https
            texto = respuesta.read(64).decode("utf-8", "replace").strip()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # Se registra sin la direccion: lleva el token dentro.
        logger.warning("No se pudo actualizar DuckDNS de %s: %s", limpio, exc)
        raise DdnsError(
            "No se pudo contactar con DuckDNS. Comprueba que hay conexion a internet."
        ) from exc
    if texto.upper().startswith("OK"):
        logger.info("DuckDNS actualizado: %s.%s → %s", limpio, DUCKDNS_DOMAIN, ip or "(IP de salida)")
        return "OK"
    logger.warning("DuckDNS rechazo la actualizacion de %s (respuesta: %s)", limpio, texto[:20])
    raise DdnsError(
        "DuckDNS no acepto la actualizacion. Revisa que el nombre y el token sean los "
        "de tu cuenta (el token esta en www.duckdns.org)."
    )


def needs_update(*, last_ip: str, current_ip: str) -> bool:
    """True si la direccion ha cambiado (y por tanto hay que avisar a DuckDNS)."""
    actual = str(current_ip or "").strip()
    anterior = str(last_ip or "").strip()
    if not actual:
        return False
    return actual != anterior


__all__ = [
    "DUCKDNS_DOMAIN",
    "UPDATE_URL",
    "DdnsStatus",
    "check",
    "hostname",
    "mdns_hostname",
    "needs_update",
    "resolve",
    "update",
    "validate_subdomain",
    "validate_token",
]
