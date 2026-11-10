# Cambios

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
