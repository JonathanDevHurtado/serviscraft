# Seguridad

## Versiones con soporte

| Versión | Soporte |
| --- | --- |
| 0.8.x | Sí |
| 0.7.x y anteriores | No (actualiza a la última) |

## Cómo informar de una vulnerabilidad

**No abras un issue público** con los detalles. Usa la pestaña **Security →
Advisories → Report a vulnerability** del repositorio de GitHub:

<https://github.com/JonathanDevHurtado/serviscraft/security/advisories/new>

Si no puedes usar esa vía, escribe a **JonathanHurtadoDev@proton.me** o abre un
issue **sin detalles sensibles** pidiendo contacto privado.

Incluye, si puedes:

- Versión de Serviscraft (`serviscraft --self-test`).
- Distribución y versión de Podman y PySide6.
- Pasos para reproducirlo.
- Impacto que crees que tiene.
- Una prueba de concepto, si la tienes.

## Qué se considera una vulnerabilidad

- Ejecución de comandos o escape del contenedor.
- Lectura o escritura de ficheros fuera de la carpeta del servidor.
- SSRF, redirecciones o descargas que salten las reglas de `core/textures.py`.
- Exposición de la contraseña de RCON o de tokens de DuckDNS.
- Saltarse la confirmación de una acción destructiva.
- Escalada de privilegios o uso de `sudo` por accidente.

No se consideran vulnerabilidades:

- Que un servidor de Minecraft sea accesible desde Internet si el usuario abrió
  el puerto a propósito.
- Los fallos de seguridad **del juego** o de un mod/plugin concreto.
- La falta de una función que no está documentada.

## Alcance

Serviscraft es una aplicación de escritorio que ejecuta Podman **rootless** con
el usuario que la abre. No hay servidor web, no hay API de red y no se expone el
socket de Podman por TCP. El modelo completo está en
[`docs/seguridad.md`](docs/seguridad.md).

## Divulgación

Se intentará confirmar el informe en un plazo razonable, preparar un arreglo y
publicar un aviso. No se promete recompensa económica. Se dará crédito a quien
informe si lo desea.
