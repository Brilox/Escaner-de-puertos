#!/usr/bin/env bash
# Nombre antiguo del instalador: ahora todo esta en instalar_vps.sh (Vultr u otro VPS con Ubuntu). Ver GUIA_VULTR.md.
exec bash "$(dirname "$0")/instalar_vps.sh" "$@"
