# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'biosignal.ui'
##
## Created by: Qt User Interface Compiler version 6.8.0
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
from PySide6.QtWidgets import (QApplication, QGridLayout, QGroupBox, QSizePolicy,
    QWidget)

from biosignal_device_interface.devices import OTBDevicesWidget

class Ui_BioSignalInterface(object):
    def setupUi(self, BioSignalInterface):
        if not BioSignalInterface.objectName():
            BioSignalInterface.setObjectName(u"BioSignalInterface")
        BioSignalInterface.resize(400, 300)
        self.gridLayout = QGridLayout(BioSignalInterface)
        self.gridLayout.setObjectName(u"gridLayout")
        self.groupBox = QGroupBox(BioSignalInterface)
        self.groupBox.setObjectName(u"groupBox")
        self.gridLayout_2 = QGridLayout(self.groupBox)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.devicesWidget = OTBDevicesWidget(self.groupBox)
        self.devicesWidget.setObjectName(u"devicesWidget")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.devicesWidget.sizePolicy().hasHeightForWidth())
        self.devicesWidget.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.devicesWidget, 0, 0, 1, 1)


        self.gridLayout.addWidget(self.groupBox, 0, 0, 1, 1)


        self.retranslateUi(BioSignalInterface)

        QMetaObject.connectSlotsByName(BioSignalInterface)
    # setupUi

    def retranslateUi(self, BioSignalInterface):
        BioSignalInterface.setWindowTitle(QCoreApplication.translate("BioSignalInterface", u"Form", None))
        self.groupBox.setTitle(QCoreApplication.translate("BioSignalInterface", u"Biosignal Device Interface", None))
    # retranslateUi

