# Pruebas dentro de QGIS completo (iface real). Ver tests/run_qgis_tests.sh
import os, sys, traceback, json, time
from qgis.PyQt.QtCore import QTimer, QPoint
from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QInputDialog
from qgis.core import (QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
                       QgsApplication, QgsPrintLayout, QgsLayoutItemMap)
from qgis.gui import QgsMapLayerComboBox
import qgis.utils

OUT = os.environ.get("MM_OUT", "/tmp/mm_report.txt")
WORK = os.environ.get("MM_WORK", "/tmp")
lines = []
fails = []


def log(msg):
    lines.append(msg)
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")


def check(name, cond, extra=""):
    log(("OK   " if cond else "FAIL ") + name + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


def pump(n=8):
    for _ in range(n):
        QApplication.processEvents()
        time.sleep(0.02)


def mem_layer(name, pts):
    lyr = QgsVectorLayer("Point?crs=EPSG:4326&field=nombre:string", name, "memory")
    feats = []
    for i, (x, y) in enumerate(pts):
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        f.setAttributes(["%s %d" % (name, i)])
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    return lyr


# Respuestas automaticas a dialogos modales
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)


def names(project=None):
    return sorted(l.name() for l in QgsProject.instance().mapLayers().values())


def run():
    iface = qgis.utils.iface
    win = iface.mainWindow()
    try:
        # ---------------------------------------------------------- carga
        ok = qgis.utils.loadPlugin("multimap_layout") and qgis.utils.startPlugin("multimap_layout")
        check("el complemento carga", ok)
        p = qgis.utils.plugins.get("multimap_layout")
        pump(20)
        mb = win.menuBar()
        tb = getattr(p, "_layout_row", None)
        check("la barra de Layout NO esta visible sobre el menu", tb is None or not tb.isVisible())
        strip_y = p.strip.mapTo(win, QPoint(0, 0)).y()
        check("la barra de mapas queda debajo del menu y barras", strip_y > mb.height(), "y=%d menu=%d" % (strip_y, mb.height()))
        from qgis.PyQt import sip
        check("el lienzo de QGIS sigue vivo", not sip.isdeleted(iface.mapCanvas()))

        # ---------------------------------------------------------- mapas independientes
        prj = QgsProject.instance()
        a = mem_layer("Rios", [(0, 0), (1, 1)])
        prj.addMapLayer(a)
        pump()
        check("se crea Mapa 1 automaticamente", len(p.maps) == 1, [m["name"] for m in p.maps])
        p.add_map()
        pump()
        m2 = p.active_id
        b = mem_layer("Ciudades", [(10, 10), (11, 11), (12, 12)])
        prj.addMapLayer(b)
        pump()
        check("Mapa 2 solo ve sus capas (QgsProject.mapLayers)", names() == ["Ciudades"], names())
        combo = QgsMapLayerComboBox()
        check("los selectores de capas de otros complementos solo ven el mapa activo",
              [combo.itemText(i) for i in range(combo.count())] == ["Ciudades"],
              [combo.itemText(i) for i in range(combo.count())])
        check("el panel de capas solo muestra el mapa activo",
              [n.name() for n in prj.layerTreeRoot().findLayers()] == ["Ciudades"])
        # Processing (otro complemento) trabaja sobre el mapa activo
        try:
            import processing
            from processing.core.Processing import Processing
            Processing.initialize()
            res = processing.runAndLoadResults("native:buffer", {"INPUT": b.id(), "DISTANCE": 0.5,
                                                                 "SEGMENTS": 5, "OUTPUT": "memory:"})
            pump()
            check("Processing: el resultado cae en el mapa activo", "Buffered" in " ".join(names()) or len(names()) == 2, names())
        except Exception as e:
            check("Processing ejecuta sobre el mapa activo", False, e)
        n2 = set(names())
        # cambiar al mapa 1
        m1 = p.maps[0]["id"]
        p.activate(m1)
        pump()
        check("al volver a Mapa 1 solo se ven sus capas", names() == ["Rios"], names())
        check("capa activa es del mapa activo", iface.activeLayer() is None or iface.activeLayer().name() == "Rios",
              iface.activeLayer().name() if iface.activeLayer() else None)
        p.activate(m2)
        pump()
        check("Mapa 2 conserva sus capas (incluido el resultado de Processing)", set(names()) == n2, names())
        # seleccion y edicion por mapa
        b2 = prj.mapLayersByName("Ciudades")[0]
        b2.selectByIds([f.id() for f in b2.getFeatures()][:2])
        b2.startEditing()
        f = next(b2.getFeatures())
        b2.changeAttributeValue(f.id(), 0, "editado")
        p._ask_edit_choice = lambda names: "save"
        p.activate(m1)
        pump()
        check("al cambiar de mapa con edicion pendiente se guarda (respuesta Guardar)",
              not b2.isEditable() and any(ft["nombre"] == "editado" for ft in b2.getFeatures()))
        p.activate(m2)
        pump()
        check("la seleccion se conserva por mapa", prj.mapLayersByName("Ciudades")[0].selectedFeatureCount() == 2,
              prj.mapLayersByName("Ciudades")[0].selectedFeatureCount())
        # CRS por mapa
        from qgis.core import QgsCoordinateReferenceSystem
        iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        pump()
        p.activate(m1)
        pump()
        c1 = iface.mapCanvas().mapSettings().destinationCrs().authid()
        p.activate(m2)
        pump()
        c2 = iface.mapCanvas().mapSettings().destinationCrs().authid()
        check("CRS independiente por mapa", c1 != "EPSG:3857" and c2 == "EPSG:3857", (c1, c2))
        check("el CRS del proyecto sigue al mapa activo", prj.crs().authid() == c2, prj.crs().authid())

        # ---------------------------------------------------------- orden de capas por mapa
        root = prj.layerTreeRoot()
        lays = [n.layer() for n in root.findLayers()]
        root.setHasCustomLayerOrder(True)
        root.setCustomLayerOrder(list(reversed(lays)))
        p.activate(m1)
        pump()
        check("Mapa 1 no hereda el orden personalizado de Mapa 2", not root.hasCustomLayerOrder())
        p.activate(m2)
        pump()
        check("Mapa 2 recupera su orden personalizado", root.hasCustomLayerOrder())

        # ---------------------------------------------------------- cerrar / catalogo / eliminar
        p.add_map()
        pump()
        m3 = p.active_id
        check("cerrar la vista no borra el mapa", p.close_map_view(m3) and p._get(m3) is not None)
        check("la pestana cerrada desaparece de la barra",
              all(p._tab_key(i) != "map:" + m3 for i in range(p.tabbar.count())))
        check("el catalogo lista el mapa cerrado",
              any(p.catalog.tree.topLevelItem(0).child(i).text(0) == p._get(m3)["name"]
                  for i in range(p.catalog.tree.topLevelItem(0).childCount())))
        check("reabrir desde el catalogo", p.open_map(m3) and p.active_id == m3)
        check("eliminar mapa desde el catalogo", p.delete_map(m3) and p._get(m3) is None)
        pump()

        # ---------------------------------------------------------- vistas lado a lado + enlace
        p.activate(m2)
        pump()
        v = p.open_side_map(m1)
        pump()
        check("abrir al lado crea vista acoplada", v is not None and v.isVisible())
        check("la vista acoplada dibuja las capas de su mapa (fuera del registro)",
              [l.name() for l in v.canvas.layers()] == ["Rios"], [l.name() for l in v.canvas.layers()])
        check("el registro sigue aislado con la vista acoplada", "Rios" not in names(), names())
        p.set_link_mode("scale")
        iface.mapCanvas().zoomScale(50000)
        pump()
        check("navegacion enlazada (escala)", abs(v.canvas.scale() - 50000) / 50000 < 0.05, v.canvas.scale())
        p.set_link_mode("none")
        p.swap_side_map(m1)
        pump(15)
        check("Activar intercambia: Mapa 1 al lienzo principal", p.active_id == m1 and names() == ["Rios"], names())
        check("Activar intercambia: Mapa 2 a la vista acoplada", p._side_ids() == [m2], p._side_ids())
        p._close_floating_map(m2)
        pump()
        check("cerrar vista acoplada", p._side_ids() == [] and not p._side_column.isVisible())

        # ---------------------------------------------------------- layouts
        n_before = len(prj.layoutManager().printLayouts())
        p.new_layout()
        pump(30)
        check("nuevo Layout crea pestana", any(p._tab_key(i).startswith("layout:") for i in range(p.tabbar.count())))
        check("el disenador queda integrado", p._active_designer is not None and p.view_stack.currentWidget() is p._active_designer.window())
        check("pestanas del Layout encima de la hoja (no barra de respaldo)",
              p._layout_placer is not None, "respaldo" if p._layout_fallback_tb else "")
        row = p._layout_row
        check("pestanas del Layout visibles", row.isVisible())
        try:
            dwin = p._active_designer.window()
            view = p._active_designer.view()
            ry = row.mapTo(dwin, QPoint(0, 0)).y() + row.height()
            vy = view.mapTo(dwin, QPoint(0, 0)).y()
            check("las pestanas no tapan la hoja del Layout", ry <= vy + 2, "fila hasta %d, hoja desde %d" % (ry, vy))
        except Exception as e:
            check("posicion de pestanas en Layout", False, e)
        lay = p._current_layout()
        # plantillas
        from multimap_layout import templates
        tpl = os.path.join(templates.user_template_dir(), "PruebaMM.qpt")
        templates.save_template(lay, tpl)
        check("guardar plantilla en carpeta general", os.path.isfile(tpl), tpl)
        p.template_new(tpl)
        pump(30)
        check("nuevo Layout desde plantilla", prj.layoutManager().layoutByName("PruebaMM") is not None,
              [l.name() for l in prj.layoutManager().printLayouts()])
        # volver a mapas
        p._on_tab_changed(next(i for i in range(p.tabbar.count()) if p._tab_key(i).startswith("map:")))
        pump(10)
        check("volver a la vista de mapas restaura menus", win.menuBar().isVisible() and p.view_stack.currentWidget() is p._map_page)

        # ---------------------------------------------------------- guardar / abrir
        path = os.path.join(WORK, "prueba_mm.qgz")
        for l in list(p._hidden.values()) + list(prj.mapLayers().values()):
            pass
        # capas temporales no se guardan: se usan geopackage
        gpkg = os.path.join(WORK, "datos.gpkg")
        from qgis.core import QgsVectorFileWriter
        p.activate(m2)
        pump()
        city = prj.mapLayersByName("Ciudades")[0]
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = "ciudades"
        QgsVectorFileWriter.writeAsVectorFormatV3(city, gpkg, prj.transformContext(), opts)
        g = QgsVectorLayer(gpkg + "|layername=ciudades", "CiudadesGPKG", "ogr")
        prj.addMapLayer(g)
        pump()
        state_maps = [(m["name"]) for m in p.maps]
        ok = prj.write(path)
        pump(30)
        check("guardar proyecto", ok)
        log("... proyecto nuevo (como el usuario)")
        iface.newProject(False)
        pump(20)
        log("... abriendo proyecto (como el usuario)")
        ok = iface.addProject(path)
        pump(40)
        check("abrir proyecto", ok)
        check("se recuperan los mapas", [m["name"] for m in p.maps] == state_maps, [m["name"] for m in p.maps])
        p.activate(next(m["id"] for m in p.maps if m["name"] == "Mapa 2"))
        pump()
        check("las capas guardadas vuelven a su mapa", "CiudadesGPKG" in names(), names())
        # formato portable: abrir el archivo sin el complemento muestra todo
        from qgis.core import QgsProject as QP
        other = QP()
        other.read(path)
        allnames = sorted(l.name() for l in other.mapLayers().values())
        check("proyecto portable: sin el complemento se ven las capas de todos los mapas",
              "CiudadesGPKG" in allnames, allnames)

        # ---------------------------------------------------------- otros complementos: senales
        seen = []
        prj.layersAdded.connect(lambda ls: seen.append(("add", [l.name() for l in ls])))
        prj.layersRemoved.connect(lambda ids: seen.append(("rem", len(ids))))
        p.activate(next(m["id"] for m in p.maps if m["name"] == "Mapa 1"))
        pump()
        check("cambiar de mapa emite layersRemoved/layersAdded (los complementos se enteran)",
              any(s[0] == "rem" for s in seen) and any(s[0] == "add" for s in seen), seen)

        # ---------------------------------------------------------- descarga
        qgis.utils.unloadPlugin("multimap_layout")
        pump(20)
        check("al desactivar, el widget central original vuelve", win.centralWidget() is p._main_central)
        check("al desactivar, las capas de otros mapas vuelven al proyecto", "CiudadesGPKG" in names(), names())
    except Exception:
        check("excepcion inesperada", False, traceback.format_exc())
    log("FIN: %d fallos" % len(fails))
    QTimer.singleShot(200, QgsApplication.instance().exit)


def _msg(message, tag, level):
    if tag in ("Python error", "Python warning") or "Traceback" in message:
        log("PYTHON [%s]: %s" % (tag, message[-1500:]))
QgsApplication.messageLog().messageReceived.connect(_msg)


def watchdog():
    w = QApplication.activeModalWidget() or QApplication.activePopupWidget()
    if w is not None:
        txt = getattr(w, "text", lambda: "")()
        log("MODAL abierto: %s %r %r" % (type(w).__name__, w.windowTitle(), txt))
        w.close()
    QTimer.singleShot(1500, watchdog)


QTimer.singleShot(3000, run)
QTimer.singleShot(4000, watchdog)
