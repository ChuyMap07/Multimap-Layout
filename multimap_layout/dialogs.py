# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from .common import qenum

_CHECKABLE = qenum(Qt, "ItemFlag", "ItemIsUserCheckable")
_CHECKED = qenum(Qt, "CheckState", "Checked")
_USER_ROLE = qenum(Qt, "ItemDataRole", "UserRole")
_KEY_ESC = qenum(Qt, "Key", "Key_Escape")


class LayoutDialog(QDialog):
    """Opciones para crear un layout con un elemento de mapa por pestana."""

    def __init__(self, parent, maps, default_name):
        super().__init__(parent)
        self.setWindowTitle("Crear layout con los mapas")

        self.name_edit = QLineEdit(default_name)
        self.list = QListWidget()
        for m in maps:
            it = QListWidgetItem(m["name"])
            it.setFlags(it.flags() | _CHECKABLE)
            it.setCheckState(_CHECKED)
            it.setData(_USER_ROLE, m["id"])
            self.list.addItem(it)
        self.chk_titles = QCheckBox("Título sobre cada mapa")
        self.chk_titles.setChecked(True)
        self.chk_legends = QCheckBox("Leyenda en cada mapa")
        self.chk_legends.setChecked(True)

        form = QFormLayout()
        form.addRow("Nombre del layout:", self.name_edit)
        form.addRow("Mapas a incluir:", self.list)
        form.addRow("", self.chk_titles)
        form.addRow("", self.chk_legends)

        buttons = QDialogButtonBox(
            qenum(QDialogButtonBox, "StandardButton", "Ok")
            | qenum(QDialogButtonBox, "StandardButton", "Cancel")
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def name(self):
        return self.name_edit.text().strip()

    def selected_ids(self):
        ids = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == _CHECKED:
                ids.append(it.data(_USER_ROLE))
        return ids

    def with_titles(self):
        return self.chk_titles.isChecked()

    def with_legends(self):
        return self.chk_legends.isChecked()


class TabNameEdit(QLineEdit):
    """Editor de nombre que se coloca encima de una pestana (Esc cancela)."""

    cancelled = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == _KEY_ESC:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)
