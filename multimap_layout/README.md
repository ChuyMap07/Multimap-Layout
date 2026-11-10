# Multimap Layout 1.0.1

Pestañas de mapas independientes y de Layout en un mismo proyecto de QGIS, al estilo de ArcGIS Pro.
Compatible con QGIS 3.22 en adelante, incluido QGIS 4 (Qt6). Probado en 3.34 y 4.2.

Instalar: QGIS > Complementos > Instalar desde ZIP > multimap_layout.zip

## Idea general
Cada mapa (pestaña) tiene sus propias capas, su árbol, su CRS, su extensión, su rotación, sus filtros y su simbología.
Los mapas son independientes: **las capas no se comparten**. Las capas de los mapas que no están activos se sacan del registro del
proyecto, de modo que QGIS y los demás complementos solo ven las capas del mapa activo (selectores de capas, Processing,
`QgsProject.mapLayers()`, el árbol y la capa activa). Así los demás complementos funcionan por mapa sin tener que adaptarse.

## Barra de pestañas
- Aspecto de ArcGIS Pro, con la pestaña activa en verde; incluye mapas y Layouts abiertos. Doble clic renombra; arrastra para
  reordenar; la X aparece en la pestaña activa y al pasar el cursor.
- "+" crea un mapa vacío. Los Layouts aparecen como pestaña al crearlos con el botón normal de QGIS.
- Al elegir un Layout, el diseñador se integra en la ventana principal y la barra Multimapa queda en la misma posición que en la
  vista de mapas. Elegir un mapa vuelve al lienzo principal. Cerrar la pestaña usa el aviso normal de QGIS.
- Clic derecho: renombrar y cerrar; en mapas también duplicar y mover a otra pantalla. Se pueden arrastrar pestañas fuera de la
  barra para abrir mapas en ventana propia o mover Layouts a otro monitor.
- Las ventanas flotantes de mapa tienen árbol de capas, navegación, identificación y escala.

## Mapas y capas
- **Duplicar mapa / Copiar capa:** cada capa se copia de forma independiente: capas temporales (con sus datos), filtros, uniones,
  capas virtuales y estilo. Panel de Capas, clic derecho > Multimapa: Copiar / Mover a otro mapa.
- **Por mapa:** CRS (el CRS del proyecto sigue al de la pestaña activa), extensión, rotación, capa activa, estructura del árbol
  (grupos, orden, visibilidad, expandido, grupos exclusivos y propiedades de los nodos). La selección de entidades es de cada capa y,
  como las capas no se comparten, también queda por mapa.
- **Capas en edición:** al cambiar de mapa con capas en edición, sin cambios pendientes solo se termina la edición; con cambios
  aparece Guardar / Descartar / Cancelar.
- El cambio de pestaña congela el lienzo mientras se intercambian las capas para evitar parpadeos.

## Layouts
- En "Añadir elemento > Añadir Mapa" elige un mapa en el menú; el elemento queda enlazado a él con sus capas y CRS. Las leyendas
  nuevas siguen al mapa de su elemento de referencia. "Sin enlazar" conserva el comportamiento normal de QGIS.
- Los elementos enlazados se actualizan solos cuando cambia la composición de capas de su mapa. La extensión del marco queda libre.
- Complementos > Multimap Layout > Crear layout con todos los mapas; Layout > Asignar mapa… para reasignar.

## Archivos de proyecto
Al guardar, el complemento convierte el proyecto a un **formato portable**: las capas de los demás mapas quedan como capas normales
dentro de grupos desmarcados «Mapa N (Multimap)». Cualquier QGIS, con o sin el complemento, abre el proyecto completo y puede
volver a guardarlo sin perder nada. Con el complemento, esos grupos se reconocen y cada mapa se reconstruye.
- Si el archivo no se puede convertir (base de datos, solo lectura…) queda en un formato propio: solo se ve completo con el complemento.
- Las capas temporales (memoria) de otros mapas no se guardan con el proyecto: se avisa al guardar.
- Los proyectos de la 0.8.x (nodos planos) se migran solos al abrirlos. Al descargar o desinstalar el complemento, las capas
  ocultas vuelven al proyecto en un grupo.

## Limitaciones conocidas
- Orden de renderizado personalizado del proyecto (`customLayerOrder`): es global, no por mapa.
- Proyectos guardados en base de datos o en red permanecen en el formato propio.
- No se ha probado con proyectos muy grandes ni con deshacer/rehacer entre cambios de mapa.
- Interfaz solo en español.
