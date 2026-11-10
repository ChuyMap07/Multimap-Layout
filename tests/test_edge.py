import os, traceback, time
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QApplication, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer, QgsApplication
import qgis.utils
out = open(os.environ["MM_OUT"], "w")
def log(m): out.write(m + "\n"); out.flush()
def pump(n=10):
    for _ in range(n): QApplication.processEvents(); time.sleep(0.02)
def ck(name, cond, extra=""): log(("OK   " if cond else "FAIL ") + name + ("  -> %s" % (extra,) if extra != "" else ""))
def _msg(message, tag, level):
    if "Traceback" in message or tag.startswith("Python"): log("PYTHON: " + message[-900:])
QgsApplication.messageLog().messageReceived.connect(_msg)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)
def run():
    try:
        iface = qgis.utils.iface; win = iface.mainWindow()
        qgis.utils.loadPlugin("multimap_layout"); qgis.utils.startPlugin("multimap_layout")
        p = qgis.utils.plugins["multimap_layout"]
        QgsProject.instance().addMapLayer(QgsVectorLayer("Point?crs=EPSG:4326", "a", "memory")); pump()
        p.new_layout(); pump(30)
        QgsProject.instance().setDirty(False)
        iface.newProject(False); pump(30)
        ck("proyecto nuevo desde vista de Layout: vuelve a mapas", p.view_stack.currentWidget() is p._map_page)
        ck("proyecto nuevo: menus visibles", win.menuBar().isVisible())
        ck("proyecto nuevo: sin pestañas de Layout", not any(p._tab_key(i).startswith("layout:") for i in range(p.tabbar.count())))
        QgsProject.instance().addMapLayer(QgsVectorLayer("Point?crs=EPSG:4326", "b", "memory")); pump()
        p.new_layout(); pump(30)
        log("... recargando complemento con Layout abierto")
        qgis.utils.reloadPlugin("multimap_layout"); pump(40)
        p2 = qgis.utils.plugins["multimap_layout"]
        ck("recarga: queda en la vista de Layout (menus del diseñador)", p2.view_stack.currentWidget() is not p2._map_page)
        ck("recarga: hay pestañas de mapa y layout", p2.tabbar.count() >= 2, [p2._tab_key(i) for i in range(p2.tabbar.count())])
        ck("recarga: un solo contenedor de vistas", type(win.centralWidget()).__name__ == "QStackedWidget" and
           win.centralWidget().indexOf(p2._map_page) >= 0)
        # proyecto creado SIN el complemento
        plain = QgsProject(); plain.addMapLayer(QgsVectorLayer("Point?crs=EPSG:4326", "normal1", "memory"))
        path = os.path.join(os.environ["MM_WORK"], "normal.qgz"); plain.write(path)
        iface.addProject(path); pump(40)
        ck("proyecto normal de QGIS: se crea Mapa 1 con sus capas",
           [m["name"] for m in p2.maps] == ["Mapa 1"] and p2.tabbar.count() >= 1, [m["name"] for m in p2.maps])
        ck("proyecto normal: abrirlo no lo marca como modificado", not QgsProject.instance().isDirty())
        qgis.utils.unloadPlugin("multimap_layout"); pump(30)
        ck("descarga con Layout abierto: el lienzo original vuelve", win.centralWidget() is p2._main_central)
        ck("descarga: menus visibles", win.menuBar().isVisible())
        ck("descarga: el diseñador queda como ventana normal", all(d.window().isWindow() for d in iface.openLayoutDesigners()))
    except Exception:
        log("EXC " + traceback.format_exc())
    log("FIN"); os._exit(0)
def watchdog():
    w = QApplication.activeModalWidget()
    if w is not None:
        log("MODAL %r" % w.windowTitle()); w.close()
    QTimer.singleShot(1000, watchdog)
QTimer.singleShot(3000, run); QTimer.singleShot(4000, watchdog)
