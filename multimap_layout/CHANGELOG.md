# Cambios

## 1.4.0
- Vista de Layout: las pestañas quedan en el **mismo lugar** que en la vista de mapas (se realinean si cambia el ancho de los
  paneles). El espacio de la izquierda lo ocupan las herramientas de plantillas: Guardar, Nueva y Aplicar.
- Botones visibles en la barra: **Lado a lado** (ver otro mapa junto al lienzo), **Enlazar** y **Catálogo**. El Catálogo
  también se puede abrir desde la barra de Complementos.
- Pruebas de interfaz (posición de pestañas, botones) en `tests/test_ui.py`.

## 1.3.2
- Corrige pérdida de datos: las **relaciones** entre capas y las capas de los **temas de mapa** se borraban al cambiar de pestaña
  (QGIS las elimina al sacar capas del registro). Ahora se conservan y se reponen, también al guardar y abrir el proyecto.
- Corrige: al abrir un proyecto normal de QGIS (sin datos del complemento) o recargar el complemento no se creaba «Mapa 1»
  (sin pestaña de mapa ni Catálogo).
- Pruebas de integración en QGIS real (`tests/run_qgis_tests.sh`).

## 1.3.1
- «Guardar como plantilla» pide solo el nombre y guarda siempre en la carpeta general de plantillas de QGIS: la plantilla queda
  disponible en cualquier proyecto (avisa antes de reemplazar una existente). Ya no se leen plantillas de la carpeta del proyecto.

## 1.3.0
- Botón **Plantillas** en la barra de pestañas del Layout (y en el Catálogo): guardar como plantilla, nuevo Layout desde
  plantilla, reemplazar con plantilla y abrir la carpeta de plantillas. Comparte la carpeta con el Administrador de diseños de QGIS.

## 1.2.0
- **Vistas lado a lado:** «Abrir al lado» acopla un mapa a la derecha del lienzo principal dentro de la ventana de QGIS;
  «Activar» intercambia esa vista con el lienzo principal. Se guardan con el proyecto.
- **Navegación enlazada** (botón 🔗 en la barra): centro, o centro y escala, entre todas las vistas, con transformación de CRS.
- Vistas secundarias más completas: iconos de QGIS, extensión completa / anterior / siguiente, identificar en todas las capas
  visibles (resultados en árbol), medir distancias, escala y coordenadas. La ventana propia permite reordenar el árbol de capas.
- Vista de Layout: las pestañas quedan pegadas encima de la hoja del Layout (mismo concepto que en mapas). Se eliminan los ajustes
  por píxeles que intentaban alinear la barra con la de mapas.
- Orden de renderizado personalizado (panel Orden de capas) por mapa, también al duplicar.

## 1.1.0
- Panel **Catálogo** (como en ArcGIS Pro): lista todos los mapas y Layouts del proyecto, abiertos o no. Doble clic abre;
  clic derecho: Abrir, Cerrar vista, Renombrar (F2), Duplicar, Eliminar (Supr), Nuevo mapa / Nuevo Layout. Sigue visible
  en la vista de Layout. Se muestra/oculta desde Complementos > Multimap Layout > Catálogo de mapas y Layouts.
- Cerrar la pestaña de un mapa ya **no lo borra**: solo cierra su vista; el mapa, sus capas y su extensión siguen en el
  proyecto y se reabren desde el Catálogo. Eliminar un mapa se hace desde el Catálogo, con confirmación.
- Al abrir un proyecto solo se reabren los Layouts que estaban abiertos al guardar; los demás quedan en el Catálogo.

## 1.0.1
- Corrige la barra de pestañas de Layout que aparecía sobre el menú (Proyecto/Edición) al abrir QGIS con el complemento ya activo.
- El widget central original de QGIS se retira con takeCentralWidget (Qt ya no puede borrarlo) y se restaura bien al descargar el complemento.

## 1.0.0
- Aislamiento de capas por mapa: las capas de los mapas inactivos salen del registro del proyecto.
- Formato de proyecto portable (legible con o sin el complemento) y migración automática desde 0.8.x.
- Política de capas en edición al cambiar de mapa; aviso de capas temporales al guardar.
- Layouts: corrige la barra que se perdía o quedaba suelta al borrar un layout y crear otro; la barra de layout se alinea con la de mapas.
- Cada mapa conserva también la rotación, los grupos exclusivos, las propiedades de los nodos y el estado expandido de capas y grupos.
- El lienzo se congela durante el cambio de pestaña. Se limpia el estado interno de los layouts al cerrarlos.
- Probado en QGIS 3.34 y 4.2 (sin pantalla).

## 0.8.x
- Pestañas de Layout, ventanas flotantes, CRS por mapa, enlace de elementos de Layout, duplicado de mapas con capas temporales, uniones y filtros.
