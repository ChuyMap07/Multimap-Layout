# -*- coding: utf-8 -*-
"""Vistas secundarias de un mapa (al estilo de ArcGIS Pro).

* MapViewWidget: lienzo + barra de navegacion (desplazar, zoom, extension completa, anterior /
  siguiente, identificar en todas las capas visibles, medir) + linea de estado (escala y
  coordenadas). Es la pieza comun de las dos vistas siguientes.
* MapViewWindow: ventana propia (otra pantalla) con arbol de capas del mapa.
* SideMapView: vista acoplada al lado del lienzo principal, dentro de la ventana de QGIS.

Ambas exponen canvas, root, bridge y map_info: el complemento las sincroniza igual."""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsApplication,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFeatureRequest,
    QgsLayerTreeModel,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.gui import (
    QgsLayerTreeMapCanvasBridge,
    QgsLayerTreeView,
    QgsMapCanvas,
    QgsMapToolEmitPoint,
    QgsMapToolPan,
    QgsMapToolZoom,
    QgsRubberBand,
)

from .common import qenum

try:
    from qgis.PyQt.QtGui import QAction, QActionGroup
except ImportError:
    from qgis.PyQt.QtWidgets import QAction, QActionGroup


def _theme_icon(name):
    try:
        return QgsApplication.getThemeIcon(name)
    except Exception:
        from qgis.PyQt.QtGui import QIcon
        return QIcon()


def _line_geometry_type():
    try:
        from qgis.core import Qgis
        return Qgis.GeometryType.Line
    except Exception:
        from qgis.core import QgsWkbTypes
        return QgsWkbTypes.LineGeometry


def _right_button():
    return qenum(Qt, "MouseButton", "RightButton")


class IdentifyTool(QgsMapToolEmitPoint):
    """Identifica en TODAS las capas vectoriales visibles del lienzo (no solo en una)."""

    def __init__(self, canvas, view):
        super().__init__(canvas)
        self.view = view
        self.canvas_ref = canvas

    def canvasReleaseEvent(self, event):
        try:
            pt = self.toMapCoordinates(event.pos())
        except Exception:
            return
        self.view.identify_at(pt)


class MeasureTool(QgsMapToolEmitPoint):
    """Mide distancias: clic izquierdo agrega vertices, clic derecho termina (el siguiente clic
    empieza una medicion nueva). El resultado se muestra en la linea de estado de la vista."""

    def __init__(self, canvas, view):
        super().__init__(canvas)
        self.view = view
        self.canvas_ref = canvas
        self.points = []
        self.finished = False
        self.band = QgsRubberBand(canvas, _line_geometry_type())
        self.band.setColor(QColor(220, 40, 40, 200))
        self.band.setWidth(2)

    def _distance(self, points):
        d = QgsDistanceArea()
        prj = QgsProject.instance()
        d.setSourceCrs(self.canvas_ref.mapSettings().destinationCrs(), prj.transformContext())
        try:
            d.setEllipsoid(prj.ellipsoid())
        except Exception:
            pass
        total = d.measureLine(points) if len(points) > 1 else 0.0
        try:
            return QgsDistanceArea.formatDistance(total, 2, d.lengthUnits(), False)
        except Exception:
            return "%.2f" % total

    def reset(self):
        self.points = []
        self.finished = False
        self.band.reset(_line_geometry_type())

    def canvasReleaseEvent(self, event):
        pt = self.toMapCoordinates(event.pos())
        if event.button() == _right_button():
            self.finished = True
            if self.points:
                self.view.show_message("Distancia total: %s" % self._distance(self.points))
            return
        if self.finished:
            self.reset()
        self.points.append(QgsPointXY(pt))
        self.band.addPoint(QgsPointXY(pt), True)
        self.view.show_message("Distancia: %s  (clic derecho para terminar)" % self._distance(self.points))

    def canvasMoveEvent(self, event):
        if not self.points or self.finished:
            return
        pt = QgsPointXY(self.toMapCoordinates(event.pos()))
        self.view.show_message("Distancia: %s  (clic derecho para terminar)"
                               % self._distance(self.points + [pt]))

    def deactivate(self):
        self.reset()
        super().deactivate()


