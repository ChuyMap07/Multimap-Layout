import os, traceback, time
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QApplication, QMessageBox
from qgis.core import (QgsProject, QgsVectorLayer, QgsApplication, QgsRelation, QgsMapThemeCollection,
                       QgsSnappingConfig, QgsTolerance, QgsFeature, QgsGeometry, QgsPointXY)
import qgis.utils
out = open(os.environ["MM_OUT"], "w")
def log(m): out.write(m + "\n"); out.flush()
def pump(n=10):
    for _ in range(n): QApplication.processEvents(); time.sleep(0.02)
def ck(name, cond, extra=""): log(("OK   " if cond else "FAIL ") + name + ("  -> %s" % (extra,) if extra != "" else ""))
def _msg(message, tag, level):
    if "Traceback" in message or tag.startswith("Python"): log("PYTHON: " + message[-800:])
QgsApplication.messageLog().messageReceived.connect(_msg)
def run():
    try:
        iface = qgis.utils.iface
        qgis.utils.loadPlugin("multimap_layout"); qgis.utils.startPlugin("multimap_layout")
        p = qgis.utils.plugins["multimap_layout"]
        prj = QgsProject.instance()
        # Mapa 1: capa padre/hija con relacion, tema de mapa, snapping por capa
        par = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", "padre", "memory")
        chi = QgsVectorLayer("Point?crs=EPSG:4326&field=pid:integer", "hija", "memory")
        f = QgsFeature(par.fields()); f.setAttributes([1]); f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0,0)))
        par.dataProvider().addFeatures([f])
        prj.addMapLayers([par, chi]); pump()
        m1 = p.active_id
        rel = QgsRelation(); rel.setId("rel1"); rel.setName("padre_hija")
        rel.setReferencedLayer(par.id()); rel.setReferencingLayer(chi.id()); rel.addFieldPair("pid", "id")
        ck("relacion valida", rel.isValid())
        prj.relationManager().addRelation(rel)
        rec = QgsMapThemeCollection.createThemeFromCurrentState(prj.layerTreeRoot(), iface.layerTreeView().layerTreeModel())
        prj.mapThemeCollection().insert("Tema1", rec)
        sc = prj.snappingConfig(); sc.setEnabled(True); sc.setMode(QgsSnappingConfig.AdvancedConfiguration)
        ils = QgsSnappingConfig.IndividualLayerSettings(True, QgsSnappingConfig.VertexFlag, 12, QgsTolerance.Pixels, 0, 0)
        sc.setIndividualLayerSettings(par, ils); prj.setSnappingConfig(sc)
        # tabla de atributos y panel de estilo abiertos sobre una capa del mapa 1
        iface.setActiveLayer(par)
        dlg = iface.showAttributeTable(par); pump(20)
        ck("tabla de atributos abierta", dlg is not None)
        # cambiar a Mapa 2 y volver
        p.add_map(); pump(20)
        QgsProject.instance().addMapLayer(QgsVectorLayer("Point?crs=EPSG:4326", "otra", "memory")); pump()
        ck("QGIS sigue vivo tras ocultar capa con tabla de atributos abierta", True)
        p.activate(m1); pump(20)
        ck("relacion se conserva al volver", "rel1" in prj.relationManager().relations(), list(prj.relationManager().relations()))
        th = prj.mapThemeCollection().mapThemeState("Tema1")
        ck("tema de mapa conserva sus capas", len(th.layerRecords()) == 2, len(th.layerRecords()))
        lay = prj.mapLayersByName("padre")[0]
        ils2 = prj.snappingConfig().individualLayerSettings().get(lay)
        ck("snapping por capa se conserva", ils2 is not None and ils2.tolerance() == 12, ils2.tolerance() if ils2 else None)
        # relacion con capa en otro mapa y guardar estando en mapa 2
        p.activate(next(m["id"] for m in p.maps if m["id"] != m1)); pump(20)
        path = os.path.join(os.environ["MM_WORK"], "compat.qgz")
        prj.write(path); pump(30)
        iface.newProject(False); pump(20); iface.addProject(path); pump(40)
        p.activate(next(m["id"] for m in p.maps if m["name"] == "Mapa 1")); pump(20)
        ck("relacion sobrevive guardar/abrir estando en otro mapa", len(prj.relationManager().relations()) == 1, list(prj.relationManager().relations()))
        th = prj.mapThemeCollection().mapThemeState("Tema1")
        ck("tema de mapa sobrevive guardar/abrir", len(th.layerRecords()) == 2, len(th.layerRecords()))
        other = QgsProject(); other.read(path)
        ck("sin el complemento: el archivo trae la relacion", len(other.relationManager().relations()) == 1)
        ck("sin el complemento: el archivo trae el tema completo", len(other.mapThemeCollection().mapThemeState("Tema1").layerRecords()) == 2,
           len(other.mapThemeCollection().mapThemeState("Tema1").layerRecords()))
        # borrar el mapa elimina tambien lo estacionado
        p.activate(next(m["id"] for m in p.maps if m["name"] != "Mapa 1")); pump(20)
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        p.delete_map(next(m["id"] for m in p.maps if m["name"] == "Mapa 1")); pump(10)
        ck("al eliminar el mapa no quedan relaciones huerfanas", not p._parked_relations and not p._parked_themes,
           (p._parked_relations.keys(), p._parked_themes.keys()))
    except Exception:
        log("EXC " + traceback.format_exc())
    log("FIN"); os._exit(0)
def watchdog():
    w = QApplication.activeModalWidget()
    if w is not None:
        log("MODAL %r" % w.windowTitle()); w.close()
    QTimer.singleShot(1000, watchdog)
QTimer.singleShot(3000, run); QTimer.singleShot(4000, watchdog)
