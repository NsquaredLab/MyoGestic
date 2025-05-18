# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'setup.ui'
##
## Created by: Qt User Interface Compiler version 6.6.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QGridLayout, QGroupBox,
    QPushButton, QSizePolicy, QSpacerItem, QWidget)

class Ui_SetupVirtualCursorInterface(object):
    def setupUi(self, SetupVirtualCursorInterface):
        if not SetupVirtualCursorInterface.objectName():
            SetupVirtualCursorInterface.setObjectName(u"SetupVirtualCursorInterface")
        SetupVirtualCursorInterface.resize(360, 78)
        self.gridLayout = QGridLayout(SetupVirtualCursorInterface)
        self.gridLayout.setObjectName(u"gridLayout")
        self.groupBox = QGroupBox(SetupVirtualCursorInterface)
        self.groupBox.setObjectName(u"groupBox")
        self.gridLayout_31 = QGridLayout(self.groupBox)
        self.gridLayout_31.setObjectName(u"gridLayout_31")
        self.useExternalVirtualCursorInterfaceCheckBox = QCheckBox(self.groupBox)
        self.useExternalVirtualCursorInterfaceCheckBox.setObjectName(u"useExternalVirtualCursorInterfaceCheckBox")

        self.gridLayout_31.addWidget(self.useExternalVirtualCursorInterfaceCheckBox, 0, 4, 1, 1)

        self.toggleVirtualCursorInterfacePushButton = QPushButton(self.groupBox)
        self.toggleVirtualCursorInterfacePushButton.setObjectName(u"toggleVirtualCursorInterfacePushButton")
        self.toggleVirtualCursorInterfacePushButton.setCheckable(True)

        self.gridLayout_31.addWidget(self.toggleVirtualCursorInterfacePushButton, 0, 0, 1, 2)

        self.virtualCursorInterfaceStatusWidget = QWidget(self.groupBox)
        self.virtualCursorInterfaceStatusWidget.setObjectName(u"virtualCursorInterfaceStatusWidget")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.virtualCursorInterfaceStatusWidget.sizePolicy().hasHeightForWidth())
        self.virtualCursorInterfaceStatusWidget.setSizePolicy(sizePolicy)
        self.virtualCursorInterfaceStatusWidget.setMinimumSize(QSize(10, 10))
        self.virtualCursorInterfaceStatusWidget.setStyleSheet(u"border-radius: 5px;")

        self.gridLayout_31.addWidget(self.virtualCursorInterfaceStatusWidget, 0, 2, 1, 1)

        self.horizontalSpacer = QSpacerItem(17, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.gridLayout_31.addItem(self.horizontalSpacer, 0, 5, 1, 1)


        self.gridLayout.addWidget(self.groupBox, 0, 0, 1, 1)


        self.retranslateUi(SetupVirtualCursorInterface)

        QMetaObject.connectSlotsByName(SetupVirtualCursorInterface)
    # setupUi

    def retranslateUi(self, SetupVirtualCursorInterface):
        SetupVirtualCursorInterface.setWindowTitle(QCoreApplication.translate("SetupVirtualCursorInterface", u"Form", None))
        self.groupBox.setTitle(QCoreApplication.translate("SetupVirtualCursorInterface", u"Virtual Cursor Interface", None))
        self.useExternalVirtualCursorInterfaceCheckBox.setText(QCoreApplication.translate("SetupVirtualCursorInterface", u"Use ext. Virtual Cursor Interface", None))
        self.toggleVirtualCursorInterfacePushButton.setText(QCoreApplication.translate("SetupVirtualCursorInterface", u"Open", None))
    # retranslateUi