class IdentifyResults(QDialog):
    def __init__(self, parent, results):
        super().__init__(parent)
        self.setWindowTitle("Identificar")
        self.resize(420, 360)
        tree = QTreeWidget(self)
        tree.setHeaderLabels(["Campo", "Valor"])
        for layer_name, features in results:
            top = QTreeWidgetItem(tree, [layer_name, "%d entidad(es)" % len(features)])
            for fid, attrs in features:
                fi = QTreeWidgetItem(top, ["Entidad %s" % fid, ""])
                for name, value in attrs:
                    QTreeWidgetItem(fi, [name, "" if value is None else str(value)])
            top.setExpanded(True)
            if top.childCount():
                top.child(0).setExpanded(True)
        tree.resizeColumnToContents(0)
        buttons = QDialogButtonBox(qenum(QDialogButtonBox, "StandardButton", "Close"))
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tree)
        lay.addWidget(buttons)


class MapViewWidget(QWidget):
    """Lienzo de un mapa con su barra de navegacion y su linea de estado."""

    def __init__(self, plugin, map_info, root, parent=None, compact=False):
        super().__init__(parent)
        self.plugin = plugin
        self.map_info = map_info
        self.root = root
        self.closing = False

        self.canvas = QgsMapCanvas(self)
        self.canvas.setProject(QgsProject.instance())
        self.canvas.setDestinationCrs(plugin._crs_from(map_info["crs"]))
        self.canvas.setExtent(QgsRectangle(*map_info["extent"]))
        try:
            self.canvas.setRotation(float(map_info.get("rot", 0.0)))
        except Exception:
            pass

        self.bridge = QgsLayerTreeMapCanvasBridge(root, self.canvas, self)
        self.bridge.setAutoSetupOnFirstLayer(False)
        self.bridge.setCanvasLayers()
        self.canvas.setExtent(QgsRectangle(*map_info["extent"]))

        self.toolbar = QToolBar("Navegación", self)
        self.toolbar.setObjectName("MultiMapViewNavigation")
        if compact:
            self.toolbar.setIconSize(self.toolbar.iconSize() * 0.75)
        group = QActionGroup(self)
        self._tools = {}

        def tool_action(key, icon, text, tool):
            act = QAction(_theme_icon(icon), text, self)
            act.setCheckable(True)
            group.addAction(act)
            tool.setAction(act)
            act.triggered.connect(lambda _c=False, t=tool: self.canvas.setMapTool(t))
            self.toolbar.addAction(act)
            self._tools[key] = (tool, act)
            return act

        def plain_action(icon, text, slot):
            act = QAction(_theme_icon(icon), text, self)
            act.triggered.connect(lambda _c=False: slot())
            self.toolbar.addAction(act)
            return act

        pan = tool_action("pan", "/mActionPan.svg", "Desplazar mapa", QgsMapToolPan(self.canvas))
        tool_action("zin", "/mActionZoomIn.svg", "Acercar", QgsMapToolZoom(self.canvas, False))
        tool_action("zout", "/mActionZoomOut.svg", "Alejar", QgsMapToolZoom(self.canvas, True))
        plain_action("/mActionZoomFullExtent.svg", "Extensión completa", self.canvas.zoomToFullExtent)
        plain_action("/mActionZoomLast.svg", "Extensión anterior", self.canvas.zoomToPreviousExtent)
        plain_action("/mActionZoomNext.svg", "Extensión siguiente", self.canvas.zoomToNextExtent)
        self.toolbar.addSeparator()
        tool_action("identify", "/mActionIdentify.svg", "Identificar entidades (todas las capas visibles)",
                    IdentifyTool(self.canvas, self))
        tool_action("measure", "/mActionMeasure.svg", "Medir distancia (clic derecho termina)",
                    MeasureTool(self.canvas, self))
        pan.setChecked(True)
        self.canvas.setMapTool(self._tools["pan"][0])

        self.status = QLabel(self)
        self.status.setContentsMargins(6, 1, 6, 1)
        self._message = ""
        self._coords = ""
        self.canvas.scaleChanged.connect(lambda *_: self._update_status())
        self.canvas.xyCoordinates.connect(self._on_xy)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.status)
        self._update_status()

        self.canvas.extentsChanged.connect(self._on_extent_changed)
        self.canvas.destinationCrsChanged.connect(self._on_crs_changed)

    # ------------------------------------------------------------- estado
    def _on_xy(self, pt):
        self._coords = "%.4f, %.4f" % (pt.x(), pt.y())
        self._update_status()

    def show_message(self, text):
        self._message = text
        self._update_status()

    def _update_status(self):
        try:
            scale = "Escala 1:%s" % format(int(round(self.canvas.scale())), ",").replace(",", ".")
        except Exception:
            scale = ""
        parts = [p for p in (scale, self._coords, self._message) if p]
        self.status.setText("   |   ".join(parts))

    # ---------------------------------------------------------- identificar
    def identify_at(self, point):
        canvas = self.canvas
        tol = canvas.mapUnitsPerPixel() * 5
        rect = QgsRectangle(point.x() - tol, point.y() - tol, point.x() + tol, point.y() + tol)
        dst = canvas.mapSettings().destinationCrs()
        results = []
        for layer in canvas.layers():
            if not isinstance(layer, QgsVectorLayer) or not layer.isSpatial():
                continue
            try:
                r = rect
                if layer.crs() != dst:
                    tr = QgsCoordinateTransform(dst, layer.crs(), QgsProject.instance())
                    r = tr.transformBoundingBox(rect)
                req = QgsFeatureRequest().setFilterRect(r).setLimit(20)
                feats = []
                for f in layer.getFeatures(req):
                    attrs = [(fld.name(), val) for fld, val in zip(layer.fields(), f.attributes())]
                    feats.append((f.id(), attrs))
                if feats:
                    results.append((layer.name(), feats))
            except Exception:
                continue
        if not results:
            self.show_message("Identificar: no hay entidades en ese punto")
            return
        self.show_message("")
        dlg = IdentifyResults(self.window(), results)
        (getattr(dlg, "exec", None) or dlg.exec_)()

    # ------------------------------------------------------------ senales
    def _on_extent_changed(self):
        if not self.closing:
            self.plugin._on_floating_extent_changed(self.map_info["id"], self.canvas.extent())

    def _on_crs_changed(self):
        if not self.closing:
            self.plugin._on_floating_crs_changed(
                self.map_info["id"], self.canvas.mapSettings().destinationCrs()
            )

    def shutdown(self):
        self.closing = True
        try:
            self.canvas.unsetMapTool(self.canvas.mapTool())
        except Exception:
            pass


