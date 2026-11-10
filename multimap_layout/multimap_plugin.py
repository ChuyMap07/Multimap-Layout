# -*- coding: utf-8 -*-
"""Multimap Layout v0.6.

Cada "mapa" (pestana) es un arbol de capas completo e independiente.

* El mapa activo vive en el arbol real del proyecto: el panel de Capas se ve
  como siempre (sin grupos extra) y se pueden crear grupos con normalidad.
* Los mapas inactivos se guardan como una estructura (JSON) y sus capas quedan
  en la raiz como nodos "planos": privados (ocultos en el panel y, normalmente,
  en los selectores) y sin marcar. Mantener un nodo por capa evita que QGIS
  elimine la capa del proyecto al quitar el nodo del mapa activo.
"""
import json
import math
import os
import time
import uuid

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsLayerTree,
    QgsLayerTreeGroup,
    QgsLayoutItem,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsMapLayer,
    QgsMapLayerStyle,
    QgsMemoryProviderUtils,
    QgsMessageLog,
    QgsPrintLayout,
    QgsProject,
    QgsReadWriteContext,
    QgsRectangle,
    QgsVectorLayer,
    QgsVirtualLayerDefinition,
)
from qgis.PyQt.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDockWidget,
    QHBoxLayout,
    QVBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

try:
    from qgis.PyQt.QtGui import QAction
except ImportError:  # PyQt5 sin shim
    from qgis.PyQt.QtWidgets import QAction

from .common import FLAT, KEY, NONE, PROP, SKIP, qenum
from .dialogs import LayoutDialog, TabNameEdit
from .map_window import MapViewWindow
from .portable import GROUP_PROP, make_portable
from .tabbar import (
    ProTabBar,
    StripPlacer,
    add_button_stylesheet,
    strip_stylesheet,
    style_colors,
    tab_icon,
)


# ----------------------------------------------------------- compatibilidad
_enum = qenum   # compatibilidad: acceso a enums con y sin ambito (PyQt5 / PyQt6)


def layout_tab_icon():
    """Icono verde de Layout, con variante blanca para la pestaña activa."""
    base = os.path.dirname(__file__)
    icon = QIcon()
    icon.addFile(os.path.join(base, "layout_tab.svg"), QSize(), qenum(QIcon, "Mode", "Normal"))
    icon.addFile(os.path.join(base, "layout_tab_active.svg"), QSize(), qenum(QIcon, "Mode", "Selected"))
    return icon


def _ref_lower_left():
    """Punto de referencia 'abajo a la izquierda' de un elemento de layout.
    El nombre cambio entre versiones (LowerLeft en 3.x, BottomLeft en Qgis.ReferencePoint)."""
    try:
        from qgis.core import Qgis
        return Qgis.ReferencePoint.BottomLeft
    except Exception:
        pass
    try:
        return QgsLayoutItem.ReferencePoint.LowerLeft
    except Exception:
        pass
    return getattr(QgsLayoutItem, "LowerLeft", None)


def _private_flag():
    try:
        from qgis.core import Qgis
        return Qgis.MapLayerFlag.Private
    except Exception:
        pass
    try:
        return QgsMapLayer.LayerFlag.Private
    except Exception:
        return QgsMapLayer.Private


def _mm_unit():
    try:
        from qgis.core import Qgis
        return Qgis.LayoutUnit.Millimeters
    except Exception:
        from qgis.core import QgsUnitTypes
        return QgsUnitTypes.LayoutMillimeters


def _map_item_type():
    try:
        from qgis.core import Qgis
        return int(Qgis.LayoutItemType.Map)
    except Exception:
        from qgis.core import QgsLayoutItemRegistry
        return int(QgsLayoutItemRegistry.LayoutMap)


def _layer_types():
    out = []
    try:
        from qgis.core import Qgis
        for n in ("Vector", "Raster", "Mesh", "PointCloud", "VectorTile"):
            if hasattr(Qgis.LayerType, n):
                out.append(getattr(Qgis.LayerType, n))
        if out:
            return out
    except Exception:
        pass
    try:
        from qgis.core import QgsMapLayerType
        for n in ("VectorLayer", "RasterLayer", "MeshLayer", "PointCloudLayer", "VectorTileLayer"):
            if hasattr(QgsMapLayerType, n):
                out.append(getattr(QgsMapLayerType, n))
    except Exception:
        pass
    return out


PRIVATE = _private_flag()
MM = _mm_unit()


