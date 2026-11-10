# -*- coding: utf-8 -*-
KEY = "multimap_layout"   # clave dentro del proyecto .qgz
PROP = "multimap_id"      # propiedad personalizada de elementos de layout enlazados a un mapa
SKIP = "multimap_skip"    # elemento de layout que el usuario dejo sin enlazar
FLAT = "multimap_flat"    # nodo "plano" (oculto) de una capa que pertenece a un mapa inactivo
NONE = "__none__"         # opcion "sin enlazar"


def qenum(cls, scope, name):
    """Acceso a enums de Qt con y sin ambito (PyQt5 / PyQt6, QGIS 3.x / 4):
    Qt.DockWidgetArea.TopDockWidgetArea  <->  Qt.TopDockWidgetArea."""
    try:
        return getattr(getattr(cls, scope), name)
    except AttributeError:
        return getattr(cls, name)