class _ViewMixin:
    """Atributos comunes que usa el complemento (canvas, root, bridge)."""

    @property
    def canvas(self):
        return self.view.canvas

    @property
    def root(self):
        return self.view.root

    @property
    def bridge(self):
        return self.view.bridge


class MapViewWindow(_ViewMixin, QMainWindow):
    """Mapa en ventana propia (otra pantalla), con su arbol de capas editable."""

    kind = "window"

    def __init__(self, plugin, map_info, root, screen_geometry=None):
        QMainWindow.__init__(self, plugin.iface.mainWindow())
        self.plugin = plugin
        self.map_info = map_info
        self.setWindowTitle("Multimapa — %s" % map_info["name"])
        self.resize(1100, 720)
        self.view = MapViewWidget(plugin, map_info, root, self)
        self.setCentralWidget(self.view)

        self.layer_view = QgsLayerTreeView(self)
        self.layer_model = QgsLayerTreeModel(root, self.layer_view)
        try:
            self.layer_model.setFlag(qenum(QgsLayerTreeModel, "Flag", "AllowNodeReorder"))
            self.layer_model.setFlag(qenum(QgsLayerTreeModel, "Flag", "AllowNodeChangeVisibility"))
        except Exception:
            pass
        self.layer_view.setModel(self.layer_model)
        self.layer_dock = QDockWidget("Capas del mapa", self)
        self.layer_dock.setObjectName("MultiMapFloatingLayerTree")
        self.layer_dock.setWidget(self.layer_view)
        self.addDockWidget(qenum(Qt, "DockWidgetArea", "LeftDockWidgetArea"), self.layer_dock)

        self.view.toolbar.addSeparator()
        act_main = QAction("Activar en el lienzo principal", self)
        act_main.setToolTip("Activa este mapa en la ventana de QGIS (para editar y usar todas las herramientas)")
        act_main.triggered.connect(lambda: plugin._close_floating_map(map_info["id"], activate=True))
        self.view.toolbar.addAction(act_main)
        act_side = QAction("Acoplar al lado", self)
        act_side.triggered.connect(lambda: plugin.open_side_map(map_info["id"]))
        self.view.toolbar.addAction(act_side)

        # Un arbol de capas cambia tanto por checks como por altas, bajas, reordenamientos y grupos.
        for signal_name in ("dataChanged", "rowsInserted", "rowsRemoved", "rowsMoved", "layoutChanged"):
            signal = getattr(self.layer_model, signal_name, None)
            if signal is not None:
                try:
                    signal.connect(self._on_tree_changed)
                except (TypeError, RuntimeError):
                    pass
        if screen_geometry is not None:
            frame = self.frameGeometry()
            frame.moveCenter(screen_geometry.center())
            self.move(frame.topLeft())

    def _on_tree_changed(self, *_):
        if not self.view.closing:
            self.plugin._on_floating_tree_changed(self.map_info["id"], self.root)

    def closeEvent(self, event):
        self.view.shutdown()
        self.plugin._on_floating_map_closed(self.map_info["id"], self)
        super().closeEvent(event)


