# -*- coding: utf-8 -*-
"""Ventana secundaria para explorar un mapa en otra pantalla."""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDockWidget, QMainWindow, QMessageBox, QToolBar
from qgis.core import QgsFeature, QgsLayerTree, QgsLayerTreeModel, QgsProject, QgsRectangle, QgsVectorLayer
from qgis.gui import (
    QgsLayerTreeMapCanvasBridge,
    QgsLayerTreeView,
    QgsMapCanvas,
    QgsMapToolIdentifyFeature,
    QgsMapToolPan,
    QgsMapToolZoom,
)
from .common import qenum

try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction


class MapViewWindow(QMainWindow):
    def __init__(self, plugin, map_info, root, screen_geometry=None):
        super().__init__(plugin.iface.mainWindow())
        self.plugin = plugin
        self.map_info = map_info
        self.root = root
        self._closing = False
        self._identify_layer = None
        self.setWindowTitle("Multimapa — %s" % map_info["name"])
        self.resize(1100, 720)

        self.canvas = QgsMapCanvas(self)
        self.canvas.setProject(QgsProject.instance())
        self.canvas.setDestinationCrs(plugin._crs_from(map_info["crs"]))
        self.canvas.setExtent(QgsRectangle(*map_info["extent"]))
        self.setCentralWidget(self.canvas)

        self.layer_view = QgsLayerTreeView(self)
        self.layer_model = QgsLayerTreeModel(root, self.layer_view)
        self.layer_view.setModel(self.layer_model)
        self.layer_dock = QDockWidget("Capas del mapa", self)
        self.layer_dock.setObjectName("MultiMapFloatingLayerTree")
        self.layer_dock.setWidget(self.layer_view)
        self.addDockWidget(qenum(Qt, "DockWidgetArea", "LeftDockWidgetArea"), self.layer_dock)

        self.bridge = QgsLayerTreeMapCanvasBridge(root, self.canvas, self)
        self.bridge.setAutoSetupOnFirstLayer(False)
        self.bridge.setCanvasLayers()
        self.canvas.setExtent(QgsRectangle(*map_info["extent"]))

        toolbar = QToolBar("Navegación", self)
        toolbar.setObjectName("MultiMapFloatingNavigation")
        self.addToolBar(toolbar)
        self._tools = {
            "Pan": QgsMapToolPan(self.canvas),
            "Acercar": QgsMapToolZoom(self.canvas, False),
            "Alejar": QgsMapToolZoom(self.canvas, True),
            "Identificar": QgsMapToolIdentifyFeature(self.canvas),
        }
        for label, tool in self._tools.items():
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, t=tool: self.canvas.setMapTool(t))
            toolbar.addAction(action)
            if label == "Identificar":
                self._identify_action = action
        self._tools["Pan"].setAction(toolbar.actions()[0])
        self.canvas.setMapTool(self._tools["Pan"])
        try:
            self._tools["Identificar"].featureIdentified[QgsFeature].connect(self._show_identified_feature)
        except Exception:
            self._tools["Identificar"].featureIdentified.connect(self._show_identified_feature)
        self.layer_view.currentLayerChanged.connect(self._set_identify_layer)
        for node in root.findLayers():
            layer = node.layer()
            if isinstance(layer, QgsVectorLayer):
                self._tools["Identificar"].setLayer(layer)
                self._identify_layer = layer
                break
        self._identify_action.setEnabled(self._identify_layer is not None)
        self.canvas.scaleChanged.connect(
            lambda scale: self.statusBar().showMessage("Escala 1:%d" % int(scale))
        )
        return_action = QAction("Volver al mapa principal", self)
        return_action.triggered.connect(
            lambda: plugin._close_floating_map(map_info["id"], activate=True)
        )
        toolbar.addSeparator()
        toolbar.addAction(return_action)

        self.canvas.extentsChanged.connect(self._on_extent_changed)
        # Un árbol de capas cambia tanto por checks como por altas, bajas,
        # reordenamientos y grupos. Escuchar solo dataChanged perdía cambios
        # estructurales al sincronizar el lienzo flotante.
        for signal_name in ("dataChanged", "rowsInserted", "rowsRemoved", "rowsMoved", "layoutChanged"):
            signal = getattr(self.layer_model, signal_name, None)
            if signal is not None:
                try:
                    signal.connect(self._on_tree_changed)
                except (TypeError, RuntimeError):
                    pass
        self.canvas.destinationCrsChanged.connect(self._on_crs_changed)
        if screen_geometry is not None:
            frame = self.frameGeometry()
            frame.moveCenter(screen_geometry.center())
            self.move(frame.topLeft())

    def _on_extent_changed(self):
        if not self._closing:
            self.plugin._on_floating_extent_changed(self.map_info["id"], self.canvas.extent())

    def _on_crs_changed(self):
        if not self._closing:
            self.plugin._on_floating_crs_changed(
                self.map_info["id"], self.canvas.mapSettings().destinationCrs()
            )

    def _on_tree_changed(self, *_):
        if not self._closing:
            self.plugin._on_floating_tree_changed(self.map_info["id"], self.root)

    def _set_identify_layer(self, layer):
        if isinstance(layer, QgsVectorLayer):
            self._tools["Identificar"].setLayer(layer)
            self._identify_layer = layer
            self._identify_action.setEnabled(True)
        else:
            self._identify_layer = None
            self._identify_action.setEnabled(False)

    def _show_identified_feature(self, feature):
        layer = self._identify_layer
        if layer is None:
            return
        rows = ["%s: %s" % (field.name(), value)
                for field, value in zip(layer.fields(), feature.attributes())]
        QMessageBox.information(
            self, "Identificar: %s" % layer.name(), "\n".join(rows) or "La entidad no tiene atributos."
        )

    def closeEvent(self, event):
        self._closing = True
        self.plugin._on_floating_map_closed(self.map_info["id"], self)
        super().closeEvent(event)
