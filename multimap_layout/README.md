# Multimap Layout 1.4.0

Pestañas de mapas independientes y de Layout en un mismo proyecto de QGIS, al estilo de ArcGIS Pro.
Compatible con QGIS 3.22 en adelante, incluido QGIS 4 (Qt6). Pruebas automáticas en QGIS 3.34 (ver `tests/`).

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
- Al elegir un Layout, el diseñador se integra en la ventana principal y las pestañas quedan **en el mismo lugar** que en la
  vista de mapas. El espacio a su izquierda lo ocupan las herramientas de plantillas (Guardar / Nueva / Aplicar). Elegir un mapa
  vuelve al lienzo principal.
- Botones a la derecha de la barra: **Lado a lado** (elige qué mapa ver junto al lienzo), **Enlazar** (navegación enlazada) y
  **Catálogo** (muestra u oculta el panel). El Catálogo también está en la barra de Complementos y en el menú del complemento.
- Clic derecho: renombrar y cerrar; en mapas también duplicar, abrir al lado y abrir en otra pantalla. Se pueden arrastrar
  pestañas fuera de la barra para abrir mapas en ventana propia o mover Layouts a otro monitor.
- **Enlazar**: navegación enlazada entre el lienzo principal, las vistas lado a lado y las ventanas: *Sin enlazar*, *Enlazar
  centro* o *Enlazar centro y escala*. El centro se transforma entre los CRS de cada mapa.

## Vistas lado a lado
- Botón **Lado a lado** de la barra (o pestaña / Catálogo > clic derecho > **Abrir al lado**): el mapa se acopla a la derecha del lienzo principal, dentro de la
  ventana de QGIS. Se pueden acoplar varios (se apilan) y ajustar el tamaño con los divisores.
- Cada vista acoplada tiene navegación, extensión completa / anterior / siguiente, identificar, medir, escala y coordenadas.
- **Activar** en su cabecera intercambia: ese mapa pasa al lienzo principal (con todas las herramientas de QGIS y edición) y el
  mapa que estaba activo ocupa su lugar en la vista acoplada. **↗** la pasa a ventana propia; **✕** cierra la vista.
- Las vistas acopladas y el modo de enlace se guardan con el proyecto.
- Las ventanas propias tienen además el árbol de capas del mapa (orden, grupos, visibilidad) y los botones *Activar en el lienzo
  principal* y *Acoplar al lado*.

## Catálogo
- Panel con todos los mapas y Layouts del proyecto (el activo en negrita, los cerrados en cursiva).
- Doble clic o Enter abre; clic derecho: Abrir, Cerrar vista, Renombrar (F2), Duplicar, Eliminar (Supr), Nuevo mapa, Nuevo Layout.
- Cerrar una pestaña solo cierra la vista (como en ArcGIS Pro). Para borrar un mapa o Layout se usa Eliminar en el Catálogo.
- Debe quedar al menos un mapa abierto (el lienzo principal siempre muestra uno).

## Mapas y capas
- **Duplicar mapa / Copiar capa:** cada capa se copia de forma independiente: capas temporales (con sus datos), filtros, uniones,
  capas virtuales y estilo. Panel de Capas, clic derecho > Multimapa: Copiar / Mover a otro mapa.
- **Por mapa:** CRS (el CRS del proyecto sigue al de la pestaña activa), extensión, rotación, capa activa, estructura del árbol
  (grupos, orden, visibilidad, expandido, grupos exclusivos y propiedades de los nodos) y el orden de renderizado personalizado
  (panel Orden de capas). La selección de entidades es de cada capa y,
  como las capas no se comparten, también queda por mapa.
- **Capas en edición:** al cambiar de mapa con capas en edición, sin cambios pendientes solo se termina la edición; con cambios
  aparece Guardar / Descartar / Cancelar.
- El cambio de pestaña congela el lienzo mientras se intercambian las capas para evitar parpadeos.

