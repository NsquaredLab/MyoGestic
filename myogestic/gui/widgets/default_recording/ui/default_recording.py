# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'default_recording.ui'
##
## Created by: Qt User Interface Compiler version 6.10.1
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
from PySide6.QtWidgets import (QApplication, QComboBox, QGridLayout, QGroupBox,
    QLabel, QLineEdit, QProgressBar, QPushButton,
    QSizePolicy, QSpinBox, QStackedWidget, QWidget)

class Ui_DefaultRecordingInterface(object):
    def setupUi(self, DefaultRecordingInterface):
        if not DefaultRecordingInterface.objectName():
            DefaultRecordingInterface.setObjectName(u"DefaultRecordingInterface")
        DefaultRecordingInterface.resize(400, 300)
        self.gridLayout = QGridLayout(DefaultRecordingInterface)
        self.gridLayout.setObjectName(u"gridLayout")
        self.recordRecordingGroupBox = QGroupBox(DefaultRecordingInterface)
        self.recordRecordingGroupBox.setObjectName(u"recordRecordingGroupBox")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.recordRecordingGroupBox.sizePolicy().hasHeightForWidth())
        self.recordRecordingGroupBox.setSizePolicy(sizePolicy)
        self.gridLayout_9 = QGridLayout(self.recordRecordingGroupBox)
        self.gridLayout_9.setObjectName(u"gridLayout_9")
        self.label = QLabel(self.recordRecordingGroupBox)
        self.label.setObjectName(u"label")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.label.sizePolicy().hasHeightForWidth())
        self.label.setSizePolicy(sizePolicy1)

        self.gridLayout_9.addWidget(self.label, 0, 0, 1, 1)

        self.recordTaskComboBox = QComboBox(self.recordRecordingGroupBox)
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.setObjectName(u"recordTaskComboBox")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.recordTaskComboBox.sizePolicy().hasHeightForWidth())
        self.recordTaskComboBox.setSizePolicy(sizePolicy2)
        self.recordTaskComboBox.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow)
        self.recordTaskComboBox.setIconSize(QSize(0, 0))

        self.gridLayout_9.addWidget(self.recordTaskComboBox, 0, 1, 1, 1)

        self.label_7 = QLabel(self.recordRecordingGroupBox)
        self.label_7.setObjectName(u"label_7")
        sizePolicy1.setHeightForWidth(self.label_7.sizePolicy().hasHeightForWidth())
        self.label_7.setSizePolicy(sizePolicy1)

        self.gridLayout_9.addWidget(self.label_7, 1, 0, 1, 1)

        self.recordDurationSpinBox = QSpinBox(self.recordRecordingGroupBox)
        self.recordDurationSpinBox.setObjectName(u"recordDurationSpinBox")
        self.recordDurationSpinBox.setValue(10)

        self.gridLayout_9.addWidget(self.recordDurationSpinBox, 1, 1, 1, 1)

        self.recordRecordPushButton = QPushButton(self.recordRecordingGroupBox)
        self.recordRecordPushButton.setObjectName(u"recordRecordPushButton")
        self.recordRecordPushButton.setCheckable(True)

        self.gridLayout_9.addWidget(self.recordRecordPushButton, 2, 0, 1, 2)

        self.groundTruthProgressBar = QProgressBar(self.recordRecordingGroupBox)
        self.groundTruthProgressBar.setObjectName(u"groundTruthProgressBar")
        self.groundTruthProgressBar.setValue(0)

        self.gridLayout_9.addWidget(self.groundTruthProgressBar, 3, 0, 1, 2)


        self.gridLayout.addWidget(self.recordRecordingGroupBox, 0, 0, 1, 1)

        self.recordReviewRecordingStackedWidget = QStackedWidget(DefaultRecordingInterface)
        self.recordReviewRecordingStackedWidget.setObjectName(u"recordReviewRecordingStackedWidget")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.recordReviewRecordingStackedWidget.sizePolicy().hasHeightForWidth())
        self.recordReviewRecordingStackedWidget.setSizePolicy(sizePolicy3)
        self.emptyWidget_2 = QWidget()
        self.emptyWidget_2.setObjectName(u"emptyWidget_2")
        self.recordReviewRecordingStackedWidget.addWidget(self.emptyWidget_2)
        self.reviewRecordingWidget = QWidget()
        self.reviewRecordingWidget.setObjectName(u"reviewRecordingWidget")
        self.gridLayout_11 = QGridLayout(self.reviewRecordingWidget)
        self.gridLayout_11.setObjectName(u"gridLayout_11")
        self.reviewRecordingGroupBox = QGroupBox(self.reviewRecordingWidget)
        self.reviewRecordingGroupBox.setObjectName(u"reviewRecordingGroupBox")
        sizePolicy3.setHeightForWidth(self.reviewRecordingGroupBox.sizePolicy().hasHeightForWidth())
        self.reviewRecordingGroupBox.setSizePolicy(sizePolicy3)
        self.gridLayout_10 = QGridLayout(self.reviewRecordingGroupBox)
        self.gridLayout_10.setObjectName(u"gridLayout_10")
        self.label_5 = QLabel(self.reviewRecordingGroupBox)
        self.label_5.setObjectName(u"label_5")

        self.gridLayout_10.addWidget(self.label_5, 0, 0, 1, 1)

        self.reviewRecordingTaskLabel = QLabel(self.reviewRecordingGroupBox)
        self.reviewRecordingTaskLabel.setObjectName(u"reviewRecordingTaskLabel")

        self.gridLayout_10.addWidget(self.reviewRecordingTaskLabel, 0, 1, 1, 1)

        self.label_2 = QLabel(self.reviewRecordingGroupBox)
        self.label_2.setObjectName(u"label_2")

        self.gridLayout_10.addWidget(self.label_2, 1, 0, 1, 1)

        self.reviewRecordingLabelLineEdit = QLineEdit(self.reviewRecordingGroupBox)
        self.reviewRecordingLabelLineEdit.setObjectName(u"reviewRecordingLabelLineEdit")
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy4.setHorizontalStretch(0)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.reviewRecordingLabelLineEdit.sizePolicy().hasHeightForWidth())
        self.reviewRecordingLabelLineEdit.setSizePolicy(sizePolicy4)

        self.gridLayout_10.addWidget(self.reviewRecordingLabelLineEdit, 1, 1, 1, 1)

        self.reviewRecordingAcceptPushButton = QPushButton(self.reviewRecordingGroupBox)
        self.reviewRecordingAcceptPushButton.setObjectName(u"reviewRecordingAcceptPushButton")
        sizePolicy5 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy5.setHorizontalStretch(0)
        sizePolicy5.setVerticalStretch(0)
        sizePolicy5.setHeightForWidth(self.reviewRecordingAcceptPushButton.sizePolicy().hasHeightForWidth())
        self.reviewRecordingAcceptPushButton.setSizePolicy(sizePolicy5)
        self.reviewRecordingAcceptPushButton.setStyleSheet(u"color: rgb(0, 0, 0); background-color: rgb(170, 255, 0);")

        self.gridLayout_10.addWidget(self.reviewRecordingAcceptPushButton, 2, 0, 1, 1)

        self.reviewRecordingRejectPushButton = QPushButton(self.reviewRecordingGroupBox)
        self.reviewRecordingRejectPushButton.setObjectName(u"reviewRecordingRejectPushButton")
        sizePolicy5.setHeightForWidth(self.reviewRecordingRejectPushButton.sizePolicy().hasHeightForWidth())
        self.reviewRecordingRejectPushButton.setSizePolicy(sizePolicy5)
        self.reviewRecordingRejectPushButton.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.reviewRecordingRejectPushButton.setStyleSheet(u"background-color: rgb(255, 0, 0);\n"
"color: rgb(0, 0, 0);")

        self.gridLayout_10.addWidget(self.reviewRecordingRejectPushButton, 2, 1, 1, 1)


        self.gridLayout_11.addWidget(self.reviewRecordingGroupBox, 0, 0, 1, 1)

        self.recordReviewRecordingStackedWidget.addWidget(self.reviewRecordingWidget)

        self.gridLayout.addWidget(self.recordReviewRecordingStackedWidget, 1, 0, 1, 1)


        self.retranslateUi(DefaultRecordingInterface)

        self.recordReviewRecordingStackedWidget.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(DefaultRecordingInterface)
    # setupUi

    def retranslateUi(self, DefaultRecordingInterface):
        DefaultRecordingInterface.setWindowTitle(QCoreApplication.translate("DefaultRecordingInterface", u"Form", None))
        self.recordRecordingGroupBox.setTitle(QCoreApplication.translate("DefaultRecordingInterface", u"Record (No Visual Interface)", None))
        self.label.setText(QCoreApplication.translate("DefaultRecordingInterface", u"Task", None))
        self.recordTaskComboBox.setItemText(0, QCoreApplication.translate("DefaultRecordingInterface", u"Rest", None))
        self.recordTaskComboBox.setItemText(1, QCoreApplication.translate("DefaultRecordingInterface", u"Index", None))
        self.recordTaskComboBox.setItemText(2, QCoreApplication.translate("DefaultRecordingInterface", u"Thumb", None))
        self.recordTaskComboBox.setItemText(3, QCoreApplication.translate("DefaultRecordingInterface", u"Middle", None))
        self.recordTaskComboBox.setItemText(4, QCoreApplication.translate("DefaultRecordingInterface", u"Ring", None))
        self.recordTaskComboBox.setItemText(5, QCoreApplication.translate("DefaultRecordingInterface", u"Pinky", None))
        self.recordTaskComboBox.setItemText(6, QCoreApplication.translate("DefaultRecordingInterface", u"Power Grasp", None))
        self.recordTaskComboBox.setItemText(7, QCoreApplication.translate("DefaultRecordingInterface", u"Pinch", None))
        self.recordTaskComboBox.setItemText(8, QCoreApplication.translate("DefaultRecordingInterface", u"Tripod Pinch", None))
        self.recordTaskComboBox.setItemText(9, QCoreApplication.translate("DefaultRecordingInterface", u"Pointing", None))

        self.label_7.setText(QCoreApplication.translate("DefaultRecordingInterface", u"Duration", None))
        self.recordRecordPushButton.setText(QCoreApplication.translate("DefaultRecordingInterface", u"Record", None))
        self.reviewRecordingGroupBox.setTitle(QCoreApplication.translate("DefaultRecordingInterface", u"Review Recording", None))
        self.label_5.setText(QCoreApplication.translate("DefaultRecordingInterface", u"Task", None))
        self.reviewRecordingTaskLabel.setText(QCoreApplication.translate("DefaultRecordingInterface", u"Placeholder", None))
        self.label_2.setText(QCoreApplication.translate("DefaultRecordingInterface", u"Recording Label", None))
        self.reviewRecordingAcceptPushButton.setText(QCoreApplication.translate("DefaultRecordingInterface", u"Accept", None))
        self.reviewRecordingRejectPushButton.setText(QCoreApplication.translate("DefaultRecordingInterface", u"Reject", None))
    # retranslateUi