class SideMapView(_ViewMixin, QFrame):
    """Mapa acoplado al lado del lienzo principal (vistas lado a lado de ArcGIS Pro)."""

    kind = "side"

    def __init__(self, plugin, map_info, root, parent=None):
        QFrame.__init__(self, parent)
        self.plugin = plugin
        self.map_info = map_info
        self.setFrameShape(qenum(QFrame, "Shape", "StyledPanel"))
        self.view = MapViewWidget(plugin, map_info, root, self, compact=True)

        header = QWidget(self)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(6, 2, 2, 2)
        hl.setSpacing(2)
        self.title = QLabel(header)
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        hl.addWidget(self.title, 1)

        def button(text, tip, slot):
            b = QToolButton(header)
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _c=False: slot())
            hl.addWidget(b)
            return b

        button("Activar", "Activa este mapa en el lienzo principal (el mapa activo pasa a esta vista)",
               lambda: plugin.swap_side_map(map_info["id"]))
        button("↗", "Abrir en ventana propia", lambda: plugin.side_to_window(map_info["id"]))
        button("✕", "Cerrar esta vista (el mapa sigue en el Catálogo)",
               lambda: plugin._close_floating_map(map_info["id"]))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(header)
        lay.addWidget(self.view, 1)
        self.setWindowTitle(map_info["name"])

    def setWindowTitle(self, text):
        # El complemento renombra las vistas con "Multimapa — <nombre>": en la cabecera basta el nombre.
        name = text.split(" — ", 1)[-1]
        self.title.setText(name)
        QFrame.setWindowTitle(self, name)

    # La API de ventana que usa el complemento con las vistas flotantes.
    def showNormal(self):
        self.show()

    def activateWindow(self):
        self.canvas.setFocus()

    def closeEvent(self, event):
        self.view.shutdown()
        self.plugin._on_floating_map_closed(self.map_info["id"], self)
        super().closeEvent(event)
        self.hide()
        self.deleteLater()
