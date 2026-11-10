#!/usr/bin/env bash
# Genera multimap_layout.zip (el que se instala en QGIS) en la raiz del repositorio.
set -e
cd "$(dirname "$0")"
rm -f multimap_layout.zip
find multimap_layout -name __pycache__ -prune -exec rm -rf {} +
zip -qr multimap_layout.zip multimap_layout -x '*__pycache__*' '*.pyc'
echo "multimap_layout.zip listo ($(grep '^version=' multimap_layout/metadata.txt))"
