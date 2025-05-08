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
    QPushButton, QSizePolicy, QWidget)

class Ui_SetupVirtualHandInterface(object):
    def setupUi(self, SetupVirtualHandInterface):
        if not SetupVirtualHandInterface.objectName():
            SetupVirtualHandInterface.setObjectName(u"SetupVirtualHandInterface")
        SetupVirtualHandInterface.resize(361, 78)
        self.gridLayout = QGridLayout(SetupVirtualHandInterface)
        self.gridLayout.setObjectName(u"gridLayout")
        self.groupBox = QGroupBox(SetupVirtualHandInterface)
        self.groupBox.setObjectName(u"groupBox")
        self.gridLayout_31 = QGridLayout(self.groupBox)
        self.gridLayout_31.setObjectName(u"gridLayout_31")
        self.useExternalVirtualHandInterfaceCheckBox = QCheckBox(self.groupBox)
        self.useExternalVirtualHandInterfaceCheckBox.setObjectName(u"useExternalVirtualHandInterfaceCheckBox")

        self.gridLayout_31.addWidget(self.useExternalVirtualHandInterfaceCheckBox, 0, 4, 1, 1)

        self.virtualHandInterfaceStatusWidget = QWidget(self.groupBox)
        self.virtualHandInterfaceStatusWidget.setObjectName(u"virtualHandInterfaceStatusWidget")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.virtualHandInterfaceStatusWidget.sizePolicy().hasHeightForWidth())
        self.virtualHandInterfaceStatusWidget.setSizePolicy(sizePolicy)
        self.virtualHandInterfaceStatusWidget.setMinimumSize(QSize(10, 10))
        self.virtualHandInterfaceStatusWidget.setStyleSheet(u"border-radius: 5px;")

        self.gridLayout_31.addWidget(self.virtualHandInterfaceStatusWidget, 0, 3, 1, 1)

        self.toggleVirtualHandInterfacePushButton = QPushButton(self.groupBox)
        self.toggleVirtualHandInterfacePushButton.setObjectName(u"toggleVirtualHandInterfacePushButton")
        self.toggleVirtualHandInterfacePushButton.setCheckable(True)

        self.gridLayout_31.addWidget(self.toggleVirtualHandInterfacePushButton, 0, 0, 1, 2)


        self.gridLayout.addWidget(self.groupBox, 0, 0, 1, 1)


        self.retranslateUi(SetupVirtualHandInterface)

        QMetaObject.connectSlotsByName(SetupVirtualHandInterface)
    # setupUi

    def retranslateUi(self, SetupVirtualHandInterface):
        SetupVirtualHandInterface.setWindowTitle(QCoreApplication.translate("SetupVirtualHandInterface", u"Form", None))
        self.groupBox.setTitle(QCoreApplication.translate("SetupVirtualHandInterface", u"Virtual Hand Interface", None))
        self.useExternalVirtualHandInterfaceCheckBox.setText(QCoreApplication.translate("SetupVirtualHandInterface", u"Use external Virtual Hand Interface", None))
        self.toggleVirtualHandInterfacePushButton.setText(QCoreApplication.translate("SetupVirtualHandInterface", u"Open", None))
    # retranslateUi

