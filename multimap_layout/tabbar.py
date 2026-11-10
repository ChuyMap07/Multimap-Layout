# -*- coding: utf-8 -*-
"""Barra de pestanas con el aspecto de ArcGIS Pro (pestana activa rellena en verde).

* Pestanas planas y delgadas, con icono de mapa a la izquierda.
* La pestana activa va rellena de verde con texto blanco.
* El boton de cerrar solo aparece en la pestana activa y en la que esta bajo el cursor.
* La barra se coloca dentro del widget central de QGIS, pegada al lienzo (sin dock).
Los colores salen de la paleta de QGIS, asi que funciona en tema claro y oscuro.
"""
import os

from qgis.PyQt.QtCore import QEvent, QObject, QPoint, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QIcon, QPalette
from qgis.PyQt.QtWidgets import QApplication, QTabBar, QToolButton

from .common import qenum

ACCENT = "#2a8a54"


def tab_icon():
    base = os.path.dirname(__file__)
    icon = QIcon()
    icon.addFile(os.path.join(base, "map_tab.svg"), QSize(), qenum(QIcon, "Mode", "Normal"))
    icon.addFile(os.path.join(base, "map_tab_active.svg"), QSize(), qenum(QIcon, "Mode", "Selected"))
    return icon


def style_colors(sample=None):
    """Colores de la barra. 'sample' es el color real del fondo de QGIS (lo fija el tema con
    hojas de estilo, asi que la paleta no sirve); sin muestra se deriva de la paleta."""
    exact = sample is not None and sample.isValid()
    win = sample if exact else QApplication.palette().color(qenum(QPalette, "ColorRole", "Window"))
    if win.lightness() < 128:
        strip = win if exact else win.darker(125)
        return {
            "accent": ACCENT, "strip": strip.name(),
            "hover": strip.lighter(125).name(), "press": strip.lighter(155).name(),
            "text": "#ffffff", "dim": "#b4b4b4",
        }
    strip = win if exact else win.darker(106)
    return {
        "accent": ACCENT, "strip": strip.name(),
        "hover": strip.darker(108).name(), "press": strip.darker(118).name(),
        "text": "#1a1a1a", "dim": "#555555",
    }


def strip_stylesheet(c):
    return "#mmStrip { background: %s; }" % c["strip"]


def tabbar_stylesheet(c, h):
    d = dict(c, inner=max(h - 4, 12))
    return (
        "QTabBar { background: %(strip)s; border: none; }"
        "QTabBar::tab { background: %(strip)s; color: %(dim)s; border: none;"
        " padding: 2px 4px 2px 6px; min-height: %(inner)dpx; max-height: %(inner)dpx;"
        " margin: 0px; max-width: 220px; }"
        "QTabBar::tab:selected { background: %(accent)s; color: #ffffff; }"
        "QTabBar::tab:hover:!selected { background: %(hover)s; color: %(text)s; }"
        "QTabBar QToolButton { background: %(strip)s; border: none; }"
    ) % d


def close_button_stylesheet(c, selected):
    d = dict(c, fg="#ffffff" if selected else c["dim"],
             hov="rgba(255,255,255,70)" if selected else c["press"])
    return (
        "QToolButton { background: transparent; color: %(fg)s; border: none;"
        " border-radius: 2px; padding: 0px 2px; font-size: 8pt; }"
        "QToolButton:hover { background: %(hov)s; color: #ffffff; }"
    ) % d


def add_button_stylesheet(c):
    return (
        "QToolButton { background: transparent; color: %(dim)s; border: none;"
        " border-radius: 0px; padding: 0px; font-size: 11pt; }"
        "QToolButton:hover { background: %(hover)s; color: %(text)s; }"
        "QToolButton:pressed { background: %(press)s; }"
    ) % c


