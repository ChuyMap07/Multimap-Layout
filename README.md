# Multimap Layout para QGIS

Pestañas de mapas independientes y de Layout en un mismo proyecto de QGIS, al estilo de ArcGIS Pro.
Autor: Jesús Mora.

## ⬇️ Descarga rápida

**[Descargar multimap_layout.zip](https://github.com/ChuyMap07/Multimap-Layout/raw/main/multimap_layout.zip)**

Instalación: QGIS → *Complementos* → *Administrar e instalar complementos* → *Instalar a partir de ZIP* → elige
`multimap_layout.zip` → *Instalar complemento*.

> No uses el botón verde *Code → Download ZIP* de GitHub para instalar: ese archivo trae todo el repositorio y QGIS no lo
> reconoce como complemento. Usa el enlace de arriba.

## Qué hace
- **Pestañas de mapas independientes:** cada mapa tiene sus propias capas, CRS, extensión, filtros, simbología y orden de
  capas. Los demás complementos (Processing, selectores de capas, etc.) trabajan solo con el mapa activo.
- **Pestañas de Layout** integradas en la ventana de QGIS, en el mismo lugar que las de mapas, con herramientas de
  **plantillas** (guardar, nueva, aplicar) disponibles en todos los proyectos.
- **Catálogo** con todos los mapas y Layouts del proyecto; cerrar una pestaña no borra el mapa.
- **Lado a lado** y **navegación enlazada** entre mapas; mapas en ventana propia u otro monitor.
- **Proyecto portable:** el archivo se abre completo incluso en un QGIS sin el complemento.

Requiere QGIS 3.22 o posterior (incluido QGIS 4). Guía completa: [multimap_layout/README.md](multimap_layout/README.md) ·
Cambios: [CHANGELOG](multimap_layout/CHANGELOG.md)

## Reportar errores
Abre un *Issue* en https://github.com/ChuyMap07/Multimap-Layout/issues con la versión de QGIS, el sistema operativo y, si
aparece, el texto del panel *Registro de mensajes → Multimap Layout*.

## Para desarrolladores
- `multimap_layout/`: el complemento.
- `tests/run_qgis_tests.sh`: pruebas de integración dentro de QGIS (requiere `qgis`, `python3-qgis` y `xvfb`).
- `build_zip.sh`: vuelve a generar `multimap_layout.zip` después de cambiar el código.
