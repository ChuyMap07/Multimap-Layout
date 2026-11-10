#!/usr/bin/env bash
# Pruebas de integracion dentro de QGIS completo (con iface real) en una pantalla virtual.
# Requisitos: qgis, python3-qgis y xvfb (Ubuntu: apt install qgis python3-qgis xvfb).
# Uso: tests/run_qgis_tests.sh        Resultado: lineas OK/FAIL por prueba; sale con 1 si hay fallos.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
PLUG="$TMP/profiles/profiles/default/python/plugins"
mkdir -p "$PLUG" "$TMP/work"
ln -s "$HERE/../multimap_layout" "$PLUG/multimap_layout"
status=0
for t in test_general test_compat test_edge; do
  echo "== $t"
  MM_OUT="$TMP/$t.txt" MM_WORK="$TMP/work" timeout 300 xvfb-run -a -s "-screen 0 1600x1000x24" \
    qgis --profiles-path "$TMP/profiles" --nologo --noversioncheck --code "$HERE/$t.py" > "$TMP/$t.log" 2>&1
  cat "$TMP/$t.txt"
  grep -q "^FAIL\|^EXC\|^PYTHON" "$TMP/$t.txt" && status=1
done
echo "registros en $TMP"
exit $status