class ProTabBar(QTabBar):
    """QTabBar con botones de cierre propios (visibles solo en activa/hover)."""

    closeClicked = pyqtSignal(int)
    detachRequested = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.colors = style_colors()
        self._hover = -1
        self._pressed_key = None
        self._press_global = None
        self._side = qenum(QTabBar, "ButtonPosition", "RightSide")
        h = self.row_height()
        self.setFixedHeight(h)
        self.setMouseTracking(True)
        self.setTabsClosable(False)
        self.setMovable(True)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setDocumentMode(True)
        self.setUsesScrollButtons(True)
        self.setElideMode(qenum(Qt, "TextElideMode", "ElideRight"))
        self.setStyleSheet(tabbar_stylesheet(self.colors, h))
        self.currentChanged.connect(lambda *_: self.refresh_close_buttons())

    def apply_colors(self, colors):
        self.colors = colors
        self.setStyleSheet(tabbar_stylesheet(colors, self.row_height()))
        for i in range(self.count()):
            b = self.tabButton(i, self._side)
            if b is not None:
                b.setProperty("mm_sel", None)    # fuerza a re-aplicar el estilo del boton
        self.refresh_close_buttons()

    def row_height(self):
        # Margen visual pequeno para separar la barra del borde del lienzo.
        return max(22, self.fontMetrics().height() + 7)

    # ------------------------------------------------------------- pestanas
    def add_map_tab(self, icon, text, map_id):
        return self.add_view_tab(icon, text, "map:" + str(map_id), "Cerrar vista (el mapa sigue en el Catálogo)")

    def add_layout_tab(self, icon, text, layout_name):
        return self.add_view_tab(icon, text, "layout:" + str(layout_name), "Cerrar Layout")

    def add_view_tab(self, icon, text, view_key, close_tip):
        i = self.addTab(icon, text)
        self.setTabData(i, view_key)
        btn = QToolButton(self)
        btn.setText("\u2715")
        btn.setToolTip(close_tip)
        btn.setAutoRaise(True)
        btn.setFocusPolicy(qenum(Qt, "FocusPolicy", "NoFocus"))
        btn.setCursor(QCursor(qenum(Qt, "CursorShape", "ArrowCursor")))
        btn.setProperty("mm_sel", None)
        btn.clicked.connect(lambda _c=False, b=btn: self._on_close_clicked(b))
        self.setTabButton(i, self._side, btn)
        return i

    def _on_close_clicked(self, btn):
        idx = self.tabAt(btn.mapTo(self, btn.rect().center()))
        if idx >= 0:
            self.closeClicked.emit(idx)

    def refresh_close_buttons(self):
        cur = self.currentIndex()
        for i in range(self.count()):
            b = self.tabButton(i, self._side)
            if b is None:
                continue
            sel = (i == cur)
            if b.property("mm_sel") != sel:      # el estilo cambia entre activa e inactiva
                b.setProperty("mm_sel", sel)
                b.setStyleSheet(close_button_stylesheet(self.colors, sel))
            b.setVisible(sel or i == self._hover)

    # --------------------------------------------------------------- hover
    def _set_hover(self, idx):
        if idx != self._hover:
            self._hover = idx
            self.refresh_close_buttons()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        self._set_hover(self.tabAt(pos))

    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        idx = self.tabAt(pos)
        self._pressed_key = self.tabData(idx) if idx >= 0 else None
        self._press_global = (event.globalPosition().toPoint() if hasattr(event, "globalPosition")
                              else event.globalPos())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        global_pos = (event.globalPosition().toPoint() if hasattr(event, "globalPosition")
                      else event.globalPos())
        moved = (self._press_global is not None and
                 (global_pos - self._press_global).manhattanLength() >= QApplication.startDragDistance())
        detach_key = (self._pressed_key if moved and self._pressed_key is not None
                      and not self.rect().contains(pos) else None)
        super().mouseReleaseEvent(event)
        self._pressed_key = None
        self._press_global = None
        if detach_key is not None:
            for i in range(self.count()):
                if self.tabData(i) == detach_key:
                    self.detachRequested.emit(i, global_pos)
                    break

    def leaveEvent(self, event):
        super().leaveEvent(event)
        # El cursor puede haber pasado al boton de cerrar (hijo de la barra): no cuenta como salir.
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._set_hover(-1)


class StripPlacer(QObject):
    """Coloca la barra encima del lienzo, dentro del widget central de QGIS.

    Se reserva arriba un margen del alto de la barra en el layout del widget central
    y la barra se superpone en ese hueco: queda pegada al lienzo, sin separadores de dock."""

    def __init__(self, strip, host, canvas=None):
        super().__init__(host)
        lay = host.layout() if host is not None else None
        if lay is None:
            raise ValueError("el widget central no tiene layout")
        self.strip, self.host, self.lay = strip, host, lay
        self._saved = lay.contentsMargins()
        m = self._saved
        # El lienzo de QGIS empieza unos px mas abajo que su contenedor (marco): ese hueco
        # se cubre con la barra para que quede realmente pegada al mapa.
        off = 2
        if canvas is not None:
            try:
                lay.activate()
                y = canvas.viewport().mapTo(host, QPoint(0, 0)).y() - m.top()
                if 1 <= y <= 4:
                    off = y
            except Exception:
                pass
        lay.setContentsMargins(m.left(), m.top() + max(strip.height() - off, 0), m.right(), m.bottom())
        strip.setParent(host)
        self.place()
        strip.show()
        host.installEventFilter(self)

    def place(self):
        self.strip.setGeometry(0, 0, self.host.width(), self.strip.height())
        self.strip.raise_()

    def eventFilter(self, obj, event):
        if obj is self.host and event.type() in (
            qenum(QEvent, "Type", "Resize"), qenum(QEvent, "Type", "Show")
        ):
            self.place()
        return False

    def remove(self):
        try:
            self.host.removeEventFilter(self)
            m = self._saved
            self.lay.setContentsMargins(m.left(), m.top(), m.right(), m.bottom())
            self.strip.hide()
            self.strip.setParent(None)
            self.strip.deleteLater()
        except RuntimeError:
            pass    # QGIS ya esta cerrando la ventana
