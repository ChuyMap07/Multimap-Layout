# -*- coding: utf-8 -*-
"""Proyecto portable: las capas de los otros mapas, que el complemento guarda en un elemento propio,
se convierten (justo despues de guardar) en capas y grupos NORMALES del proyecto, para que cualquier
QGIS (sin el complemento) las vea y no se pierdan si se vuelve a guardar. Con el complemento, esos
grupos se reconocen por su marca y las capas vuelven a salir del registro.

Se trabaja con el mismo analizador XML que usa QGIS (QDomDocument), se valida el resultado y el
archivo se reemplaza de forma atomica: si algo falla, queda el archivo original intacto."""
import os
import tempfile
import zipfile

from qgis.PyQt.QtXml import QDomDocument

HIDDEN_TAG = "multimap_hidden_layers"
GROUP_PROP = "multimap_hidden"


def _read_qgs(path):
    if path.lower().endswith(".qgz"):
        with zipfile.ZipFile(path) as z:
            member = next((n for n in z.namelist() if n.lower().endswith(".qgs")), None)
            if member is None:
                raise ValueError("el .qgz no contiene un .qgs")
            return member, z.read(member).decode("utf-8")
    with open(path, encoding="utf-8") as f:
        return None, f.read()


def _write_qgs(path, member, text):
    fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(path)[1], dir=os.path.dirname(path) or ".", prefix=".mm_")
    os.close(fd)
    try:
        if member is not None:
            with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = text.encode("utf-8") if item.filename == member else zin.read(item.filename)
                    zout.writestr(item, data)
        else:
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _parse(text):
    doc = QDomDocument()
    res = doc.setContent(text)
    ok = res[0] if isinstance(res, tuple) else bool(res)
    if not ok:
        raise ValueError("XML del proyecto no valido")
    return doc


def _count(doc, tag):
    return doc.documentElement().firstChildElement("projectlayers").elementsByTagName(tag).count()


def make_portable(path, groups):
    """groups: [(nombre del grupo, [ids de capa en orden])]. Devuelve True si el archivo se convirtio."""
    member, text = _read_qgs(path)
    doc = _parse(text)
    root = doc.documentElement()
    hid = root.firstChildElement(HIDDEN_TAG)
    projectlayers = root.firstChildElement("projectlayers")
    tree = root.firstChildElement("layer-tree-group")
    if hid.isNull() or projectlayers.isNull() or tree.isNull():
        return False
    before = _count(doc, "maplayer")
    layers = {}
    child = hid.firstChildElement("maplayer")
    while not child.isNull():
        layers[child.firstChildElement("id").text()] = child
        child = child.nextSiblingElement("maplayer")
    if not layers:
        return False
    grouped = set()
    plan = []
    for name, ids in groups:
        ids = [i for i in ids if i in layers and i not in grouped]
        if ids:
            plan.append((name, ids))
            grouped.update(ids)
    rest = [i for i in layers if i not in grouped]
    if rest:
        plan.append(("Capas sin mapa (Multimap)", rest))
    for name, ids in plan:
        g = doc.createElement("layer-tree-group")
        g.setAttribute("name", name)
        g.setAttribute("checked", "Qt::Unchecked")
        g.setAttribute("expanded", "0")
        cp = doc.createElement("customproperties")
        opt = doc.createElement("Option")
        opt.setAttribute("type", "Map")
        flag = doc.createElement("Option")
        flag.setAttribute("name", GROUP_PROP)
        flag.setAttribute("value", "1")
        flag.setAttribute("type", "QString")
        opt.appendChild(flag)
        cp.appendChild(opt)
        g.appendChild(cp)
        for lid in ids:
            ml = layers[lid]
            n = doc.createElement("layer-tree-layer")
            n.setAttribute("id", lid)
            n.setAttribute("name", ml.firstChildElement("layername").text())
            n.setAttribute("source", ml.firstChildElement("datasource").text())
            n.setAttribute("providerKey", ml.firstChildElement("provider").text())
            n.setAttribute("checked", "Qt::Unchecked")
            n.setAttribute("expanded", "0")
            n.setAttribute("patch_size", "-1,-1")
            n.setAttribute("legend_exp", "")
            n.setAttribute("legend_split_behavior", "0")
            cp2 = doc.createElement("customproperties")
            cp2.appendChild(doc.createElement("Option"))
            n.appendChild(cp2)
            g.appendChild(n)
        tree.appendChild(g)
    for ml in layers.values():
        hid.removeChild(ml)
        projectlayers.appendChild(ml)
    root.removeChild(hid)
    new_text = doc.toString(2)
    check = _parse(new_text)
    if _count(check, "maplayer") != before + len(layers):
        raise ValueError("la validacion del proyecto convertido no coincide")
    _write_qgs(path, member, new_text)
    return True