## Layouts
- En "Añadir elemento > Añadir Mapa" elige un mapa en el menú; el elemento queda enlazado a él con sus capas y CRS. Las leyendas
  nuevas siguen al mapa de su elemento de referencia. "Sin enlazar" conserva el comportamiento normal de QGIS.
- Los elementos enlazados se actualizan solos cuando cambia la composición de capas de su mapa. La extensión del marco queda libre.
- Complementos > Multimap Layout > Crear layout con todos los mapas; Layout > Asignar mapa… para reasignar.
- **Plantillas** (a la izquierda de las pestañas en la vista de Layout, y en el Catálogo > Layouts): guardar el Layout como plantilla,
  crear un Layout desde una plantilla y reemplazar el contenido del Layout con una plantilla. Las plantillas se guardan
  siempre en la carpeta general de QGIS (perfil > composer_templates), así que están disponibles en **cualquier proyecto** (y en
  el Administrador de diseños de QGIS). También se leen las rutas de búsqueda de plantillas configuradas en QGIS. Los elementos
  que venían enlazados a mapas de otro proyecto se sueltan y el complemento ofrece enlazarlos a los mapas de este.

## Archivos de proyecto
Al guardar, el complemento convierte el proyecto a un **formato portable**: las capas de los demás mapas quedan como capas normales
dentro de grupos desmarcados «Mapa N (Multimap)». Cualquier QGIS, con o sin el complemento, abre el proyecto completo y puede
volver a guardarlo sin perder nada. Con el complemento, esos grupos se reconocen y cada mapa se reconstruye.
- Si el archivo no se puede convertir (base de datos, solo lectura…) queda en un formato propio: solo se ve completo con el complemento.
- Las capas temporales (memoria) de otros mapas no se guardan con el proyecto: se avisa al guardar.
- Los proyectos de la 0.8.x (nodos planos) se migran solos al abrirlos. Al descargar o desinstalar el complemento, las capas
  ocultas vuelven al proyecto en un grupo.

## Compatibilidad con otros complementos y funciones de QGIS
Al cambiar de pestaña, las capas del mapa que deja de estar activo **salen del registro del proyecto** (QGIS emite
`layersWillBeRemoved` / `layersRemoved`) y las del mapa nuevo **entran** (`layersAdded`). Por eso los demás complementos (Processing,
selectores de capas, paneles…) trabajan solo con el mapa activo sin adaptarse. Verificado en QGIS 3.34:
- Processing: los resultados se agregan al mapa activo y se quedan en él.
- Selectores de capas (`QgsMapLayerComboBox`), panel de capas y capa activa: solo el mapa activo.
- Selección de entidades, edición pendiente (Guardar / Descartar / Cancelar), CRS y orden de capas: por mapa.
- **Relaciones** entre capas y **temas de mapa**: QGIS los borra al sacar capas del registro; el complemento los conserva mientras
  el mapa está inactivo y los repone al volver, también al guardar y abrir (y el archivo portable los trae completos).
- Ajuste (snapping) por capa, tablas de atributos abiertas: se conservan.
Consecuencia a tener en cuenta: un complemento que guarda estado propio por capa lo verá como capa quitada y vuelta a agregar al
cambiar de pestaña.

## Limitaciones conocidas
- Las vistas acopladas y las ventanas solo navegan, identifican y miden; para editar o usar otras herramientas de QGIS se pulsa
  *Activar* (el lienzo principal es el único conectado a todas las herramientas de QGIS).
- Un mapa solo puede estar en una vista secundaria a la vez (acoplada o en ventana).
- Proyectos guardados en base de datos o en red permanecen en el formato propio.
- No se ha probado con proyectos muy grandes ni con deshacer/rehacer entre cambios de mapa.
- En proyectos guardados en el formato propio (no portable), los temas de mapa pierden las capas de los mapas inactivos al abrir.
- Interfaz solo en español.
