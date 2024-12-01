# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'umap_window.ui'
##
## Created by: Qt User Interface Compiler version 6.8.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QPushButton, QSizePolicy,
    QSpacerItem, QStatusBar, QVBoxLayout, QWidget)

class Ui_UMAP(object):
    def setupUi(self, UMAP):
        if not UMAP.objectName():
            UMAP.setObjectName(u"UMAP")
        UMAP.resize(944, 729)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(UMAP.sizePolicy().hasHeightForWidth())
        UMAP.setSizePolicy(sizePolicy)
        UMAP.setAcceptDrops(False)
        UMAP.setAutoFillBackground(False)
        self.actionPreferences = QAction(UMAP)
        self.actionPreferences.setObjectName(u"actionPreferences")
        self.actionPreferences.setEnabled(True)
        self.centralwidget = QWidget(UMAP)
        self.centralwidget.setObjectName(u"centralwidget")
        self.gridLayout = QGridLayout(self.centralwidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.verticalLayout_2 = QVBoxLayout()
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.groupBox = QGroupBox(self.centralwidget)
        self.groupBox.setObjectName(u"groupBox")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.groupBox.sizePolicy().hasHeightForWidth())
        self.groupBox.setSizePolicy(sizePolicy1)
        self.horizontalLayout = QHBoxLayout(self.groupBox)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.trainingSelectDatasetPushButton = QPushButton(self.groupBox)
        self.trainingSelectDatasetPushButton.setObjectName(u"trainingSelectDatasetPushButton")

        self.horizontalLayout.addWidget(self.trainingSelectDatasetPushButton)

        self.trainingSelectedDatasetLabel = QLabel(self.groupBox)
        self.trainingSelectedDatasetLabel.setObjectName(u"trainingSelectedDatasetLabel")

        self.horizontalLayout.addWidget(self.trainingSelectedDatasetLabel)


        self.verticalLayout_2.addWidget(self.groupBox)

        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer)

        self.pushButton = QPushButton(self.centralwidget)
        self.pushButton.setObjectName(u"pushButton")
        sizePolicy1.setHeightForWidth(self.pushButton.sizePolicy().hasHeightForWidth())
        self.pushButton.setSizePolicy(sizePolicy1)

        self.horizontalLayout_2.addWidget(self.pushButton)

        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer_2)


        self.verticalLayout_2.addLayout(self.horizontalLayout_2)


        self.gridLayout.addLayout(self.verticalLayout_2, 0, 0, 1, 1)

        UMAP.setCentralWidget(self.centralwidget)
        self.statusbar = QStatusBar(UMAP)
        self.statusbar.setObjectName(u"statusbar")
        UMAP.setStatusBar(self.statusbar)

        self.retranslateUi(UMAP)

        QMetaObject.connectSlotsByName(UMAP)
    # setupUi

    def retranslateUi(self, UMAP):
        UMAP.setWindowTitle(QCoreApplication.translate("UMAP", u"UMAP Monitoring Widget", None))
        self.actionPreferences.setText(QCoreApplication.translate("UMAP", u"Preferences", None))
        self.groupBox.setTitle(QCoreApplication.translate("UMAP", u"Dataset", None))
        self.trainingSelectDatasetPushButton.setText(QCoreApplication.translate("UMAP", u"Select Dataset", None))
        self.trainingSelectedDatasetLabel.setText(QCoreApplication.translate("UMAP", u"Placeholder", None))
        self.pushButton.setText(QCoreApplication.translate("UMAP", u"Create UMAP model", None))
    # retranslateUi

