import os, traceback, time
from qgis.PyQt.QtCore import QTimer, QPoint
from qgis.PyQt.QtWidgets import QApplication, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer, QgsApplication
import qgis.utils
out = open(os.environ["MM_OUT"], "w")
def log(m): out.write(m + "\n"); out.flush()
def pump(n=10):
    for _ in range(n): QApplication.processEvents(); time.sleep(0.03)
def ck(name, cond, extra=""): log(("OK   " if cond else "FAIL ") + name + ("  -> %s" % (extra,) if extra != "" else ""))
def _msg(message, tag, level):
    if "Traceback" in message or tag.startswith("Python"): log("PYTHON: " + message[-900:])
QgsApplication.messageLog().messageReceived.connect(_msg)
def run():
    try:
        iface = qgis.utils.iface; win = iface.mainWindow()
        win.showMaximized(); pump(20)
        qgis.utils.loadPlugin("multimap_layout"); qgis.utils.startPlugin("multimap_layout")
        p = qgis.utils.plugins["multimap_layout"]
        QgsProject.instance().addMapLayer(QgsVectorLayer("Point?crs=EPSG:4326", "a", "memory")); pump(20)
        p.add_map(); pump(20)
        shot = os.environ.get("MM_SHOT")
        if shot: win.grab().save(shot + "_mapas.png")
        mpos = p.tabbar.mapTo(win, QPoint(0, 0))
        p.new_layout(); pump(40)
        lpos = p.layout_tabbar.mapTo(win, QPoint(0, 0))
        if shot: win.grab().save(shot + "_layout.png")
        ck("pestañas en el mismo lugar (x)", abs(mpos.x() - lpos.x()) <= 2, (mpos.x(), lpos.x()))
        ck("pestañas en el mismo lugar (y)", abs(mpos.y() - lpos.y()) <= 2, (mpos.y(), lpos.y()))
        ck("plantillas completas visibles", p._tpl_full.isVisible(), [b.text() for b in p._tpl_buttons])
        ck("boton Catálogo en Layout", p.layout_catalog.isVisible())
        p.toggle_catalog(); pump(); hidden = not p.catalog.isVisible()
        p.toggle_catalog(); pump()
        ck("boton Catálogo oculta y muestra", hidden and p.catalog.isVisible() and p.layout_catalog.isChecked())
        # volver a mapas, cambiar ancho del panel de capas y volver al Layout: se realinea
        p._on_tab_changed(next(i for i in range(p.tabbar.count()) if p._tab_key(i).startswith("map:"))); pump(20)
        dock = next(d for d in win.findChildren(__import__("qgis.PyQt.QtWidgets", fromlist=["QDockWidget"]).QDockWidget) if d.objectName() == "Layers")
        win.resizeDocks([dock], [dock.width() + 120], __import__("qgis.PyQt.QtCore", fromlist=["Qt"]).Qt.Horizontal); pump(20)
        mpos = p.tabbar.mapTo(win, QPoint(0, 0))
        p._on_tab_changed(next(i for i in range(p.tabbar.count()) if p._tab_key(i).startswith("layout:"))); pump(30)
        lpos = p.layout_tabbar.mapTo(win, QPoint(0, 0))
        ck("se realinea si cambia el ancho del panel de capas", abs(mpos.x() - lpos.x()) <= 2 and abs(mpos.y() - lpos.y()) <= 2, (mpos, lpos))
        # lado a lado desde el boton
        p._on_tab_changed(next(i for i in range(p.tabbar.count()) if p._tab_key(i).startswith("map:"))); pump(20)
        from qgis.PyQt.QtWidgets import QMenu
        m = QMenu(); p._fill_side_menu(m)
        other = [x["name"] for x in p.maps if x["id"] != p.active_id]
        ck("menu Lado a lado lista el otro mapa", [a.text() for a in m.actions()][:1] == other, [a.text() for a in m.actions()])
        m.actions()[0].trigger(); pump(30)
        ck("Lado a lado abre la vista", p._side_ids() != [])
        if shot: win.grab().save(shot + "_lado.png")
    except Exception:
        log("EXC " + traceback.format_exc())
    log("FIN"); os._exit(0)
QTimer.singleShot(3000, run)
