# Serviscraft — tareas de desarrollo, pruebas y empaquetado.
#
# Uso rapido:
#     make            # ayuda
#     make venv       # crea el entorno virtual de desarrollo
#     make run        # inicia la aplicacion desde el codigo fuente
#     make test       # todas las pruebas
#     make packages   # rpm + deb + AppImage en dist/

SHELL := /bin/bash
PYTHON ?= python3
VENV   := .venv
V      := $(VENV)/bin
SRC    := serviscraft
TESTS  := tests

.PHONY: help venv run debug self-test test test-gui lint format install-user uninstall-user \
        desktop rpm deb appimage packages clean distclean

help: ## Muestra esta ayuda
	@echo "Serviscraft — objetivo                     descripcion"
	@echo "---------------------------------------------------------------"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-22s %s\n", $$1, $$2}'

$(V)/python:
	@echo "==> Creando el entorno virtual en $(VENV)"
	$(PYTHON) -m venv --system-site-packages $(VENV)
	$(V)/python -m pip install --upgrade pip >/dev/null
	$(V)/python -m pip install "pytest>=7" "pytest-qt>=4.2" >/dev/null
	@echo "==> Listo. Prueba 'make run'."

venv: $(V)/python ## Crea el entorno virtual de desarrollo

run: ## Inicia la aplicacion desde el codigo fuente
	$(V)/python -m serviscraft

debug: ## Inicia la aplicacion con registro detallado
	$(V)/python -m serviscraft --debug

self-test: ## Comprueba las dependencias (Python, PySide6, Podman)
	$(V)/python -m serviscraft --self-test

test: ## Ejecuta todas las pruebas
	$(V)/python -m pytest -q

test-gui: ## Ejecuta solo las pruebas de la interfaz
	$(V)/python -m pytest -q -m gui

lint: ## Analiza el codigo con ruff (si esta instalado)
	@command -v ruff >/dev/null 2>&1 && ruff check $(SRC) $(TESTS) || \
		echo "aviso: ruff no esta instalado (sudo dnf install ruff)"

format: ## Formatea el codigo con ruff (si esta instalado)
	@command -v ruff >/dev/null 2>&1 && ruff format $(SRC) $(TESTS) || \
		echo "aviso: ruff no esta instalado"

install-user: ## Instala el lanzador y el .desktop en ~/.local (sin root)
	@echo "==> Instalando en ~/.local"
	install -d $(HOME)/.local/bin
	install -d $(HOME)/.local/share/applications
	install -d $(HOME)/.local/share/icons/hicolor/scalable/apps
	printf '%s\n' '#!/bin/sh' \
		'# Lanzador de la instalacion de usuario: usa el codigo de este proyecto.' \
		'AQUI="$(CURDIR)"' \
		'PYTHONPATH="$$AQUI"' \
		'export PYTHONPATH' \
		'exec "$$AQUI/$(V)/python" -s -m serviscraft "$$@"' \
		> $(HOME)/.local/bin/serviscraft
	chmod 0755 $(HOME)/.local/bin/serviscraft
	install -pm0644 packaging/serviscraft.desktop $(HOME)/.local/share/applications/serviscraft.desktop
	install -pm0644 $(SRC)/resources/icons/serviscraft.svg \
		$(HOME)/.local/share/icons/hicolor/scalable/apps/serviscraft.svg
	-update-desktop-database $(HOME)/.local/share/applications 2>/dev/null || true
	@echo "==> Hecho. Asegurate de que ~/.local/bin esta en tu PATH."

uninstall-user: ## Quita la instalacion de usuario
	rm -f $(HOME)/.local/bin/serviscraft
	rm -f $(HOME)/.local/share/applications/serviscraft.desktop
	rm -f $(HOME)/.local/share/icons/hicolor/scalable/apps/serviscraft.svg
	-update-desktop-database $(HOME)/.local/share/applications 2>/dev/null || true

desktop: ## Valida el fichero .desktop
	desktop-file-validate packaging/serviscraft.desktop

rpm: ## Construye el paquete RPM
	packaging/build-rpm.sh

deb: ## Construye el paquete .deb
	packaging/build-deb.sh

appimage: ## Construye el AppImage
	packaging/build-appimage.sh

packages: rpm deb appimage ## Construye los tres paquetes

clean: ## Borra el trabajo intermedio de empaquetado
	rm -rf packaging/build
	rm -rf $(SRC)/__pycache__ $(SRC)/core/__pycache__ $(SRC)/ui/__pycache__
	rm -rf $(TESTS)/__pycache__ .pytest_cache

distclean: clean ## Borra tambien dist/ y el entorno virtual
	rm -rf dist $(VENV)
