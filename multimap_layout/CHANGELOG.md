# Cambios

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
