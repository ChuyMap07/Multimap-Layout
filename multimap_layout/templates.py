# -*- coding: utf-8 -*-
"""Plantillas de Layout (.qpt) a mano desde la barra de pestañas del Layout.

Usa la misma carpeta de plantillas de QGIS (perfil de usuario > composer_templates, mas las rutas
de busqueda configuradas en QGIS), de modo que lo que se guarda aqui aparece tambien en el
Administrador de diseños de QGIS y viceversa."""
import os

from qgis.PyQt.QtCore import QFile, QIODevice, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtXml import QDomDocument
from qgis.core import QgsApplication, QgsPrintLayout, QgsProject, QgsReadWriteContext, QgsSettings


def user_template_dir():
    path = os.path.join(QgsApplication.qgisSettingsDirPath(), "composer_templates")
    os.makedirs(path, exist_ok=True)
    return path


def template_dirs():
    dirs = [user_template_dir()]
    try:
        extra = QgsSettings().value("core/Layout/searchPathsForTemplates", [])
        if isinstance(extra, str):
            extra = [extra] if extra else []
        dirs.extend(str(d) for d in extra or [])
    except Exception:
        pass
    project_dir = QgsProject.instance().homePath()
    if project_dir:
        dirs.append(os.path.join(project_dir, "plantillas"))
    out = []
    for d in dirs:
        if d and os.path.isdir(d) and os.path.normcase(os.path.abspath(d)) not in [
                os.path.normcase(os.path.abspath(o)) for o in out]:
            out.append(d)
    return out


def list_templates():
    """[(nombre visible, ruta)] ordenadas por nombre."""
    found = []
    for d in template_dirs():
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if n.lower().endswith(".qpt"):
                found.append((os.path.splitext(n)[0], os.path.join(d, n)))
    return sorted(found, key=lambda t: t[0].lower())


def _read_doc(path):
    f = QFile(path)
    if not f.open(QIODevice.OpenModeFlag.ReadOnly if hasattr(QIODevice, "OpenModeFlag") else QIODevice.ReadOnly):
        raise IOError("no se pudo abrir %s" % path)
    try:
        doc = QDomDocument()
        res = doc.setContent(f)
        ok = res[0] if isinstance(res, tuple) else bool(res)
        if not ok:
            raise ValueError("la plantilla no es un XML válido")
        return doc
    finally:
        f.close()


def _context():
    ctx = QgsReadWriteContext()
    ctx.setPathResolver(QgsProject.instance().pathResolver())
    return ctx


def save_template(layout, path):
    if not path.lower().endswith(".qpt"):
        path += ".qpt"
    if not layout.saveAsTemplate(path, _context()):
        raise IOError("QGIS no pudo escribir la plantilla")
    return path


def load_into(layout, path, clear=True):
    """Carga la plantilla en 'layout' (clear=True reemplaza su contenido). Devuelve los elementos."""
    res = layout.loadFromTemplate(_read_doc(path), _context(), clear)
    items, ok = res if isinstance(res, tuple) else (res, True)
    if not ok:
        raise ValueError("QGIS no pudo cargar la plantilla")
    return items or []


def new_layout_from(path, name):
    project = QgsProject.instance()
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    load_into(layout, path, clear=True)
    layout.setName(name)
    if not project.layoutManager().addLayout(layout):
        raise ValueError("no se pudo agregar el Layout al proyecto")
    return layout


def open_folder():
    QDesktopServices.openUrl(QUrl.fromLocalFile(user_template_dir()))