class MultiMapPlugin:
    MENU = "&Multimap Layout"

    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.maps = []          # [{id, name, crs, extent:[xmin,ymin,xmax,ymax]}]
        self.active_id = None
        self.stored = {}        # id de mapa inactivo -> estructura de su arbol (lista de dicts)
        self._busy = False      # evita reentradas de senales
        self._loading = False   # True mientras QGIS carga/limpia un proyecto
        self.dock = None
        self.menu_actions = []
        self._seen = {}                 # id(layout) -> uuids de items ya conocidos
        self._watched = set()
        self._layout_dirty_slots = {}
        self._watched_item_slots = {}
        self._restoring_layouts = False
        self._designer_by_layout = {}
        self._layouts_by_key = {}       # nombre actual -> QgsPrintLayout abierto
        self._layout_name_slots = {}    # evita conexiones duplicadas y permite desconectar en unload
        self._view_order = []           # claves "map:<id>" y "layout:<nombre>"
        self._map_windows = {}          # mapa id -> ventana secundaria
        self._syncing_floating = False
        self._patched = {}              # id(layout) -> (accion 'Anadir Mapa', menu)
        self._pending = {}              # id(layout) -> (id de mapa elegido, instante, mapa activo previo)
        self._deferred_layout_binds = {}  # (layout, uuid) -> timer, layout, item, mapa, mapa previo
        self._surgery_pending = False   # tras guardar: convertir el archivo en proyecto portable
        self._hidden = {}               # id -> capa de un mapa inactivo, FUERA del registro del proyecto
        self._layer_by_map = {}         # id de mapa -> id de su ultima capa activa
        self._quiet_crs = False         # True al abrir un proyecto: ajustar el CRS no lo marca como modificado
        self._legacy_noted = set()      # layouts a los que ya se ofrecio enlazar elementos sueltos
        self._unloaded = False
        self._active_designer = None
        self._layout_toolbar_window = None
        self._map_strip_pos = None
        self._align_gen = 0
        self.active_view_key = None
        self._main_central = None
        self.view_stack = None
        self._main_chrome_visibility = None
        self._native_new_layout_action = None
        self._native_new_layout_enabled = None
        self._new_layout_proxy = None
        self._new_layout_action_hosts = []

    # ------------------------------------------------------------------ GUI
    def initGui(self):
        win = self.iface.mainWindow()
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))

        self.tabbar = ProTabBar()
        self._tab_icon = tab_icon()
        self._layout_icon = layout_tab_icon()
        colors = self.tabbar.colors
        h = self.tabbar.row_height()

        self.btn_add = QToolButton()
        self.btn_add.setText("+")
        self.btn_add.setToolTip("Nuevo mapa vacío")
        self.btn_add.setAutoRaise(True)
        self.btn_add.setFixedSize(h + 6, h)
        self.btn_add.setStyleSheet(add_button_stylesheet(colors))

        w = QWidget()
        w.setObjectName("mmStrip")
        w.setAttribute(qenum(Qt, "WidgetAttribute", "WA_StyledBackground"), True)
        w.setStyleSheet(strip_stylesheet(colors))
        w.setFixedHeight(h)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.tabbar)
        lay.addWidget(self.btn_add)
        lay.addStretch(1)

        self.strip = w
        self.placer = None
        self.dock = None
        try:    # lo normal: la barra va dentro del widget central, pegada al lienzo
            self.placer = StripPlacer(w, win.centralWidget(), self.canvas)
        except Exception as e:
            QgsMessageLog.logMessage(
                "No se pudo pegar la barra al lienzo (%s); se usa un panel." % e, "Multimap Layout"
            )
            self.placer = None
            self.dock = QDockWidget("Multimapa", win)
            self.dock.setObjectName("MultiMapLayoutDock")
            self.dock.setTitleBarWidget(QWidget())  # sin barra de titulo
            self.dock.setFeatures(qenum(QDockWidget, "DockWidgetFeature", "NoDockWidgetFeatures"))
            self.dock.setWidget(w)
            self.iface.addDockWidget(qenum(Qt, "DockWidgetArea", "TopDockWidgetArea"), self.dock)

        if self.placer is not None:     # colores definitivos cuando la ventana ya esta pintada
            QTimer.singleShot(300, self._restyle)
        # takeCentralWidget: QMainWindow no debe borrar el widget central original de QGIS
        # (lienzo, barra de mensajes) al poner el contenedor de vistas en su lugar.
        self._main_central = win.takeCentralWidget()
        self.view_stack = QStackedWidget(win)
        self.view_stack.addWidget(self._main_central)
        win.setCentralWidget(self.view_stack)
        self.tabbar.setContextMenuPolicy(qenum(Qt, "ContextMenuPolicy", "CustomContextMenu"))
        self._connect_tabbar(self.tabbar)
        self.btn_add.clicked.connect(self.add_map)
        self._build_layout_toolbar()
        self._replace_native_new_layout_action()

        # Menu de complementos
        self.act_add = QAction(icon, "Nuevo mapa", win)
        self.act_dup = QAction(icon, "Duplicar mapa activo", win)
        self.act_layout = QAction(icon, "Crear layout con todos los mapas…", win)
        self.act_assign = QAction(icon, "Asignar mapa a elementos del layout…", win)
        self.act_add.triggered.connect(self.add_map)
        self.act_dup.triggered.connect(self.duplicate_map)
        self.act_layout.triggered.connect(self.create_layout)
        self.act_assign.triggered.connect(self.assign_map_to_layout_items)
        self.menu_actions = [self.act_add, self.act_dup, self.act_layout, self.act_assign]
        for a in self.menu_actions:
            self.iface.addPluginToMenu(self.MENU, a)

        # Menu contextual de las capas: Multimapa > copiar / mover
        self.act_copy = QAction("Copiar a otro mapa…", win)
        self.act_move = QAction("Mover a otro mapa…", win)
        self.act_copy.triggered.connect(self.copy_selected_layers)
        self.act_move.triggered.connect(self.move_selected_layers)
        for t in _layer_types():
            for a in (self.act_copy, self.act_move):
                try:
                    self.iface.addCustomActionForLayerType(a, "Multimapa", t, True)
                except Exception:
                    pass

        # Disenador de layouts: lista de mapas en "Anadir Mapa" + panel
        try:
            self.iface.layoutDesignerOpened.connect(self._on_designer_opened)
        except Exception:
            pass
        try:
            self.iface.layoutDesignerWillBeClosed.connect(self._on_designer_will_close)
        except Exception:
            pass
        for d in self._designers():
            self._on_designer_opened(d)

        prj = QgsProject.instance()
        prj.layersAdded.connect(self._on_layers_added)
        prj.writeProject.connect(self._on_write)
        prj.cleared.connect(self._on_cleared)
        prj.readProject.connect(self._on_read_project)
        prj.projectSaved.connect(self._after_save)
        try:
            prj.crsChanged.connect(self._on_project_crs_changed)
        except Exception:
            pass
        self.canvas.destinationCrsChanged.connect(self._on_crs_changed)
        self.canvas.extentsChanged.connect(self._sync_floating_from_main)
        try:
            self._layer_model = self.iface.layerTreeView().model()
            self._layer_model_signals = []
            for signal_name in ("dataChanged", "rowsInserted", "rowsRemoved", "rowsMoved", "layoutChanged"):
                signal = getattr(self._layer_model, signal_name, None)
                if signal is not None:
                    signal.connect(self._on_main_layer_tree_changed)
                    self._layer_model_signals.append(signal)
        except Exception:
            self._layer_model = None
            self._layer_model_signals = []
        self.iface.projectRead.connect(self._load_state)
        self.iface.newProjectCreated.connect(self._on_project_new)

        self._load_state()  # por si ya hay un proyecto abierto

    def unload(self):
        self._unloaded = True
        self._release_hidden()
        self._show_map_view()
        self._restore_native_new_layout_action()
        for designer in self._designers():
            try:
                window = designer.window()
                if self._layout_toolbar_window is window:
                    self._detach_layout_toolbar(window)
                if self.view_stack is not None and self.view_stack.indexOf(window) >= 0:
                    self.view_stack.removeWidget(window)
                window.setParent(self.iface.mainWindow(), qenum(Qt, "WindowType", "Window"))
                window.show()
            except Exception:
                pass
        if self.view_stack is not None and self._main_central is not None:
            try:
                win = self.iface.mainWindow()
                stack = win.takeCentralWidget()
                self.view_stack.removeWidget(self._main_central)
                self._main_central.setParent(win)
                win.setCentralWidget(self._main_central)
                if stack is not None:
                    stack.deleteLater()
                self.view_stack = None
            except Exception:
                pass
        if self._layout_toolbar_window is not None:
            self._detach_layout_toolbar()
        for window in list(self._map_windows.values()):
            try:
                window.close()
            except RuntimeError:
                pass
        self._map_windows.clear()
        for signal in self._layer_model_signals:
            try:
                signal.disconnect(self._on_main_layer_tree_changed)
            except Exception:
                pass
        self._layer_model_signals = []
        for layout, slot in list(self._layout_name_slots.values()):
            try:
                layout.nameChanged.disconnect(slot)
            except Exception:
                pass
        self._layout_name_slots.clear()
        for layout, slots in list(self._layout_dirty_slots.values()):
            for signal, slot in slots:
                try:
                    signal.disconnect(slot)
                except Exception:
                    pass
        self._layout_dirty_slots.clear()
        for item, signal, slot in list(self._watched_item_slots.values()):
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        self._watched_item_slots.clear()
        self._pending.clear()
        self._cancel_deferred_layout_binds()
        for action, menu in list(self._patched.values()):
            try:
                action.setMenu(None)
                menu.deleteLater()
            except Exception:
                pass
        self._patched = {}
        prj = QgsProject.instance()
        pairs = [
            (prj.layersAdded, self._on_layers_added),
            (prj.writeProject, self._on_write),
            (prj.cleared, self._on_cleared),
            (prj.readProject, self._on_read_project),
            (prj.projectSaved, self._after_save),
            (prj.crsChanged, self._on_project_crs_changed),
            (self.canvas.destinationCrsChanged, self._on_crs_changed),
            (self.canvas.extentsChanged, self._sync_floating_from_main),
            (self.iface.projectRead, self._load_state),
            (self.iface.newProjectCreated, self._on_project_new),
        ]
        try:
            pairs.append((self.iface.layoutDesignerOpened, self._on_designer_opened))
        except Exception:
            pass
        try:
            pairs.append((self.iface.layoutDesignerWillBeClosed, self._on_designer_will_close))
        except Exception:
            pass
        for sig, slot in pairs:
            try:
                sig.disconnect(slot)
            except Exception:
                pass
        for a in self.menu_actions:
            try:
                self.iface.removePluginMenu(self.MENU, a)
            except Exception:
                pass
        for a in (self.act_copy, self.act_move):
            try:
                self.iface.removeCustomActionForLayerType(a)
            except Exception:
                pass
        for d in self._designers():
            try:
                d.layoutMenu().removeAction(self.act_assign)
            except Exception:
                pass
        self._clear_privacy()
        if self.placer is not None:
            self.placer.remove()
            self.placer = None
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

    # -------------------------------------------------------------- helpers
    def _root(self):
        return QgsProject.instance().layerTreeRoot()

    def _get(self, map_id):
        for m in self.maps:
            if m["id"] == map_id:
                return m
        return None

    def _warn(self, text):
        self.iface.messageBar().pushWarning("Multimapa", text)

    def _ok(self, text):
        self.iface.messageBar().pushSuccess("Multimapa", text)

    @staticmethod
    def _crs_str(crs):
        return crs.authid() or ("WKT:" + crs.toWkt())

    @staticmethod
    def _crs_from(s):
        return QgsCoordinateReferenceSystem(s)

    @staticmethod
    def _rect_to_list(r):
        return [r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()]

    def _new_map(self, name, crs_str, extent_list):
        return {"id": uuid.uuid4().hex[:8], "name": name, "crs": crs_str, "extent": extent_list}

    def _next_name(self):
        used = set(m["name"] for m in self.maps)
        n = 1
        while "Mapa %d" % n in used:
            n += 1
        return "Mapa %d" % n

    def _current_view(self):
        crs = self._crs_str(self.canvas.mapSettings().destinationCrs())
        return crs, self._rect_to_list(self.canvas.extent())

    def _save_view(self):
        m = self._get(self.active_id)
        if m:
            m["crs"], m["extent"] = self._current_view()
            try:
                m["rot"] = float(self.canvas.rotation())
            except Exception:
                pass

    def _persist(self):
        st = {"v": 6, "active": self.active_id, "maps": self.maps, "stored": self.stored,
              "view_order": self._view_order or self._current_view_order()}
        QgsProject.instance().writeEntry(KEY, "state", json.dumps(st))

    def _pick_map(self, title, label, exclude=None, default=None):
        """Dialogo para elegir un mapa. Devuelve su id o None."""
        cands = [m for m in self.maps if m["id"] != exclude]
        if not cands:
            self._warn("No hay otro mapa disponible. Crea uno con «+».")
            return None
        items = ["%d. %s" % (i + 1, m["name"]) for i, m in enumerate(cands)]
        cur = 0
        for i, m in enumerate(cands):
            if m["id"] == default:
                cur = i
        text, ok = QInputDialog.getItem(self.iface.mainWindow(), title, label, items, cur, False)
        if not ok:
            return None
        return cands[items.index(text)]["id"]

    # ---------------------------------------------- arbol: activo vs. inactivo
    @staticmethod
    def _is_flat(node):
        return QgsLayerTree.isLayer(node) and bool(node.customProperty(FLAT, ""))

    def _active_nodes(self):
        """Nodos de la raiz que pertenecen al mapa activo (todo menos los planos)."""
        return [c for c in self._root().children() if not self._is_flat(c)]

    @staticmethod
    def _layer_nodes(node):
        if QgsLayerTree.isLayer(node):
            return [node]
        if QgsLayerTree.isGroup(node):
            return list(node.findLayers())
        return []

    @staticmethod
    def _node_props(n):
        """Propiedades personalizadas del nodo (ajustes de leyenda, conteo de entidades...)."""
        out = {}
        try:
            for k in n.customProperties():
                if k in (FLAT, PROP, SKIP):
                    continue
                v = n.customProperty(k)
                if isinstance(v, (str, int, float, bool)):
                    out[str(k)] = v
        except Exception:
            pass
        return out

    def _capture(self, nodes):
        """Estructura (JSON) de una lista de nodos: grupos, orden, visibilidad y ajustes del nodo."""
        out = []
        for n in nodes:
            if QgsLayerTree.isGroup(n):
                d = {
                    "t": "g", "name": n.name(), "on": bool(n.itemVisibilityChecked()),
                    "exp": bool(n.isExpanded()), "ch": self._capture(n.children()),
                }
                try:
                    if n.isMutuallyExclusive():
                        kids = list(n.children())
                        d["mx"] = next((i for i, k in enumerate(kids) if k.itemVisibilityChecked()), -1)
                except Exception:
                    pass
                props = self._node_props(n)
                if props:
                    d["props"] = props
                out.append(d)
            elif QgsLayerTree.isLayer(n) and n.layer() is not None:
                d = {"t": "l", "id": n.layerId(), "on": bool(n.itemVisibilityChecked()),
                     "exp": bool(n.isExpanded())}
                props = self._node_props(n)
                if props:
                    d["props"] = props
                out.append(d)
        return out

    def _struct_layer_ids(self, items):
        ids = []
        for it in items:
            if it.get("t") == "g":
                ids.extend(self._struct_layer_ids(it.get("ch", [])))
            else:
                ids.append(it.get("id"))
        return ids

    def _remap(self, items, idmap):
        out = []
        for it in items:
            if it.get("t") == "g":
                d = dict(it)
                d["ch"] = self._remap(it.get("ch", []), idmap)
                out.append(d)
            elif it.get("id") in idmap:
                d = dict(it)
                d["id"] = idmap[it["id"]].id()
                out.append(d)
        return out

    def _active_layers(self):
        out, seen = [], set()
        for n in self._active_nodes():
            for ln in self._layer_nodes(n):
                lyr = ln.layer()
                if lyr is not None and lyr.id() not in seen:
                    seen.add(lyr.id())
                    out.append(lyr)
        return out

    def _ask_edit_choice(self, names):
        """Pregunta que hacer con las capas en edicion que se van a ocultar: save | discard | cancel."""
        box = QMessageBox(self.iface.mainWindow())
        box.setWindowTitle("Capas en edición")
        box.setText("Estas capas tienen cambios sin guardar:\n\n%s\n\nAl cambiar de mapa dejan de estar visibles." % names)
        b_save = box.addButton("Guardar cambios y continuar", qenum(QMessageBox, "ButtonRole", "AcceptRole"))
        b_disc = box.addButton("Descartar cambios y continuar", qenum(QMessageBox, "ButtonRole", "DestructiveRole"))
        b_cancel = box.addButton("Cancelar", qenum(QMessageBox, "ButtonRole", "RejectRole"))
        box.setDefaultButton(b_cancel)
        (getattr(box, "exec", None) or box.exec_)()
        clicked = box.clickedButton()
        return "save" if clicked is b_save else "discard" if clicked is b_disc else "cancel"

    def _release_edits(self, layers):
        """Antes de ocultar capas: las que estan en edicion se guardan o se descartan (o se cancela).
        Sin cambios pendientes solo se termina la edicion. Devuelve False si hay que cancelar."""
        editable = [l for l in layers if isinstance(l, QgsVectorLayer) and l.isEditable()]
        if not editable:
            return True
        modified = [l for l in editable if l.isModified()]
        choice = "save"
        if modified:
            choice = self._ask_edit_choice(", ".join(l.name() for l in modified))
            if choice == "cancel":
                return False
        for lyr in editable:
            try:
                if lyr.isModified() and choice == "discard":
                    lyr.rollBack()
                elif not lyr.commitChanges():
                    self._warn("No se pudieron guardar los cambios de «%s»: %s" % (lyr.name(), "; ".join(lyr.commitErrors())[:200]))
                    return False
            except Exception as e:
                self._log("No se pudo terminar la edicion de «%s»: %s" % (lyr.name(), e))
        return True

    # ------------------------------------------- aislamiento de capas por mapa
    def _layer(self, lid):
        """Capa por id: del registro del proyecto o, si es de un mapa inactivo, del almacen propio."""
        if not lid:
            return None
        lyr = QgsProject.instance().mapLayer(lid)
        return lyr if lyr is not None else self._hidden.get(lid)

    def _hide_layer(self, lyr):
        """La capa sale del registro del proyecto (nadie mas la ve) pero sigue viva en el almacen.
        QGIS quita sola sus nodos del arbol al sacarla del registro."""
        if lyr is None:
            return
        lid = lyr.id()
        if lid in self._hidden:
            return
        taken = QgsProject.instance().takeMapLayer(lyr)
        if taken is not None:
            self._hidden[lid] = taken

    def _show_layer(self, lid):
        """Devuelve una capa oculta al registro (sin nodo en el arbol). Devuelve la capa o None."""
        lyr = self._hidden.pop(lid, None)
        if lyr is not None:
            QgsProject.instance().addMapLayer(lyr, False)
            return lyr
        return QgsProject.instance().mapLayer(lid)

    def _drop_layers(self, ids):
        """Elimina capas definitivamente, esten en el registro o en el almacen."""
        reg = []
        for lid in ids:
            if lid in self._hidden:
                self._hidden.pop(lid, None)
            else:
                reg.append(lid)
        if reg:
            QgsProject.instance().removeMapLayers(reg)

    def _add_flat(self, lyr):
        """Capa de un mapa inactivo: sale del registro del proyecto (aislamiento)."""
        self._hide_layer(lyr)
        return None

    def _hidden_order(self):
        """Orden de escritura/lectura: las capas virtuales al final (leen a las demas)."""
        def virtual(lid):
            l = self._hidden[lid]
            return isinstance(l, QgsVectorLayer) and l.providerType() == "virtual"
        return sorted(self._hidden.keys(), key=lambda i: (1 if virtual(i) else 0))

    def _inject_hidden(self, doc):
        """Durante el guardado las capas ocultas se escriben dentro del proyecto."""
        try:
            if doc is None or not self._hidden:
                return
            el = doc.createElement("multimap_hidden_layers")
            ctx = QgsReadWriteContext()
            ctx.setPathResolver(QgsProject.instance().pathResolver())
            for lid in self._hidden_order():
                node = doc.createElement("maplayer")
                if self._hidden[lid].writeLayerXml(node, doc, ctx):
                    el.appendChild(node)
            doc.documentElement().appendChild(el)
            self._surgery_pending = True
        except Exception as e:
            self._log("No se pudieron guardar las capas de los otros mapas: %s" % e)

    def _after_save(self, *_):
        """QGIS acaba de guardar: las capas de los otros mapas pasan de nuestro elemento propio a capas
        y grupos normales, para que cualquier QGIS (sin el complemento) las lea sin perderlas.
        Se hace un instante despues, cuando el archivo ya esta completo en su sitio."""
        if not self._surgery_pending:
            return
        self._surgery_pending = False
        path = QgsProject.instance().fileName()
        groups = []
        for m in self.maps:
            if m["id"] == self.active_id:
                continue
            ids = [i for i in self._struct_layer_ids(self.stored.get(m["id"], [])) if i in self._hidden]
            if ids:
                groups.append(("%s (Multimap)" % m["name"], ids))
        temp = [l.name() for l in self._hidden.values()
                if isinstance(l, QgsVectorLayer) and l.providerType() == "memory" and l.featureCount() > 0]
        if temp:
            self._warn("Capas temporales de otros mapas: sus datos NO se guardan con el proyecto (%s). "
                       "Expórtalas a un archivo." % ", ".join(temp))
        QTimer.singleShot(250, lambda: self._convert_portable(path, groups))

    def _convert_portable(self, path, groups):
        try:
            if not path or not os.path.isfile(path) or not path.lower().endswith((".qgz", ".qgs")):
                self._log("El proyecto quedo en el formato propio (no es un archivo .qgz/.qgs): %s" % path)
                return
            if not make_portable(path, groups):
                self._log("El proyecto ya estaba en formato portable o no tenia capas ocultas: %s" % path)
        except Exception as e:
            self._log("El proyecto quedo en el formato propio (no se pudo hacer portable): %s" % e)

    def _on_read_project(self, doc):
        """Al abrir un proyecto: recupera las capas ocultas y las saca otra vez del registro."""
        try:
            self._hidden.clear()
            prj = QgsProject.instance()
            root = prj.layerTreeRoot()          # 1) formato portable: grupos marcados con las capas
            for g in [c for c in root.children() if QgsLayerTree.isGroup(c) and c.customProperty(GROUP_PROP, "")]:
                for ln in g.findLayers():
                    if ln.layer() is not None:
                        self._hide_layer(ln.layer())
                root.removeChildNode(g)
            el = doc.documentElement().firstChildElement("multimap_hidden_layers")   # 2) formato propio
            if el.isNull():
                return
            nodes = el.childNodes()
            ids = []
            for i in range(nodes.count()):
                node = nodes.at(i)
                lid = node.firstChildElement("id").text()
                if lid and prj.mapLayer(lid) is None and prj.readLayer(node):
                    ids.append(lid)
            for lid in ids:                     # uniones y capas virtuales entre capas ocultas
                lyr = prj.mapLayer(lid)
                if lyr is not None:
                    lyr.resolveReferences(prj)
            for lid in ids:
                self._hide_layer(prj.mapLayer(lid))
        except Exception as e:
            self._log("No se pudieron recuperar las capas de los otros mapas: %s" % e)

    def _migrate_flat_nodes(self):
        """Proyectos guardados con versiones anteriores: los nodos planos pasan al almacen."""
        root = self._root()
        for n in [c for c in root.children() if self._is_flat(c)]:
            lyr = n.layer()
            if lyr is not None:
                self._set_private(lyr, False)
                self._hide_layer(lyr)
            else:
                root.removeChildNode(n)
        for n in [c for c in root.children() if self._is_flat(c)]:
            root.removeChildNode(n)

    def _release_hidden(self):
        """Al descargar el complemento las capas ocultas vuelven al proyecto (no se pierde nada)."""
        if not self._hidden:
            return
        root = self._root()
        group = root.addGroup("Capas de otros mapas (Multimap)")
        group.setItemVisibilityChecked(False)
        for lid in list(self._hidden.keys()):
            lyr = self._show_layer(lid)
            if lyr is not None:
                node = group.addLayer(lyr)
                node.setItemVisibilityChecked(False)

    def _stash_active(self):
        """El mapa activo pasa a ser inactivo: guarda su estructura y saca sus capas del registro."""
        root = self._root()
        nodes = self._active_nodes()
        self.stored[self.active_id] = self._capture(nodes)
        layers, seen = [], set()
        for n in nodes:
            for ln in self._layer_nodes(n):
                lyr = ln.layer()
                if lyr is not None and lyr.id() not in seen:
                    seen.add(lyr.id())
                    layers.append(lyr)
        cur = self.iface.activeLayer()
        if cur is not None and self.active_id:
            self._layer_by_map[self.active_id] = cur.id()
        for lyr in layers:                    # QGIS quita sus nodos del arbol al sacarlas
            self._hide_layer(lyr)
        for n in list(self._active_nodes()):  # grupos que quedaron vacios
            root.removeChildNode(n)

    def _build(self, items, parent):
        """Reconstruye nodos reales a partir de la estructura. Devuelve los ids creados."""
        built = set()
        for it in items:
            if it.get("t") == "g":
                g = parent.addGroup(it.get("name", ""))
                g.setItemVisibilityChecked(bool(it.get("on", True)))
                g.setExpanded(bool(it.get("exp", True)))
                for k, v in (it.get("props") or {}).items():
                    g.setCustomProperty(k, v)
                built |= self._build(it.get("ch", []), g)
                if "mx" in it:
                    try:
                        g.setIsMutuallyExclusive(True, int(it["mx"]))
                    except Exception:
                        pass
            else:
                lid = it.get("id", "")
                lyr = self._show_layer(lid) if lid in self._hidden else QgsProject.instance().mapLayer(lid)
                if lyr is None:
                    continue
                self._set_private(lyr, False)     # antes de insertar, para que el panel la muestre
                n = parent.addLayer(lyr)
                n.setItemVisibilityChecked(bool(it.get("on", True)))
                for k, v in (it.get("props") or {}).items():
                    n.setCustomProperty(k, v)
                if "exp" in it:
                    n.setExpanded(bool(it["exp"]))
                built.add(lyr.id())
        return built

    def _restore(self, map_id):
        """Un mapa inactivo pasa a ser el activo: sus capas vuelven al registro y se crean sus nodos."""
        items = self.stored.pop(map_id, [])
        root = self._root()
        flats = [c for c in root.children() if self._is_flat(c)]
        built = self._build(items, root)
        for f in flats:                       # restos de versiones anteriores
            if f.layerId() in built:
                root.removeChildNode(f)
        lid = self._layer_by_map.get(map_id)
        lyr = QgsProject.instance().mapLayer(lid) if lid else None
        if lyr is not None:                   # cada mapa recuerda su capa activa
            try:
                self.iface.setActiveLayer(lyr)
            except Exception:
                pass

    # ----------------------------------------------------------- privacidad
    @staticmethod
    def _set_private(lyr, private):
        """Marca o desmarca la capa como privada. Se opera con enteros y se reconstruye el
        tipo de banderas: en QGIS 4 'flags & ~Private' devuelve un int que setFlags rechaza."""
        try:
            cur = lyr.flags()
            cur_i, bit = int(cur), int(PRIVATE)
            if bool(cur_i & bit) == private:
                return
            new_i = (cur_i | bit) if private else (cur_i & ~bit)
            try:
                lyr.setFlags(type(cur)(new_i))
            except Exception:
                lyr.setFlags(new_i)
        except Exception as e:
            QgsMessageLog.logMessage(
                "No se pudo cambiar la marca privada de la capa: %s" % e, "Multimap Layout"
            )

    def _apply_privacy(self):
        """Capas de mapas inactivos -> privadas y sin marcar; capas del activo -> normales."""
        cur = self.iface.activeLayer()
        hide_current = False
        for n in self._root().findLayers():
            lyr = n.layer()
            if lyr is None:
                continue
            flat = bool(n.customProperty(FLAT, ""))
            self._set_private(lyr, flat)
            if flat:
                if n.itemVisibilityChecked():
                    n.setItemVisibilityChecked(False)
                if cur is not None and cur.id() == lyr.id():
                    hide_current = True
        if hide_current:
            try:
                self.iface.setActiveLayer(None)
            except Exception:
                pass
        self._refresh_panel()

    def _refresh_panel(self):
        """QGIS solo reevalua la fila del primer nodo de una capa cuando cambia su marca
        'privada'; esto fuerza a reevaluar todas las filas del panel de Capas."""
        try:
            view = self.iface.layerTreeView()
            view.setShowPrivateLayers(view.showPrivateLayers())
        except Exception:
            pass

    def _clear_privacy(self):
        for n in self._root().findLayers():
            lyr = n.layer()
            if lyr is not None:
                self._set_private(lyr, False)
        self._refresh_panel()

    # ----------------------------------------------------------------- tabs
    def _tab_key(self, idx, bar=None):
        bar = bar or self.tabbar
        return str(bar.tabData(idx) or "")

    def _connect_tabbar(self, bar):
        bar.setContextMenuPolicy(qenum(Qt, "ContextMenuPolicy", "CustomContextMenu"))
        bar.customContextMenuRequested.connect(lambda pos, b=bar: self._on_tab_context(pos, b))
        bar.currentChanged.connect(lambda idx, b=bar: self._on_tab_changed(idx, b))
        bar.closeClicked.connect(lambda idx, b=bar: self._on_tab_close(idx, b))
        bar.detachRequested.connect(lambda idx, point, b=bar: self._on_tab_detach(idx, point, b))
        bar.tabBarDoubleClicked.connect(lambda idx, b=bar: self._on_tab_rename(idx, b))
        bar.tabMoved.connect(lambda *_args, b=bar: self._on_tab_moved(b))

    @staticmethod
    def _qt_object_alive(widget):
        if widget is None:
            return False
        try:
            widget.objectName()
            return True
        except RuntimeError:
            return False

    def _ensure_layout_toolbar(self):
        if (self._qt_object_alive(getattr(self, "layout_tabbar", None))
                and self._qt_object_alive(getattr(self, "layout_toolbar", None))
                and self._qt_object_alive(getattr(self, "layout_add_map", None))):
            return
        old_toolbar = getattr(self, "layout_toolbar", None)
        old_window = self._layout_toolbar_window
        if self._qt_object_alive(old_toolbar):
            try:
                if self._qt_object_alive(old_window):
                    old_window.removeToolBar(old_toolbar)
                old_toolbar.setParent(self.iface.mainWindow())
                old_toolbar.deleteLater()
            except RuntimeError:
                pass
        self._build_layout_toolbar()
        self._layout_toolbar_window = None

    def _build_layout_toolbar(self):
        """Barra de pestañas para la vista de Layout. Lleva dos separadores (alto y ancho) que
        se ajustan para que las pestañas queden en el mismo sitio que en la vista de mapas."""
        win = self.iface.mainWindow()
        self.layout_tabbar = ProTabBar()
        self.layout_toolbar = QToolBar("Multimapa", win)
        self.layout_toolbar.setObjectName("MultiMapLayoutViewToolbar")
        self.layout_toolbar.setMovable(False)
        self.layout_toolbar.setFloatable(False)
        # Oculta de forma explicita: la barra es hija de la ventana principal pero no esta
        # acoplada a ella. Si QGIS carga el complemento al arrancar (ventana aun sin mostrar),
        # Qt la mostraria junto con la ventana en la esquina (0,0), tapando el menu
        # Proyecto/Edicion. Solo se muestra al acoplarla al diseñador de Layout.
        self.layout_toolbar.hide()
        h = self.layout_tabbar.row_height()
        self.layout_add_map = QToolButton()
        self.layout_add_map.setText("+")
        self.layout_add_map.setToolTip("Nuevo mapa vacío")
        self.layout_add_map.setAutoRaise(True)
        self.layout_add_map.setFixedSize(h + 6, h)
        host = QWidget()
        vbox = QVBoxLayout(host)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        self._layout_gap = QWidget()
        self._layout_gap.setFixedHeight(0)
        vbox.addWidget(self._layout_gap)
        mid = QWidget()
        hmid = QHBoxLayout(mid)
        hmid.setContentsMargins(0, 0, 0, 0)
        hmid.setSpacing(0)
        self._layout_xgap = QWidget()
        self._layout_xgap.setFixedWidth(0)
        hmid.addWidget(self._layout_xgap)
        row = QWidget()
        row.setObjectName("mmStrip")
        row.setAttribute(qenum(Qt, "WidgetAttribute", "WA_StyledBackground"), True)
        row.setFixedHeight(h)
        hrow = QHBoxLayout(row)
        hrow.setContentsMargins(0, 0, 0, 0)
        hrow.setSpacing(0)
        hrow.addWidget(self.layout_tabbar)
        hrow.addWidget(self.layout_add_map)
        hrow.addStretch(1)
        hmid.addWidget(row, 1)
        vbox.addWidget(mid)
        self._layout_row = row
        self.layout_toolbar.addWidget(host)
        self._connect_tabbar(self.layout_tabbar)
        self.layout_add_map.clicked.connect(self.add_map)
        colors = self.tabbar.colors
        self.layout_tabbar.apply_colors(colors)
        self.layout_toolbar.setStyleSheet(
            "QToolBar#MultiMapLayoutViewToolbar { border: none; padding: 0px; spacing: 0px; margin: 0px; }"
            + strip_stylesheet(colors))
        self.layout_add_map.setStyleSheet(add_button_stylesheet(colors))

    @staticmethod
    def _is_layout_toolbar(widget):
        try:
            return isinstance(widget, QToolBar) and widget.objectName() == "MultiMapLayoutViewToolbar"
        except RuntimeError:
            return False

    def _hide_stray_layout_toolbars(self):
        """Ninguna barra de layout debe quedar visible sobre la ventana principal."""
        try:
            win = self.iface.mainWindow()
            for tb in win.findChildren(QToolBar):
                if self._is_layout_toolbar(tb) and tb.parent() is win and tb.isVisible():
                    tb.hide()
        except RuntimeError:
            pass

    def _detach_layout_toolbar(self, window=None):
        """Quita la barra del Layout y la deja oculta (nunca suelta sobre la ventana principal)."""
        window = window or self._layout_toolbar_window
        tb = getattr(self, "layout_toolbar", None)
        if tb is not None and self._qt_object_alive(tb):
            try:
                if window is not None and self._qt_object_alive(window):
                    window.removeToolBar(tb)
                tb.hide()
            except RuntimeError:
                pass
        if window is None or window is self._layout_toolbar_window:
            self._layout_toolbar_window = None

    def _map_strip_origin(self):
        """Posicion (respecto a la ventana principal) de la barra de mapas, mientras es visible."""
        try:
            if (self.strip is not None and self.strip.isVisible()
                    and self.view_stack is not None
                    and self.view_stack.currentWidget() is self._main_central):
                pt = self.strip.mapTo(self.iface.mainWindow(), QPoint(0, 0))
                self._map_strip_pos = (pt.x(), pt.y())
        except RuntimeError:
            pass

    def _schedule_align(self, tries_left=12, delay=60):
        """Una sola cadena de ajustes a la vez (dos en paralelo se pisan y se pasan de largo)."""
        self._align_gen += 1
        gen = self._align_gen
        QTimer.singleShot(delay, lambda: self._align_layout_strip(tries_left, gen))

    def _align_layout_strip(self, tries=12, gen=None):
        """Iguala la posicion de las pestañas del Layout con la de la vista de mapas."""
        try:
            if gen is not None and gen != self._align_gen:
                return
            if (self._layout_toolbar_window is None or self._map_strip_pos is None
                    or not self._qt_object_alive(self.layout_toolbar)):
                return
            win = self.iface.mainWindow()
            cur = self._layout_row.mapTo(win, QPoint(0, 0))
            dy = self._map_strip_pos[1] - cur.y()
            dx = self._map_strip_pos[0] - cur.x()
            if dy == 0 and dx == 0:
                return
            gap = max(0, self._layout_gap.height() + dy)
            xgap = max(0, self._layout_xgap.width() + dx)
            if gap == self._layout_gap.height() and xgap == self._layout_xgap.width():
                return      # ya en el limite: el Layout tiene mas barras arriba que la ventana de mapas
            self._layout_gap.setFixedHeight(gap)
            self._layout_xgap.setFixedWidth(xgap)
            if tries > 1:
                QTimer.singleShot(80, lambda: self._align_layout_strip(tries - 1, gen))
        except RuntimeError:
            pass

    def _tab_id(self, idx, bar=None):
        key = self._tab_key(idx, bar)
        return key[4:] if key.startswith("map:") else None

    def _current_view_order(self, bar=None):
        bar = bar or self.tabbar
        return [self._tab_key(i, bar) for i in range(bar.count()) if self._tab_key(i, bar)]

    def _index_of_tab(self, map_id, bar=None):
        bar = bar or self.tabbar
        for i in range(bar.count()):
            if self._tab_key(i, bar) == "map:" + str(map_id):
                return i
        return -1

    def _fill_tabbar(self, bar):
        if bar is getattr(self, "layout_tabbar", None) and not self._qt_object_alive(bar):
            self._ensure_layout_toolbar()
            bar = self.layout_tabbar
        if not self._qt_object_alive(bar):
            return
        bar.blockSignals(True)
        while bar.count():
            bar.removeTab(0)
        available = {"map:" + m["id"]: ("map", m) for m in self.maps}
        for name, layout in self._layouts_by_key.items():
            available["layout:" + name] = ("layout", layout)
        ordered = [key for key in self._view_order if key in available]
        ordered.extend(key for key in available if key not in ordered)
        for key in ordered:
            kind, item = available[key]
            if kind == "map":
                bar.add_map_tab(self._tab_icon, item["name"], item["id"])
            else:
                bar.add_layout_tab(self._layout_icon, item.name(), item.name())
        selected = self.active_view_key or ("map:" + str(self.active_id) if self.active_id else "")
        i = next((n for n in range(bar.count()) if self._tab_key(n, bar) == selected), -1)
        if i >= 0:
            bar.setCurrentIndex(i)
        bar.blockSignals(False)
        bar.refresh_close_buttons()

    def _refresh_tabs(self):
        self._ensure_layout_toolbar()
        available = {"map:" + m["id"] for m in self.maps}
        available.update("layout:" + name for name in self._layouts_by_key)
        ordered = [key for key in self._view_order if key in available]
        ordered.extend(key for key in available if key not in ordered)
        hidden = [key for key in self._view_order if key.startswith("layout:") and key not in available]
        self._view_order = ordered + [key for key in hidden if key not in ordered]
        self._fill_tabbar(self.tabbar)
        self._fill_tabbar(self.layout_tabbar)

    def _sync_tab(self):
        self._fill_tabbar(self.tabbar)
        self._fill_tabbar(self.layout_tabbar)

    def _show_designer_view(self, designer):
        window = designer.window()
        try:
            self._ensure_layout_toolbar()
            if self.view_stack.indexOf(window) < 0:
                window.setParent(self.view_stack)
                self.view_stack.addWidget(window)
            self._map_strip_origin()
            if self._layout_toolbar_window is not window:
                if self._layout_toolbar_window is not None:
                    self._detach_layout_toolbar()
                top = qenum(Qt, "ToolBarArea", "TopToolBarArea")
                window.addToolBarBreak(top)
                window.addToolBar(top, self.layout_toolbar)
                self._layout_toolbar_window = window
            self.layout_toolbar.show()
            self._hide_main_chrome()
            self.view_stack.setCurrentWidget(window)
            window.show()
            self._active_designer = designer
            self._schedule_align(0)
        except RuntimeError:
            pass

    def _show_map_view(self, map_id=None):
        if self.view_stack is not None and self._main_central is not None:
            self.view_stack.setCurrentWidget(self._main_central)
        self._restore_main_chrome()
        self._active_designer = None
        QTimer.singleShot(500, self._map_strip_origin)
        QTimer.singleShot(1500, self._map_strip_origin)
        self.iface.mainWindow().show()
        if map_id and map_id != self.active_id and self._get(map_id) is not None:
            self.activate(map_id)

    def _hide_main_chrome(self):
        if self._main_chrome_visibility is not None:
            return
        win = self.iface.mainWindow()
        widgets = [win.menuBar(), win.statusBar()]
        widgets.extend(child for child in win.children()
                       if isinstance(child, (QToolBar, QDockWidget)))
        unique = []
        for widget in widgets:
            if self._is_layout_toolbar(widget):
                continue
            if widget not in unique:
                unique.append(widget)
        self._main_chrome_visibility = [(widget, widget.isVisible()) for widget in unique]
        for widget, _visible in self._main_chrome_visibility:
            widget.hide()

    def _restore_main_chrome(self):
        if self._main_chrome_visibility is None:
            return
        for widget, visible in self._main_chrome_visibility:
            try:
                widget.setVisible(visible)
            except RuntimeError:
                pass
        self._main_chrome_visibility = None
        self._hide_stray_layout_toolbars()

    def _replace_native_new_layout_action(self):
        """Conserva el botón/menu normal de QGIS, pero crea Layout con nombre automático."""
        try:
            getter = getattr(self.iface, "actionCreatePrintLayout", None)
            if getter is None:
                getter = getattr(self.iface, "actionNewPrintLayout", None)
            original = getter() if callable(getter) else getter
        except Exception:
            original = None
        if original is None:
            return
        self._native_new_layout_action = original
        self._native_new_layout_enabled = original.isEnabled()
        proxy = QAction(original.icon(), original.text(), self.iface.mainWindow())
        proxy.setToolTip(original.toolTip())
        proxy.setStatusTip(original.statusTip())
        proxy.setShortcut(original.shortcut())
        proxy.setShortcutContext(original.shortcutContext())
        proxy.triggered.connect(self.new_layout)
        self._new_layout_proxy = proxy
        containers = [self.iface.mainWindow().menuBar()]
        containers.extend(self.iface.mainWindow().findChildren(QMenu))
        containers.extend(self.iface.mainWindow().findChildren(QToolBar))
        for container in containers:
            actions = list(container.actions())
            if original not in actions:
                continue
            idx = actions.index(original)
            before = actions[idx + 1] if idx + 1 < len(actions) else None
            container.removeAction(original)
            if before is not None:
                container.insertAction(before, proxy)
            else:
                container.addAction(proxy)
            self._new_layout_action_hosts.append((container, before))
        if not self._new_layout_action_hosts:
            proxy.deleteLater()
            self._new_layout_proxy = None
            self._native_new_layout_action = None
            self._native_new_layout_enabled = None
            return
        original.setEnabled(False)

    def _restore_native_new_layout_action(self):
        original = self._native_new_layout_action
        proxy = self._new_layout_proxy
        if original is None or proxy is None:
            return
        for container, before in self._new_layout_action_hosts:
            try:
                container.removeAction(proxy)
                if before is not None and before in container.actions():
                    container.insertAction(before, original)
                else:
                    container.addAction(original)
            except RuntimeError:
                pass
        original.setEnabled(bool(self._native_new_layout_enabled))
        proxy.deleteLater()
        self._new_layout_action_hosts = []
        self._new_layout_proxy = None
        self._native_new_layout_action = None

    def _on_tab_changed(self, idx, bar=None):
        bar = bar or self.tabbar
        if idx < 0 or self._busy:
            return
        key = self._tab_key(idx, bar)
        self.active_view_key = key
        self._sync_tab()
        if key.startswith("layout:"):
            layout = self._layouts_by_key.get(key[7:])
            designer = self._designer_by_layout.get(id(layout)) if layout is not None else None
            if designer is not None:
                self._show_designer_view(designer)
            return
        mid = self._tab_id(idx, bar)
        self._show_map_view(mid)

    def _on_tab_detach(self, idx, global_pos, bar=None):
        """Al soltar una pestaña fuera de la barra, abre su vista en esa pantalla."""
        screens = QApplication.screens()
        if not screens:
            return
        screen = QApplication.screenAt(global_pos)
        if screen is None:
            screen = QApplication.primaryScreen() or screens[0]
        screen_index = screens.index(screen)
        key = self._tab_key(idx, bar)
        if key.startswith("layout:"):
            layout = self._layouts_by_key.get(key[7:])
            if layout is not None:
                self._move_layout_to_screen(layout, screen_index)
        elif key.startswith("map:"):
            self._open_floating_map(self._tab_id(idx, bar), screen_index)

    def _on_tab_moved(self, bar=None):
        order = self._current_view_order(bar)
        map_order = [key[4:] for key in order if key.startswith("map:")]
        self.maps.sort(key=lambda m: map_order.index(m["id"]) if m["id"] in map_order else len(map_order))
        hidden_layouts = [key for key in self._view_order
                          if key.startswith("layout:") and key not in order]
        self._view_order = order + hidden_layouts
        self._refresh_tabs()
        self._persist()

    def _on_tab_rename(self, idx, bar=None):
        """Doble clic: editor de texto sobre la pestana (Enter acepta, Esc cancela)."""
        key = self._tab_key(idx, bar) if idx >= 0 else ""
        layout = self._layouts_by_key.get(key[7:]) if key.startswith("layout:") else None
        m = self._get(self._tab_id(idx, bar)) if key.startswith("map:") else None
        if m is None and layout is None:
            return
        target_bar = bar or self.tabbar
        rect = target_bar.tabRect(idx)
        edit = TabNameEdit(target_bar)
        old_name = layout.name() if layout is not None else m["name"]
        edit.setText(old_name)
        edit.setGeometry(rect.adjusted(24, 1, -24, -1))
        state = {"done": False}

        def finish(commit):
            if state["done"]:
                return
            state["done"] = True
            new = edit.text().strip()
            edit.hide()
            edit.deleteLater()
            if commit and new and new != old_name:
                if layout is not None:
                    mgr = QgsProject.instance().layoutManager()
                    other = mgr.layoutByName(new)
                    if other is not None and other is not layout:
                        self._warn("Ya existe un Layout con ese nombre.")
                        return
                    layout.setName(new)
                    return  # nameChanged actualiza pestaña y estado
                m["name"] = new
                floating = self._map_windows.get(m["id"])
                if floating is not None:
                    floating.setWindowTitle("Multimapa — %s" % new)
                self._refresh_tabs()
                self._persist()
        
        edit.editingFinished.connect(lambda: finish(True))
        edit.cancelled.connect(lambda: finish(False))
        edit.show()
        edit.setFocus()
        edit.selectAll()

    def _restyle(self):
        """Iguala los colores de la barra al fondo real de QGIS (color mas frecuente de la
        fila de pixeles justo encima de la barra, para esquivar los iconos de las barras)."""
        try:
            if self.placer is None:
                return
            win = self.iface.mainWindow()
            origin = self.strip.mapTo(win, QPoint(0, 0))
            img = win.grab(QRect(origin.x(), max(origin.y() - 3, 0), self.strip.width(), 1)).toImage()
            counts = {}
            for x in range(img.width()):
                name = img.pixelColor(x, 0).name()
                counts[name] = counts.get(name, 0) + 1
            if not counts:
                return
            from qgis.PyQt.QtGui import QColor
            sample = QColor(max(counts, key=counts.get))
            if sample.lightness() < 8:      # no se pinto todavia
                return
            colors = style_colors(sample)
            self.tabbar.apply_colors(colors)
            self.strip.setStyleSheet(strip_stylesheet(colors))
            self.btn_add.setStyleSheet(add_button_stylesheet(colors))
            self.layout_tabbar.apply_colors(colors)
            self.layout_add_map.setStyleSheet(add_button_stylesheet(colors))
        except Exception as e:
            QgsMessageLog.logMessage("No se pudo igualar el color de la barra: %s" % e, "Multimap Layout")

    def _on_tab_context(self, pos, bar=None):
        """Menu contextual para pestañas de mapas y Layouts."""
        target_bar = bar or self.tabbar
        idx = target_bar.tabAt(pos)
        if idx < 0:
            return
        key = self._tab_key(idx, target_bar)
        menu = QMenu(target_bar)
        a_ren = menu.addAction("Renombrar")
        a_dup = None
        if key.startswith("map:"):
            a_dup = menu.addAction("Duplicar mapa")
            close_text = "Cerrar mapa"
        else:
            close_text = "Cerrar Layout"
        menu.addSeparator()
        a_close = menu.addAction(close_text)
        if key.startswith("layout:"):
            layout = self._layouts_by_key.get(key[7:])
            screens = QApplication.screens()
            if layout is not None and screens:
                screen_menu = menu.addMenu("Mover Layout a pantalla")
                for screen_index, screen in enumerate(screens):
                    label = "%d: %s" % (screen_index + 1, screen.name() or "Pantalla")
                    action = screen_menu.addAction(label)
                    action.triggered.connect(
                        lambda _checked=False, idx=screen_index, lay=layout:
                            self._move_layout_to_screen(lay, idx)
                    )
        elif key.startswith("map:"):
            map_id = self._tab_id(idx, target_bar)
            screens = QApplication.screens()
            screen_menu = menu.addMenu("Abrir mapa en pantalla")
            for screen_index, screen in enumerate(screens):
                label = "%d: %s" % (screen_index + 1, screen.name() or "Pantalla")
                action = screen_menu.addAction(label)
                action.triggered.connect(
                    lambda _checked=False, n=screen_index, mid=map_id:
                        self._open_floating_map(mid, n)
                )
            floating = self._map_windows.get(map_id)
            if floating is not None:
                a_return = menu.addAction("Volver al mapa principal")
                a_return.triggered.connect(
                    lambda _checked=False, mid=map_id: self._close_floating_map(mid, activate=True)
                )
        run = getattr(menu, "exec", None) or menu.exec_
        chosen = run(target_bar.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is a_ren:
            self._on_tab_rename(idx, target_bar)
        elif a_dup is not None and chosen is a_dup:
            mid = self._tab_id(idx, target_bar)
            if mid != self.active_id and self._get(mid) is not None:
                self.activate(mid)
            self.duplicate_map()
        elif chosen is a_close:
            self._on_tab_close(idx, target_bar)

    def _move_layout_to_screen(self, layout, screen_index):
        designer = self._designer_by_layout.get(id(layout))
        screens = QApplication.screens()
        if designer is None or screen_index < 0 or screen_index >= len(screens):
            return
        try:
            window = designer.window()
            window.showNormal()
            frame = window.frameGeometry()
            area = screens[screen_index].availableGeometry()
            frame.moveCenter(area.center())
            window.move(frame.topLeft())
            window.show()
            window.raise_()
            window.activateWindow()
        except RuntimeError:
            pass

    def _map_tree_items(self, map_id):
        if map_id == self.active_id:
            return self._capture(self._active_nodes())
        return self.stored.get(map_id, [])

    def _fill_floating_tree(self, items, parent):
        for item in items:
            if item.get("t") == "g":
                group = parent.addGroup(item.get("name", ""))
                group.setItemVisibilityChecked(bool(item.get("on", True)))
                group.setExpanded(bool(item.get("exp", True)))
                self._fill_floating_tree(item.get("ch", []), group)
            else:
                layer = self._layer(item.get("id", ""))
                if layer is not None:
                    node = parent.addLayer(layer)
                    node.setItemVisibilityChecked(bool(item.get("on", True)))

    def _open_floating_map(self, map_id, screen_index):
        map_info = self._get(map_id)
        screens = QApplication.screens()
        if map_info is None or not (0 <= screen_index < len(screens)):
            return
        window = self._map_windows.get(map_id)
        if window is not None:
            window.showNormal()
            window.raise_()
            window.activateWindow()
            return
        root = QgsLayerTree()
        root.setName(map_info["name"])
        self._fill_floating_tree(self._map_tree_items(map_id), root)
        window = MapViewWindow(self, map_info, root, screens[screen_index].availableGeometry())
        self._map_windows[map_id] = window
        window.show()

    def _close_floating_map(self, map_id, activate=False):
        window = self._map_windows.get(map_id)
        if window is not None:
            window.close()
        if activate and self._get(map_id) is not None:
            self.activate(map_id)

    def _on_floating_map_closed(self, map_id, window):
        if self._map_windows.get(map_id) is window:
            self._map_windows.pop(map_id, None)

    def _on_floating_tree_changed(self, map_id, root):
        if self._syncing_floating:
            return
        state = self._capture(root.children())
        if map_id == self.active_id:
            # La ventana flotante tiene su propio modelo de árbol. Mantener solo
            # la visibilidad sincronizada dejaba fuera altas, bajas, grupos y orden.
            # Reemplazamos la estructura real del mapa activo y conservamos los
            # nodos privados que mantienen vivas las capas de los otros mapas.
            self._busy = True
            try:
                self._replace_active_tree(state)
                self._apply_privacy()
            finally:
                self._busy = False
        else:
            self.stored[map_id] = state
        self._refresh_bound_layout_items(map_id)
        self._persist()

    def _replace_active_tree(self, state):
        """Aplica al arbol canonico del proyecto toda la estructura de un mapa."""
        root = self._root()
        layers, seen = [], set()
        for node in self._active_nodes():
            for layer_node in self._layer_nodes(node):
                layer = layer_node.layer()
                if layer is not None and layer.id() not in seen:
                    seen.add(layer.id())
                    layers.append(layer)
        old_ids = [layer.id() for layer in layers]
        for layer in layers:                  # se sacan del registro (conservan sus datos) mientras se reconstruye
            self._hide_layer(layer)
        for node in list(self._active_nodes()):
            root.removeChildNode(node)
        built = self._build(state, root)
        other_map_ids = set()
        for other_id, items in self.stored.items():
            if other_id != self.active_id:
                other_map_ids.update(self._struct_layer_ids(items))
        # Las capas retiradas del mapa solo se conservan si todavia pertenecen a otro mapa.
        self._drop_layers([i for i in old_ids if i not in built and i not in other_map_ids])

    def _apply_tree_state(self, items, nodes):
        for item, node in zip(items, nodes):
            if item.get("t") == "g" and QgsLayerTree.isGroup(node):
                node.setItemVisibilityChecked(bool(item.get("on", True)))
                self._apply_tree_state(item.get("ch", []), node.children())
            elif item.get("t") == "l" and QgsLayerTree.isLayer(node):
                node.setItemVisibilityChecked(bool(item.get("on", True)))

    def _on_floating_extent_changed(self, map_id, extent):
        map_info = self._get(map_id)
        if map_info is None:
            return
        map_info["extent"] = self._rect_to_list(extent)
        if map_id == self.active_id and not self._syncing_floating:
            self._syncing_floating = True
            try:
                self.canvas.setExtent(extent)
                self.canvas.refresh()
            finally:
                self._syncing_floating = False
        self._persist()

    def _on_floating_crs_changed(self, map_id, crs):
        map_info = self._get(map_id)
        if map_info is None or not crs.isValid():
            return
        if self._syncing_floating:
            return
        # QgsMapCanvas ligado al proyecto puede recibir el CRS global aunque
        # represente un mapa inactivo. Ese cambio pertenece al mapa principal;
        # no debe sobrescribir el CRS propio de esta ventana.
        if map_id != self.active_id and crs == QgsProject.instance().crs():
            for delay in (0, 120, 400):
                QTimer.singleShot(delay, self._restore_floating_map_crs)
            return
        map_info["crs"] = self._crs_str(crs)
        if map_id == self.active_id:
            self._syncing_floating = True
            try:
                self.canvas.setDestinationCrs(crs)
                self.canvas.refresh()
            finally:
                self._syncing_floating = False
        self._refresh_bound_layout_items(map_id)
        self._persist()

    def _on_project_crs_changed(self, *_):
        # El selector CRS estándar de QGIS modifica el CRS global. Deja que el
        # lienzo principal lo procese y luego restaura en cada ventana flotante
        # la proyección guardada para su propio mapa.
        # QGIS propaga el cambio a canvases enlazados al proyecto después de
        # emitir crsChanged; varios intentos escalonados evitan que esa
        # propagación tardía vuelva a pisar el CRS particular de cada ventana.
        for delay in (0, 120, 400):
            QTimer.singleShot(delay, self._restore_floating_map_crs)

    def _restore_floating_map_crs(self):
        if self._syncing_floating:
            return
        self._syncing_floating = True
        try:
            for map_id, window in list(self._map_windows.items()):
                map_info = self._get(map_id)
                if map_info is None:
                    continue
                if map_id == self.active_id:
                    crs = self.canvas.mapSettings().destinationCrs()
                    extent = self.canvas.extent()
                else:
                    crs = self._crs_from(map_info["crs"])
                    extent = QgsRectangle(*map_info["extent"])
                if crs.isValid() and window.canvas.mapSettings().destinationCrs() != crs:
                    window.canvas.setDestinationCrs(crs)
                window.canvas.setExtent(extent)
                window.canvas.refresh()
        finally:
            self._syncing_floating = False

    def _sync_floating_from_main(self):
        if self._syncing_floating:
            return
        window = self._map_windows.get(self.active_id)
        if window is None:
            return
        self._syncing_floating = True
        try:
            extent = self.canvas.extent()
            crs = self.canvas.mapSettings().destinationCrs()
            info = self._get(self.active_id)
            if info is not None:
                info["extent"] = self._rect_to_list(extent)
                info["crs"] = self._crs_str(crs)
            if window.canvas.mapSettings().destinationCrs() != crs:
                window.canvas.setDestinationCrs(crs)
            window.canvas.setExtent(extent)
        finally:
            self._syncing_floating = False

    def _sync_floating_visibility_from_main(self, *_):
        if self._syncing_floating:
            return
        window = self._map_windows.get(self.active_id)
        if window is None:
            return
        self._syncing_floating = True
        try:
            # Sincronizar el árbol completo (incluye capas nuevas, grupos y orden),
            # no solo el check de visibilidad.
            for node in list(window.root.children()):
                window.root.removeChildNode(node)
            self._fill_floating_tree(self._capture(self._active_nodes()), window.root)
            window.bridge.setCanvasLayers()
            window.canvas.refresh()
        finally:
            self._syncing_floating = False

    def _on_main_layer_tree_changed(self, *_):
        if self._busy or self._loading:
            return
        self._sync_floating_visibility_from_main()
        self._refresh_bound_layout_items(self.active_id)

    def _refresh_bound_layout_items(self, map_id=None):
        """Mantiene automáticamente capas y leyendas enlazadas a cada mapa."""
        if not self.maps:
            return
        target_ids = {map_id} if map_id else {m["id"] for m in self.maps}
        manager = QgsProject.instance().layoutManager()
        for layout in manager.layouts():
            for item in self._layout_items(layout):
                mid = str(item.customProperty(PROP, "") or "")
                if mid not in target_ids:
                    continue
                map_info = self._get(mid)
                if map_info is None:
                    continue
                layers = self._visible_layers_of(mid)
                if isinstance(item, QgsLayoutItemMap):
                    current_ids = [layer.id() for layer in item.layers()]
                    wanted_ids = [layer.id() for layer in layers]
                    crs = self._crs_from(map_info["crs"])
                    if current_ids != wanted_ids or (crs.isValid() and item.crs() != crs):
                        self._bind_map_item(item, map_info, zoom=False)
                elif isinstance(item, QgsLayoutItemLegend):
                    root = item.model().rootGroup()
                    current_ids = [node.layerId() for node in root.findLayers()]
                    wanted_ids = [layer.id() for layer in layers]
                    if current_ids != wanted_ids:
                        self._bind_legend(item, map_info)

    def _on_tab_close(self, idx, bar=None):
        key = self._tab_key(idx, bar) if idx >= 0 else ""
        if key.startswith("layout:"):
            layout = self._layouts_by_key.get(key[7:])
            designer = self._designer_by_layout.get(id(layout)) if layout is not None else None
            if designer is not None:
                try:
                    designer.window().close()
                except RuntimeError:
                    pass
            return  # QGIS quita la pestaña al confirmar el cierre; si se cancela, queda abierta.
        m = self._get(self._tab_id(idx, bar)) if idx >= 0 else None
        if m is None:
            return
        if len(self.maps) <= 1:
            self._warn("No se puede cerrar el único mapa.")
            return
        resp = QMessageBox.question(
            self.iface.mainWindow(),
            "Cerrar mapa",
            "Se eliminará el mapa «%s» y sus capas del proyecto. ¿Continuar?" % m["name"],
            qenum(QMessageBox, "StandardButton", "Yes") | qenum(QMessageBox, "StandardButton", "No"),
        )
        if resp != qenum(QMessageBox, "StandardButton", "Yes"):
            return
        self._close_floating_map(m["id"])
        pos = self.maps.index(m)
        if m["id"] == self.active_id:
            neighbor = self.maps[pos + 1] if pos + 1 < len(self.maps) else self.maps[pos - 1]
            if not self.activate(neighbor["id"], save_view=False):   # 'm' pasa a inactivo
                return                                              # (cancelo por capas en edicion)
        ids = [i for i in self._struct_layer_ids(self.stored.pop(m["id"], [])) if i]
        self.maps.remove(m)
        self._drop_layers(ids)                                # esten en el registro o en el almacen
        self._refresh_tabs()
        self._persist()

    # --------------------------------------------------------------- maps
    def _ensure_init(self, persist=True):
        """Garantiza que exista al menos 'Mapa 1' (adopta todo lo que haya en el arbol)."""
        if self.maps:
            return
        crs, ext = self._current_view()
        m = self._new_map("Mapa 1", crs, ext)
        self.maps.append(m)
        self.active_id = m["id"]
        self._refresh_tabs()
        self._apply_privacy()
        if persist:
            self._persist()

    def add_map(self, *_):
        self._ensure_init()
        self._save_view()
        crs, ext = self._current_view()
        m = self._new_map(self._next_name(), crs, ext)
        self.maps.append(m)
        self.stored[m["id"]] = []
        self._refresh_tabs()
        self.activate(m["id"], restore_view=False)

    # --------------------------------------------------- copia de capas
    @staticmethod
    def _is_memory(lyr):
        return isinstance(lyr, QgsVectorLayer) and lyr.providerType() == "memory"

    def _clone_memory(self, lyr):
        """Capa temporal (memoria): clone() no copia los datos, asi que se copian a mano."""
        pf = lyr.dataProvider().fields()
        try:
            c = QgsMemoryProviderUtils.createMemoryLayer(lyr.name(), pf, lyr.wkbType(), lyr.crs(), False)
        except TypeError:   # versiones sin el parametro loadDefaultStyle
            c = QgsMemoryProviderUtils.createMemoryLayer(lyr.name(), pf, lyr.wkbType(), lyr.crs())
        if c is None or not c.isValid():
            return None
        cf = c.fields()
        names = [cf.at(i).name() for i in range(cf.count())]
        feats = []
        for f in lyr.getFeatures():       # incluye los cambios aun sin guardar
            nf = QgsFeature(cf)
            nf.setGeometry(f.geometry())
            for i, n in enumerate(names):
                nf.setAttribute(i, f.attribute(n))
            feats.append(nf)
        if feats:
            c.dataProvider().addFeatures(feats)
        c.updateExtents()
        keep = lyr.customProperty("skipMemoryLayersCheck", None)
        if keep is not None:              # que no avise al guardar si el original tampoco avisa
            c.setCustomProperty("skipMemoryLayersCheck", keep)
        return c

    @staticmethod
    def _copy_subset(src, dst):
        """Filtro (constructor de consultas) de la capa original."""
        try:
            sub = src.subsetString()
        except AttributeError:
            return      # solo las capas vectoriales tienen filtro
        if sub and dst.subsetString() != sub:
            if not dst.setSubsetString(sub):
                QgsMessageLog.logMessage(
                    "No se pudo copiar el filtro de «%s»: %s" % (src.name(), sub), "Multimap Layout"
                )

    def _clone_layer(self, lyr):
        """Copia independiente de una capa: origen (o datos, si es temporal) y filtro.
        Las uniones y el estilo se aplican despues, en _clone_set. Devuelve None si falla."""
        try:
            c = self._clone_memory(lyr) if self._is_memory(lyr) else lyr.clone()
        except Exception as e:
            QgsMessageLog.logMessage("No se pudo copiar «%s»: %s" % (lyr.name(), e), "Multimap Layout")
            return None
        if c is None:
            return None
        c.setName(lyr.name())
        self._copy_subset(lyr, c)
        QgsProject.instance().addMapLayer(c, False)
        return c

    @staticmethod
    def _copy_joins(orig, c, idmap):
        """Las uniones de la copia se rehacen desde la original; si la tabla unida tambien
        se copio, la union apunta a SU copia (asi cada mapa queda independiente)."""
        if not (isinstance(orig, QgsVectorLayer) and isinstance(c, QgsVectorLayer)):
            return
        for j in list(c.vectorJoins()):
            c.removeJoin(j.joinLayerId())
        for j in orig.vectorJoins():        # 'j' es una copia: se puede modificar
            tid = j.joinLayerId()
            if tid in idmap:
                j.setJoinLayer(idmap[tid])
            c.addJoin(j)

    @staticmethod
    def _copy_style(orig, c):
        try:
            style = QgsMapLayerStyle()
            style.readFromLayer(orig)
            style.writeToLayer(c)
        except Exception:
            pass

    @staticmethod
    def _is_virtual(lyr):
        return isinstance(lyr, QgsVectorLayer) and lyr.providerType() == "virtual"

    @staticmethod
    def _virtual_refs(lyr):
        """Ids de las capas del proyecto que usa una capa virtual (layer_ref=<id>:<nombre>)."""
        try:
            d = QgsVirtualLayerDefinition.fromUrl(QUrl.fromEncoded(lyr.source().encode("utf-8")))
            return [sl.reference() for sl in d.sourceLayers() if sl.isReferenced()]
        except Exception:
            import re
            return re.findall(r"layer_ref=([^:&]+)", lyr.source())

    def _clone_virtual(self, v, idmap):
        """Capa virtual: se reescriben sus referencias para que apunten a las copias."""
        src = v.source()
        for oid in self._virtual_refs(v):
            if oid in idmap:
                src = src.replace(oid, idmap[oid].id())
        try:
            c = QgsVectorLayer(src, v.name(), "virtual")
        except Exception:
            return None
        if c is None or not c.isValid():
            return None
        QgsProject.instance().addMapLayer(c, False)
        return c

    def _clone_set(self, layers):
        """Clona varias capas a la vez, junto con las tablas de sus uniones y las capas que
        usan las capas virtuales. Devuelve (idmap, extras, fallidas): idmap = id original ->
        copia; extras = copias de capas auxiliares que no estaban en 'layers'."""
        prj = QgsProject.instance()
        idmap, pairs, extras, failed = {}, [], [], []
        virt = {}               # capas virtuales: se copian al final, cuando ya existen sus capas
        todo = [(lyr, False) for lyr in layers]
        while todo:
            lyr, is_extra = todo.pop(0)
            if lyr.id() in idmap or lyr.id() in virt:
                continue
            if self._is_virtual(lyr):
                virt[lyr.id()] = (lyr, is_extra)
                deps = self._virtual_refs(lyr)
            else:
                c = self._clone_layer(lyr)
                if c is None:
                    failed.append(lyr.name())
                    continue
                idmap[lyr.id()] = c
                pairs.append((lyr, c))
                if is_extra:
                    extras.append(c)
                deps = [j.joinLayerId() for j in lyr.vectorJoins()] if isinstance(lyr, QgsVectorLayer) else []
            for did in deps:
                t = self._layer(did)
                if t is not None and t.id() not in idmap and t.id() not in virt:
                    todo.append((t, True))
        pending = dict(virt)    # cada virtual va despues de las capas (o virtuales) que usa
        while pending:
            ready = [vid for vid, (v, _e) in pending.items()
                     if not any(r in pending for r in self._virtual_refs(v))]
            if not ready:       # dependencia circular
                failed.extend(v.name() for v, _e in pending.values())
                break
            for vid in ready:
                v, is_extra = pending.pop(vid)
                c = self._clone_virtual(v, idmap)
                if c is None:
                    failed.append(v.name())
                    continue
                idmap[vid] = c
                pairs.append((v, c))
                if is_extra:
                    extras.append(c)
        for orig, c in pairs:       # primero las uniones (ya existen todas las copias)...
            self._copy_joins(orig, c, idmap)
        for orig, c in pairs:       # ...y despues el estilo (puede usar campos unidos)
            self._copy_style(orig, c)
        return idmap, extras, failed

    def _report_copy(self, extras, failed):
        if failed:
            self._warn("No se pudieron copiar: %s." % ", ".join(failed))
        if extras:
            self._ok(
                "También se copiaron las tablas de unión: %s (sin marcar en el mapa destino)."
                % ", ".join(c.name() for c in extras)
            )

    def duplicate_map(self, *_):
        if not self.active_id:
            self._warn("No hay un mapa activo para duplicar.")
            return
        src = self._get(self.active_id)
        self._save_view()
        nodes = self._active_nodes()
        struct = self._capture(nodes)
        layers, seen = [], set()
        for n in nodes:
            for ln in self._layer_nodes(n):
                lyr = ln.layer()
                if lyr is not None and lyr.id() not in seen:
                    seen.add(lyr.id())
                    layers.append(lyr)
        self._busy = True
        try:
            idmap, extras, failed = self._clone_set(layers)
            for c in idmap.values():
                self._add_flat(c)
        finally:
            self._busy = False
        new_struct = self._remap(struct, idmap)
        for c in extras:    # tablas de union: pertenecen al mapa nuevo, sin marcar
            new_struct.append({"t": "l", "id": c.id(), "on": False})
        m = self._new_map(src["name"] + " (copia)", src["crs"], list(src["extent"]))
        m["rot"] = float(src.get("rot", 0.0))
        self.maps.append(m)
        self.stored[m["id"]] = new_struct
        self._refresh_tabs()
        self.activate(m["id"], restore_view=False)
        self._report_copy(extras, failed)

    def _set_project_crs(self, crs):
        """El CRS del proyecto sigue al de la pestana activa: asi la barra de estado de QGIS, el
        selector de CRS y el proyecto guardado coinciden siempre con lo que se ve en el lienzo."""
        project = QgsProject.instance()
        try:
            if project.crs() == crs:
                return
            was_dirty = project.isDirty()
            project.setCrs(crs)
            if self._quiet_crs and not was_dirty:   # al abrir un proyecto no debe quedar "modificado"
                project.setDirty(False)
        except Exception as e:
            self._log("No se pudo ajustar el CRS del proyecto: %s" % e)

    def activate(self, map_id, restore_view=True, save_view=True, persist=True, swap=True):
        m = self._get(map_id)
        if m is None:
            return False
        if swap and self.active_id and self.active_id != map_id and not self._release_edits(self._active_layers()):
            self._sync_tab()          # el usuario cancelo: la pestana vuelve al mapa activo
            return False
        self._busy = True
        self.canvas.freeze(True)          # sin redibujados intermedios durante el intercambio
        try:
            if swap and self.active_id and self.active_id != map_id:
                if save_view:
                    self._save_view()
                self._stash_active()
                self._restore(map_id)
            self.active_id = map_id
            self._apply_privacy()
            if restore_view:
                crs = self._crs_from(m["crs"])
                if crs.isValid():
                    # El CRS del proyecto sigue al de la pestana activa; el lienzo lo hereda.
                    self._set_project_crs(crs)
                    if crs != self.canvas.mapSettings().destinationCrs():
                        self.canvas.setDestinationCrs(crs)
                try:
                    self.canvas.setRotation(float(m.get("rot", 0.0)))
                except Exception:
                    pass
                self.canvas.setExtent(QgsRectangle(*m["extent"]))
            self._sync_tab()
        finally:
            self.canvas.freeze(False)
            self.canvas.refresh()
            self._busy = False
        # Al sacar capas del registro QGIS hace que los elementos de layout las suelten: se
        # vuelven a enlazar los de TODOS los mapas (los del recien ocultado quedaron vacios).
        self._refresh_bound_layout_items()
        if persist:
            self._persist()
        return True

    # ----------------------------------------------- copiar / mover capas
    def _selected_layers(self):
        view = self.iface.layerTreeView()
        layers = []
        try:
            layers = list(view.selectedLayersRecursive())
        except Exception:
            try:
                layers = list(view.selectedLayers())
            except Exception:
                layers = []
        if not layers:
            cur = self.iface.activeLayer()
            if cur is not None:
                layers = [cur]
        return layers

    def copy_selected_layers(self, *_):
        self._send_layers(move=False)

    def move_selected_layers(self, *_):
        self._send_layers(move=True)

    def _send_layers(self, move):
        layers = self._selected_layers()
        if not layers or not self.active_id:
            self._warn("Selecciona una o más capas del mapa activo.")
            return
        target_id = self._pick_map(
            "Mover capa" if move else "Copiar capa", "Mapa de destino:", exclude=self.active_id
        )
        if not target_id:
            return
        if move and not self._release_edits(layers):
            return
        target = self.stored.setdefault(target_id, [])
        root = self._root()
        count = 0
        extras, failed = [], []
        self._busy = True
        try:
            if move:
                for lyr in layers:
                    self._add_flat(lyr)                    # primero el nodo plano...
                    for n in list(root.findLayers()):      # ...luego se quitan los activos
                        if n.layerId() == lyr.id() and not n.customProperty(FLAT, ""):
                            n.parent().removeChildNode(n)
                    target.insert(0, {"t": "l", "id": lyr.id(), "on": True})
                    count += 1
            else:
                idmap, extras, failed = self._clone_set(layers)
                for c in idmap.values():
                    self._add_flat(c)
                for lyr in layers:
                    c = idmap.get(lyr.id())
                    if c is not None:
                        target.insert(0, {"t": "l", "id": c.id(), "on": True})
                        count += 1
                for c in extras:    # tablas de union copiadas: sin marcar
                    target.append({"t": "l", "id": c.id(), "on": False})
            self._apply_privacy()
        finally:
            self._busy = False
        self._refresh_bound_layout_items(target_id)
        self._persist()
        tm = self._get(target_id)
        self._ok("%d capa(s) %s a «%s»." % (count, "movida(s)" if move else "copiada(s)", tm["name"]))
        if not move:
            self._report_copy(extras, failed)

    # -------------------------------------------------------------- layouts
    def new_layout(self, *_):
        """Crea un Layout vacío, lo registra en el proyecto y abre su diseñador QGIS."""
        project = QgsProject.instance()
        manager = project.layoutManager()
        base, name, n = "Layout", "Layout", 2
        while manager.layoutByName(name) is not None:
            name = "%s %d" % (base, n)
            n += 1
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(name)
        if not manager.addLayout(layout):
            self._warn("No se pudo crear el Layout.")
            return
        self._mark_project_dirty()
        self.iface.openLayoutDesigner(layout)

    def _visible_from_nodes(self, nodes):
        out = []
        for c in nodes:
            if QgsLayerTree.isGroup(c):
                if c.itemVisibilityChecked():
                    out.extend(self._visible_from_nodes(c.children()))
            elif QgsLayerTree.isLayer(c):
                if c.itemVisibilityChecked() and c.layer() is not None:
                    out.append(c.layer())
        return out

    def _visible_from_struct(self, items):
        out = []
        for it in items:
            if it.get("t") == "g":
                if it.get("on", True):
                    out.extend(self._visible_from_struct(it.get("ch", [])))
            elif it.get("on", True):
                lyr = self._layer(it.get("id", ""))
                if lyr is not None:
                    out.append(lyr)
        return out

    def _visible_layers_of(self, map_id):
        """Capas visibles de un mapa (activo o inactivo), de arriba hacia abajo."""
        if map_id == self.active_id:
            return self._visible_from_nodes(self._active_nodes())
        return self._visible_from_struct(self.stored.get(map_id, []))

    def _bind_map_item(self, mi, m, zoom=True):
        """Configura un elemento de mapa del layout con las capas/CRS/extension del mapa m."""
        layers = self._visible_layers_of(m["id"])
        crs = self._crs_from(m["crs"])
        # Un mapa que sigue un tema ignora setLayers() y termina mostrando el
        # lienzo/proyecto actual. El enlace del complemento debe ser la única
        # fuente de capas para este elemento.
        for setter_name in ("setFollowVisibilityPreset", "setFollowMapTheme"):
            setter = getattr(mi, setter_name, None)
            if callable(setter):
                try:
                    setter(False)
                except Exception:
                    pass
        if crs.isValid():
            mi.setCrs(crs)
        mi.setKeepLayerSet(True)
        mi.setLayers(layers)
        mi.setCustomProperty(PROP, m["id"])
        mi.removeCustomProperty(SKIP)
        if zoom:
            ext = QgsRectangle(*m["extent"])
            if not ext.isEmpty():
                mi.zoomToExtent(ext)
        try:
            mi.invalidateCache()
        except Exception:
            pass

    def _bind_legend(self, lg, m):
        """Leyenda manual con las capas visibles del mapa m."""
        layers = self._visible_layers_of(m["id"])
        lg.setAutoUpdateModel(False)
        root = lg.model().rootGroup()
        root.removeAllChildren()
        for lyr in layers:
            root.addLayer(lyr)
        lg.setCustomProperty(PROP, m["id"])
        lg.removeCustomProperty(SKIP)
        try:
            lg.adjustBoxSize()
            lg.invalidateCache()
        except Exception:
            pass

    def _bind_item(self, it, m, zoom=True):
        if isinstance(it, QgsLayoutItemMap):
            self._bind_map_item(it, m, zoom)
        elif isinstance(it, QgsLayoutItemLegend):
            self._bind_legend(it, m)

    def _unbind_item(self, it):
        it.removeCustomProperty(PROP)
        it.setCustomProperty(SKIP, "1")
        if isinstance(it, QgsLayoutItemMap):
            it.setKeepLayerSet(False)
            it.setLayers([])
        elif isinstance(it, QgsLayoutItemLegend):
            it.setAutoUpdateModel(True)
        try:
            it.invalidateCache()
        except Exception:
            pass

    def create_layout(self, *_):
        if not self.maps:
            self._warn("Primero crea al menos un mapa.")
            return
        self._save_view()
        project = QgsProject.instance()
        mgr = project.layoutManager()
        default = "Multimapa"
        dlg = LayoutDialog(self.iface.mainWindow(), self.maps, default)
        run = getattr(dlg, "exec", None) or dlg.exec_
        if not run():
            return
        ids = dlg.selected_ids()
        chosen = [m for m in self.maps if m["id"] in ids]
        if not chosen:
            self._warn("No marcaste ningún mapa.")
            return
        name = dlg.name() or default
        base, i = name, 2
        while mgr.layoutByName(name) is not None:
            name = "%s %d" % (base, i)
            i += 1

        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(name)
        mgr.addLayout(layout)
        self._mark_project_dirty()

        size = layout.pageCollection().page(0).pageSize()
        pw, ph = size.width(), size.height()
        margin, gap = 10.0, 6.0
        title_h = 7.0 if dlg.with_titles() else 0.0
        n = len(chosen)
        cols = 1 if n == 1 else int(math.ceil(math.sqrt(n)))
        rows = int(math.ceil(n / float(cols)))
        cell_w = (pw - 2 * margin - gap * (cols - 1)) / cols
        cell_h = (ph - 2 * margin - gap * (rows - 1)) / rows
        map_h = cell_h - title_h

        for k, m in enumerate(chosen):
            r, c = divmod(k, cols)
            x = margin + c * (cell_w + gap)
            y = margin + r * (cell_h + gap)

            if dlg.with_titles():
                lab = QgsLayoutItemLabel(layout)
                lab.setText(m["name"])
                lab.setCustomProperty(PROP, m["id"])
                layout.addLayoutItem(lab)
                lab.attemptMove(QgsLayoutPoint(x, y, MM))
                lab.attemptResize(QgsLayoutSize(cell_w, title_h, MM))

            mi = QgsLayoutItemMap(layout)
            layout.addLayoutItem(mi)
            mi.attemptMove(QgsLayoutPoint(x, y + title_h, MM))
            mi.attemptResize(QgsLayoutSize(cell_w, map_h, MM))
            mi.setFrameEnabled(True)
            self._bind_map_item(mi, m)

            if dlg.with_legends():
                lg = QgsLayoutItemLegend(layout)
                layout.addLayoutItem(lg)
                lg.setTitle("")
                self._bind_legend(lg, m)
                bottom = y + title_h + map_h - 2.0
                ref = _ref_lower_left()
                placed = False
                if ref is not None:
                    try:
                        lg.setReferencePoint(ref)
                        placed = True
                    except Exception:
                        pass
                if not placed:      # sin punto de referencia: se resta el alto a mano
                    bottom -= lg.rect().height()
                lg.attemptMove(QgsLayoutPoint(x + 2.0, bottom, MM))
                try:
                    lg.setFrameEnabled(True)
                except Exception:
                    pass

        self.iface.openLayoutDesigner(layout)
        self._ok("Layout «%s» creado con %d mapa(s)." % (name, n))

    # ------------------------------------------------- disenador de layouts
    def _designers(self):
        try:
            return list(self.iface.openLayoutDesigners())
        except Exception:
            return []

    @staticmethod
    def _layout_items(layout):
        return [it for it in layout.items() if isinstance(it, QgsLayoutItem)]

    def _on_designer_opened(self, designer):
        try:
            menu = designer.layoutMenu()
            if self.act_assign not in menu.actions():
                menu.addAction(self.act_assign)
        except Exception:
            pass
        try:
            layout = designer.layout()
        except Exception:
            return
        if layout is None:
            return
        self._designer_by_layout[id(layout)] = designer
        key = layout.name()
        self._layouts_by_key[key] = layout
        if id(layout) not in self._layout_name_slots:
            try:
                slot = lambda name, lay=layout: self._on_layout_name_changed(lay, name)
                layout.nameChanged.connect(slot)
                self._layout_name_slots[id(layout)] = (layout, slot)
            except Exception:
                pass
        self._refresh_tabs()
        self.active_view_key = "layout:" + layout.name()
        tab_index = next((i for i in range(self.tabbar.count())
                          if self._tab_key(i, self.tabbar) == self.active_view_key), -1)
        if tab_index >= 0:
            self.tabbar.setCurrentIndex(tab_index)
        self._fill_tabbar(self.layout_tabbar)
        self._show_designer_view(designer)
        self._watch_layout(layout)
        self._patch_add_map(designer, layout)
        self._offer_bind_legacy(designer, layout)

    def _on_layout_name_changed(self, layout, name):
        old_keys = [key for key, value in self._layouts_by_key.items() if value is layout]
        old_key = "layout:" + old_keys[0] if old_keys else None
        for key in old_keys:
            self._layouts_by_key.pop(key, None)
        self._layouts_by_key[name] = layout
        if old_key and old_key in self._view_order:
            self._view_order[self._view_order.index(old_key)] = "layout:" + name
        if old_key:
            if self.active_view_key == old_key:
                self.active_view_key = "layout:" + name
        self._mark_project_dirty()
        self._refresh_tabs()
        self._persist()

    def _on_designer_will_close(self, designer):
        """QGIS solo emite esta señal cuando el cierre, incluido el aviso de guardado, sigue adelante."""
        try:
            layout = designer.layout()
        except RuntimeError:
            return
        if layout is None:
            return
        self._cancel_deferred_layout_binds(layout)
        window = designer.window()
        if self._active_designer is designer:
            self.active_view_key = "map:" + str(self.active_id) if self.active_id else None
            self._show_map_view(self.active_id)
        if self._layout_toolbar_window is window:
            self._detach_layout_toolbar(window)
        if self.view_stack is not None:
            try:
                self.view_stack.removeWidget(window)
            except RuntimeError:
                pass
        self._designer_by_layout.pop(id(layout), None)
        self._patched.pop(id(layout), None)
        slot_entry = self._layout_name_slots.pop(id(layout), None)
        if slot_entry is not None:
            try:
                slot_entry[0].nameChanged.disconnect(slot_entry[1])
            except Exception:
                pass
        dirty_entry = self._layout_dirty_slots.pop(id(layout), None)
        if dirty_entry is not None:
            for signal, slot in dirty_entry[1]:
                try:
                    signal.disconnect(slot)
                except Exception:
                    pass
        self._watched.discard(id(layout))
        self._seen.pop(id(layout), None)
        try:
            for item in self._layout_items(layout):
                watched = self._watched_item_slots.pop(id(item), None)
                if watched is not None:
                    watched[1].disconnect(watched[2])
        except RuntimeError:
            pass
        keys = [key for key, value in self._layouts_by_key.items() if value is layout]
        for key in keys:
            self._layouts_by_key.pop(key, None)
            view_key = "layout:" + key
            if view_key in self._view_order:
                self._view_order.remove(view_key)
        self._refresh_tabs()
        self._persist()

    # --- "Anadir Mapa" convertido en una lista con los mapas del proyecto
    def _find_add_map_action(self, win):
        try:
            from qgis.gui import QgsGui
            mid = QgsGui.layoutItemGuiRegistry().metadataIdForItemType(_map_item_type())
        except Exception:
            mid = None
        actions = win.findChildren(QAction)
        if mid is not None:
            for a in actions:
                if a.isCheckable() and a.data() is not None and a.data() == mid:
                    return a
        for a in actions:
            if a.text().replace("&", "").strip().lower() in ("add map", "añadir mapa"):
                return a
        return None

    def _patch_add_map(self, designer, layout):
        key = id(layout)
        if key in self._patched:
            return
        try:
            win = designer.window()
            action = self._find_add_map_action(win)
            if action is None:
                return
            menu = QMenu(win)
            menu.aboutToShow.connect(lambda: self._fill_add_map_menu(menu, layout, action))
            action.setMenu(menu)
            self._patched[key] = (action, menu)
        except Exception:
            pass

    def _fill_add_map_menu(self, menu, layout, action):
        menu.clear()
        for m in self.maps:
            label = m["name"] + ("  (activo)" if m["id"] == self.active_id else "")
            a = menu.addAction(label)
            a.triggered.connect(lambda _c=False, mid=m["id"]: self._start_add_map(layout, action, mid))
        if self.maps:
            menu.addSeparator()
        a = menu.addAction("Sin enlazar (usar las capas del proyecto)")
        a.triggered.connect(lambda _c=False: self._start_add_map(layout, action, NONE))

    def _start_add_map(self, layout, action, map_id):
        # La herramienta nativa toma el estado del lienzo al comenzar. Activar
        # temporalmente el mapa elegido hace que el marco nazca con su CRS,
        # extensión y capas, además de la vinculación explícita posterior.
        previous_id = self.active_id
        if map_id != NONE and map_id != previous_id:
            self.activate(map_id)
        self._pending[id(layout)] = (map_id, time.time(), previous_id)
        action.trigger()

    # --- elementos nuevos en un layout
    @staticmethod
    def _log(text):
        QgsMessageLog.logMessage(text, "Multimap Layout")

    def _watch_layout(self, layout):
        key = id(layout)
        if key in self._watched:
            return
        self._watched.add(key)
        # Lo que ya existe cuando se abre el disenador no se enlaza ni se pregunta.
        try:
            self._seen[key] = set(it.uuid() for it in self._layout_items(layout))
        except Exception as e:
            self._log("No se pudieron leer los elementos del layout: %s" % e)
        slots = []

        def connect(label, getter, slot):
            # Cada senal por separado: si una falla (cambia entre versiones de QGIS) las demas
            # siguen conectadas, y el error queda en el registro en vez de esconderse.
            try:
                signal = getter()
                signal.connect(slot)
                slots.append((signal, slot))
            except Exception as e:
                self._log("No se pudo vigilar «%s» del layout: %s" % (label, e))

        modified = lambda *_args, lay=layout: self._on_layout_modified(lay)
        connect("changed", lambda: layout.changed, modified)
        try:
            model = layout.itemsModel()
        except Exception as e:
            model = None
            self._log("No se pudo leer el modelo de elementos del layout: %s" % e)
        if model is not None:
            for name in ("rowsInserted", "rowsRemoved", "dataChanged"):
                connect(name, lambda n=name: getattr(model, n), modified)
        item_added_slot = lambda item, lay=layout: QTimer.singleShot(
            0, lambda target=lay, added=item: self._on_layout_item_added(target, added)
        )
        connect("itemAdded", lambda: layout.itemAdded, item_added_slot)
        self._layout_dirty_slots[key] = (layout, slots)
        for item in self._layout_items(layout):
            self._watch_layout_item(item)

    def _watch_layout_item(self, item):
        try:
            item_key = id(item)
            if item_key in self._watched_item_slots:
                return
            signal = getattr(item, "changed", None)
            if signal is None:
                return
            slot = lambda *_args: self._mark_project_dirty()
            signal.connect(slot)
            self._watched_item_slots[item_key] = (item, signal, slot)
        except Exception:
            pass

    def _on_layout_modified(self, layout):
        self._mark_project_dirty()
        # El mapa se crea al empezar el gesto de dibujo; QGIS sigue modificando
        # su extensión hasta soltar el ratón. Reenlazar después de la pausa evita
        # que el propio tool nativo sobrescriba las capas que acabamos de asignar.
        for (layout_key, _uuid), entry in list(self._deferred_layout_binds.items()):
            if layout_key == id(layout):
                entry[0].start(300)
        QTimer.singleShot(0, lambda lay=layout: self._check_new_items(lay))

    def _on_layout_item_added(self, layout, item):
        try:
            if isinstance(item, QgsLayoutItemMap):
                self._watch_layout_item(item)
            elif not isinstance(item, QgsLayoutItemLegend):
                return
            self._seen.setdefault(id(layout), set()).add(item.uuid())
            if item.customProperty(PROP, "") or item.customProperty(SKIP, ""):
                return
            if isinstance(item, QgsLayoutItemMap):
                self._handle_new_map_item(layout, item)
            else:
                self._handle_new_legend_item(layout, item)
        except RuntimeError:
            pass

    @staticmethod
    def _mark_project_dirty():
        project = QgsProject.instance()
        try:
            if not project.isDirty():
                project.setDirty(True)
        except Exception:
            project.setDirty(True)

    def _check_new_items(self, layout):
        if self._unloaded:
            return
        try:
            items = self._layout_items(layout)
            seen = self._seen.setdefault(id(layout), set())
            new = [it for it in items if it.uuid() not in seen]
            for it in items:
                seen.add(it.uuid())
                self._watch_layout_item(it)
            for it in new:
                if it.customProperty(PROP, "") or it.customProperty(SKIP, ""):
                    continue
                if isinstance(it, QgsLayoutItemMap):
                    self._handle_new_map_item(layout, it)
                elif isinstance(it, QgsLayoutItemLegend):
                    self._handle_new_legend_item(layout, it)
        except RuntimeError:
            pass  # el layout ya se cerro

    def _handle_new_map_item(self, layout, it):
        key = id(layout)
        if (key, it.uuid()) in self._deferred_layout_binds:
            return  # el mismo elemento llega por dos caminos (itemAdded y la revision): una sola vez
        pend = self._pending.pop(key, None)
        if pend is not None and time.time() - pend[1] < 180:
            if pend[0] == NONE:
                it.setCustomProperty(SKIP, "1")
                return
            m = self._get(pend[0])
            if m is not None:
                self._defer_new_item_binding(layout, it, m, pend[2])
                return
        # Sin eleccion explicita (boton directo, menu Capa, atajo): con 2+ mapas se enlaza al
        # mapa activo; si no, el elemento seguiria la proyeccion y las capas del lienzo activo.
        if len(self.maps) >= 2:
            m = self._get(self.active_id)
            if m is not None:
                self._defer_new_item_binding(layout, it, m)

    def _handle_new_legend_item(self, layout, it):
        """Leyenda nueva: se enlaza al mapa del elemento de referencia del layout (o al activo)."""
        if len(self.maps) < 2 or (id(layout), it.uuid()) in self._deferred_layout_binds:
            return
        m = None
        try:
            ref = layout.referenceMap()
            if ref is not None:
                m = self._get(ref.customProperty(PROP, ""))
        except Exception:
            pass
        if m is None:
            m = self._get(self.active_id)
        if m is not None:
            self._defer_new_item_binding(layout, it, m)

    def _defer_new_item_binding(self, layout, item, map_info, restore_map_id=None):
        key = (id(layout), item.uuid())
        previous = self._deferred_layout_binds.pop(key, None)
        if previous is not None:
            previous[0].stop()
            previous[0].deleteLater()
        timer = QTimer(self.iface.mainWindow())
        timer.setSingleShot(True)
        timer.timeout.connect(lambda bind_key=key: self._finish_deferred_layout_bind(bind_key))
        self._deferred_layout_binds[key] = (timer, layout, item, map_info["id"], restore_map_id)
        timer.start(300)

    def _finish_deferred_layout_bind(self, key):
        entry = self._deferred_layout_binds.pop(key, None)
        if entry is None:
            return
        timer, layout, item, map_id, restore_map_id = entry
        timer.deleteLater()
        try:
            if item not in layout.items():
                return
        except RuntimeError:
            return
        map_info = self._get(map_id)
        if map_info is not None:
            self._bind_new_item(layout, item, map_info)
        # Volver al mapa que estaba activo antes de abrir la herramienta del
        # Layout. El diseño ya quedó enlazado al mapa seleccionado.
        if restore_map_id and self._get(restore_map_id):
            self.activate(restore_map_id)

    def _cancel_deferred_layout_binds(self, layout=None):
        layout_key = id(layout) if layout is not None else None
        for key, entry in list(self._deferred_layout_binds.items()):
            if layout_key is None or key[0] == layout_key:
                self._deferred_layout_binds.pop(key, None)
                entry[0].stop()
                entry[0].deleteLater()

    def _designer_notice(self, layout, text):
        designer = self._designer_by_layout.get(id(layout))
        try:
            if designer is not None:
                designer.messageBar().pushInfo("Multimapa", text)
        except Exception:
            pass

    def _bind_new_item(self, layout, it, m):
        self._save_view()
        self._bind_item(it, m)
        self._mark_project_dirty()
        what = "Leyenda enlazada" if isinstance(it, QgsLayoutItemLegend) else "Mapa enlazado"
        self._designer_notice(layout, "%s a «%s». Se cambia con Layout > Asignar mapa…" % (what, m["name"]))
        designer = self._designer_by_layout.get(id(layout))
        if designer is not None:
            try:
                designer.showItemOptions(it, False)
            except Exception:
                pass

    # --- elementos que ya estaban en el layout sin enlazar
    def _unbound_items(self, layout):
        return [
            it for it in self._layout_items(layout)
            if isinstance(it, (QgsLayoutItemMap, QgsLayoutItemLegend))
            and not it.customProperty(PROP, "") and not it.customProperty(SKIP, "")
        ]

    def _offer_bind_legacy(self, designer, layout):
        """Mapas/leyendas sin enlazar siguen el lienzo activo (su proyeccion y capas cambian con
        el): con 2+ mapas se ofrece enlazarlos de un clic."""
        try:
            name = layout.name()
            if len(self.maps) < 2 or name in self._legacy_noted:
                return
            todo = self._unbound_items(layout)
            if not todo:
                return
            self._legacy_noted.add(name)
            bar = designer.messageBar()
            msg = bar.createMessage(
                "Multimapa",
                "%d elemento(s) sin enlazar siguen el lienzo activo (cambian con su proyección y capas)." % len(todo),
            )
            btn = QPushButton("Enlazar al mapa activo", msg)
            btn.clicked.connect(lambda _c=False: self._bind_legacy(designer, layout))
            msg.layout().addWidget(btn)
            from qgis.core import Qgis
            bar.pushWidget(msg, qenum(Qgis, "MessageLevel", "Warning"), 0)
        except Exception as e:
            self._log("No se pudo ofrecer el enlace de elementos sueltos: %s" % e)

    def _bind_legacy(self, designer, layout):
        m = self._get(self.active_id)
        if m is None:
            return
        self._save_view()
        todo = self._unbound_items(layout)
        for it in todo:
            self._bind_item(it, m)
        self._mark_project_dirty()
        try:
            designer.messageBar().clearWidgets()
        except Exception:
            pass
        self._designer_notice(layout, "%d elemento(s) enlazado(s) a «%s»." % (len(todo), m["name"]))

    def assign_map_to_layout_items(self, *_):
        if not self.maps:
            self._warn("Primero crea al menos un mapa.")
            return
        targets = []
        for d in self._designers():
            try:
                for it in d.layout().selectedLayoutItems():
                    if isinstance(it, (QgsLayoutItemMap, QgsLayoutItemLegend)):
                        targets.append(it)
            except Exception:
                pass
        if not targets:
            self._warn("Selecciona un elemento de mapa o leyenda en un layout abierto.")
            return
        mid = self._pick_map(
            "Asignar mapa", "Mapa que mostrará el elemento seleccionado:", default=self.active_id
        )
        if not mid:
            return
        self._save_view()
        m = self._get(mid)
        for it in targets:
            self._bind_item(it, m)
        self._ok("Se asignó «%s» a %d elemento(s)." % (m["name"], len(targets)))

    # -------------------------------------------------------------- signals
    def _on_cleared(self, *_):
        self._loading = True
        self._hidden.clear()
        self._layer_by_map.clear()
        self._pending.clear()
        self._cancel_deferred_layout_binds()
        for window in list(self._map_windows.values()):
            try:
                window.close()
            except RuntimeError:
                pass
        self._map_windows.clear()

    def _on_layers_added(self, layers):
        """Las capas nuevas caen en la raiz (= mapa activo). Solo hay que garantizar un mapa."""
        if self._busy or self._loading:
            return
        if not self.maps:
            self._ensure_init()   # la capa recien agregada queda dentro de 'Mapa 1'

    def _on_crs_changed(self):
        # Al abrir un proyecto QGIS aplica el CRS global al lienzo; eso no es una eleccion
        # del usuario y no debe guardarse en el mapa activo (contagiaria su proyeccion).
        if self._busy or self._loading:
            return
        m = self._get(self.active_id)
        if m:
            m["crs"] = self._crs_str(self.canvas.mapSettings().destinationCrs())
            self._refresh_bound_layout_items(m["id"])
            self._persist()

    def _on_write(self, doc=None, *_):
        if self.maps:
            self._save_view()
            self._persist()
        self._inject_hidden(doc)

    def _on_project_new(self, *_):
        self._loading = False
        if self._layout_toolbar_window is not None:
            self._detach_layout_toolbar()
        self.maps = []
        self.stored = {}
        self.active_id = None
        self._view_order = []
        self._layouts_by_key = {}
        self._refresh_tabs()
        self._ensure_init(persist=False)

    def _restore_project_layouts(self):
        if self._restoring_layouts:
            return
        self._restoring_layouts = True
        try:
            manager = QgsProject.instance().layoutManager()
            layouts = list(manager.layouts())
            opened_names = set()
            for designer in self._designers():
                try:
                    opened_names.add(designer.layout().name())
                except RuntimeError:
                    pass
            preferred = [key[7:] for key in self._view_order if key.startswith("layout:")]
            by_name = {layout.name(): layout for layout in layouts}
            ordered = [by_name[name] for name in preferred if name in by_name]
            ordered.extend(layout for layout in layouts if layout.name() not in preferred)
            for layout in ordered:
                if layout.name() in opened_names:
                    continue
                try:
                    self.iface.openLayoutDesigner(layout)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        "No se pudo reabrir el Layout «%s»: %s" % (layout.name(), e),
                        "Multimap Layout",
                    )
        finally:
            self._restoring_layouts = False

    def _load_state(self, *_):
        self._loading = False
        self.maps = []
        self.stored = {}
        self.active_id = None
        self._view_order = []
        raw, ok = QgsProject.instance().readEntry(KEY, "state", "")
        if ok and raw:
            try:
                st = json.loads(raw)
                maps = st.get("maps", [])
                stored = st.get("stored")
                self._view_order = [str(k) for k in st.get("view_order", []) if isinstance(k, str)]
                if maps and isinstance(stored, dict):   # formato v0.5
                    self.maps = maps
                    ids = set(m["id"] for m in maps)
                    self.stored = {k: v for k, v in stored.items() if k in ids}
                    active = st.get("active")
                    self.active_id = active if active in ids else maps[0]["id"]
                    for m in maps:
                        if m["id"] != self.active_id:
                            self.stored.setdefault(m["id"], [])
                    self.stored.pop(self.active_id, None)
            except Exception:
                self.maps = []
                self.stored = {}
                self.active_id = None
                self._view_order = []
        self._migrate_flat_nodes()
        self._refresh_tabs()
        self._restore_project_layouts()
        if self.active_id:
            # El estado guardado por mapa es la referencia para la vista activa: su CRS
            # se aplica al lienzo y al proyecto (sin marcar el proyecto como modificado).
            self._quiet_crs = True
            try:
                self.activate(self.active_id, restore_view=True, save_view=False, persist=False, swap=False)
            finally:
                self._quiet_crs = False
        elif not self._root().children():
            self._ensure_init(persist=False)
        self._refresh_bound_layout_items()
