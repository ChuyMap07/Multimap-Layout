# -*- coding: utf-8 -*-
"""Panel Catalogo (al estilo de ArcGIS Pro): lista TODOS los mapas y Layouts del proyecto,
esten abiertos como pestaña o no. Cerrar una pestaña solo cierra la vista; el mapa o el
Layout siguen aqui y se vuelven a abrir con doble clic. Eliminar se hace desde este panel."""
import os

from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QDockWidget, QMenu, QTreeWidget, QTreeWidgetItem

from .common import qenum

_ROLE = qenum(Qt, "ItemDataRole", "UserRole")
_KEY_DEL = qenum(Qt, "Key", "Key_Delete")
_KEY_F2 = qenum(Qt, "Key", "Key_F2")
_KEY_ENTER = (qenum(Qt, "Key", "Key_Return"), qenum(Qt, "Key", "Key_Enter"))


def _icon(name):
    return QIcon(os.path.join(os.path.dirname(__file__), name))


class _Tree(QTreeWidget):
    def __init__(self, dock):
        super().__init__(dock)
        self.dock = dock

    def keyPressEvent(self, event):
        key = self.dock.current_key()
        if key:
            if event.key() == _KEY_DEL:
                self.dock.plugin.catalog_delete(key)
                return
            if event.key() == _KEY_F2:
                self.dock.plugin.catalog_rename(key)
                return
            if event.key() in _KEY_ENTER:
                self.dock.plugin.catalog_open(key)
                return
        super().keyPressEvent(event)


class CatalogDock(QDockWidget):
    """Arbol con dos carpetas: Mapas y Layouts. Cada elemento lleva su clave de vista
    ("map:<id>" o "layout:<nombre>"); las acciones se delegan en el complemento."""

    def __init__(self, plugin, parent=None):
        super().__init__("Catálogo", parent)
        self.plugin = plugin
        self.setObjectName("MultiMapCatalogDock")
        self.tree = _Tree(self)
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setContextMenuPolicy(qenum(Qt, "ContextMenuPolicy", "CustomContextMenu"))
        self.tree.customContextMenuRequested.connect(self._on_context)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.setWidget(self.tree)
        self._map_icon = _icon("map_tab.svg")
        self._layout_icon = _icon("layout_tab.svg")
        self._folder_maps = None
        self._folder_layouts = None
        self.refresh()

    # ------------------------------------------------------------ contenido
    def current_key(self):
        it = self.tree.currentItem()
        return it.data(0, _ROLE) if it is not None else None

    def refresh(self):
        """Reconstruye el arbol conservando la seleccion y las carpetas plegadas."""
        try:
            selected = self.current_key()
            expanded = {
                "maps": self._folder_maps.isExpanded() if self._folder_maps is not None else True,
                "layouts": self._folder_layouts.isExpanded() if self._folder_layouts is not None else True,
            }
        except RuntimeError:
            selected, expanded = None, {"maps": True, "layouts": True}
        tree = self.tree
        tree.clear()
        p = self.plugin
        self._folder_maps = QTreeWidgetItem(tree, ["Mapas"])
        self._folder_maps.setData(0, _ROLE, "folder:maps")
        self._folder_layouts = QTreeWidgetItem(tree, ["Layouts"])
        self._folder_layouts.setData(0, _ROLE, "folder:layouts")
        reselect = None
        for m in p.maps:
            key = "map:" + m["id"]
            it = QTreeWidgetItem(self._folder_maps, [m["name"]])
            it.setIcon(0, self._map_icon)
            it.setData(0, _ROLE, key)
            self._decorate(it, active=(m["id"] == p.active_id), opened=p.is_map_open(m))
            if key == selected:
                reselect = it
        for layout in p.project_layouts():
            key = "layout:" + layout.name()
            it = QTreeWidgetItem(self._folder_layouts, [layout.name()])
            it.setIcon(0, self._layout_icon)
            it.setData(0, _ROLE, key)
            self._decorate(it, active=(key == p.active_view_key), opened=p.is_layout_open(layout))
            if key == selected:
                reselect = it
        self._folder_maps.setExpanded(expanded["maps"])
        self._folder_layouts.setExpanded(expanded["layouts"])
        if reselect is not None:
            tree.setCurrentItem(reselect)

    @staticmethod
    def _decorate(item, active, opened):
        font = item.font(0)
        font.setBold(active)
        font.setItalic(not opened)
        item.setFont(0, font)
        if active:
            item.setToolTip(0, "Vista activa")
        elif opened:
            item.setToolTip(0, "Abierto en una pestaña")
        else:
            item.setToolTip(0, "Cerrado: doble clic para abrirlo")

    # ------------------------------------------------------------- eventos
    def _on_double_click(self, item, _col):
        key = item.data(0, _ROLE)
        if key and not key.startswith("folder:"):
            self.plugin.catalog_open(key)

    def _on_context(self, pos):
        item = self.tree.itemAt(pos)
        p = self.plugin
        menu = QMenu(self.tree)
        key = item.data(0, _ROLE) if item is not None else None
        if key is None or key.startswith("folder:"):
            if key != "folder:layouts":
                menu.addAction("Nuevo mapa").triggered.connect(lambda *_: p.add_map())
            if key != "folder:maps":
                menu.addAction("Nuevo Layout").triggered.connect(lambda *_: p.new_layout())
                p._fill_template_menu(menu.addMenu("Plantillas"))
        else:
            is_map = key.startswith("map:")
            opened = p.is_view_open(key)
            menu.addAction("Abrir").triggered.connect(lambda *_: p.catalog_open(key))
            if is_map:
                a_side = menu.addAction("Abrir al lado")
                a_side.setEnabled(key[4:] != p.active_id)
                a_side.triggered.connect(lambda *_: p.open_side_map(key[4:]))
                menu.addAction("Abrir en ventana").triggered.connect(lambda *_: p.side_to_window(key[4:]))
            a_close = menu.addAction("Cerrar vista")
            a_close.setEnabled(opened)
            a_close.triggered.connect(lambda *_: p.catalog_close(key))
            menu.addSeparator()
            menu.addAction("Renombrar\tF2").triggered.connect(lambda *_: p.catalog_rename(key))
            menu.addAction("Duplicar").triggered.connect(lambda *_: p.catalog_duplicate(key))
            menu.addSeparator()
            a_del = menu.addAction("Eliminar %s…\tSupr" % ("mapa" if is_map else "Layout"))
            a_del.triggered.connect(lambda *_: p.catalog_delete(key))
            if is_map and len(p.maps) <= 1:
                a_del.setEnabled(False)
        run = getattr(menu, "exec", None) or menu.exec_
        run(self.tree.viewport().mapToGlobal(pos))
