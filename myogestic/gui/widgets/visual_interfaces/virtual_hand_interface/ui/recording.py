# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'recording.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QProgressBar,
    QPushButton, QSizePolicy, QSpinBox, QStackedWidget,
    QWidget)

class Ui_RecordingVirtualHandInterface(object):
    def setupUi(self, RecordingVirtualHandInterface):
        if not RecordingVirtualHandInterface.objectName():
            RecordingVirtualHandInterface.setObjectName(u"RecordingVirtualHandInterface")
        RecordingVirtualHandInterface.resize(400, 360)
        self.gridLayout = QGridLayout(RecordingVirtualHandInterface)
        self.gridLayout.setObjectName(u"gridLayout")
        self.recordRecordingGroupBox = QGroupBox(RecordingVirtualHandInterface)
        self.recordRecordingGroupBox.setObjectName(u"recordRecordingGroupBox")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.recordRecordingGroupBox.sizePolicy().hasHeightForWidth())
        self.recordRecordingGroupBox.setSizePolicy(sizePolicy)
        self.gridLayout_9 = QGridLayout(self.recordRecordingGroupBox)
        self.gridLayout_9.setObjectName(u"gridLayout_9")
        self.label_7 = QLabel(self.recordRecordingGroupBox)
        self.label_7.setObjectName(u"label_7")

        self.gridLayout_9.addWidget(self.label_7, 1, 0, 1, 1)

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
        self.recordTaskComboBox.setObjectName(u"recordTaskComboBox")

        self.gridLayout_9.addWidget(self.recordTaskComboBox, 0, 1, 1, 1)

        self.recordUseKinematicsCheckBox = QCheckBox(self.recordRecordingGroupBox)
        self.recordUseKinematicsCheckBox.setObjectName(u"recordUseKinematicsCheckBox")
        self.recordUseKinematicsCheckBox.setEnabled(True)
        self.recordUseKinematicsCheckBox.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.recordUseKinematicsCheckBox.setChecked(False)

        self.gridLayout_9.addWidget(self.recordUseKinematicsCheckBox, 2, 0, 1, 1)

        self.recordDurationSpinBox = QSpinBox(self.recordRecordingGroupBox)
        self.recordDurationSpinBox.setObjectName(u"recordDurationSpinBox")
        self.recordDurationSpinBox.setValue(10)

        self.gridLayout_9.addWidget(self.recordDurationSpinBox, 1, 1, 1, 1)

        self.groundTruthProgressBar = QProgressBar(self.recordRecordingGroupBox)
        self.groundTruthProgressBar.setObjectName(u"groundTruthProgressBar")
        self.groundTruthProgressBar.setValue(24)

        self.gridLayout_9.addWidget(self.groundTruthProgressBar, 4, 0, 1, 2)

        self.label = QLabel(self.recordRecordingGroupBox)
        self.label.setObjectName(u"label")

        self.gridLayout_9.addWidget(self.label, 0, 0, 1, 1)

        self.recordRecordPushButton = QPushButton(self.recordRecordingGroupBox)
        self.recordRecordPushButton.setObjectName(u"recordRecordPushButton")
        self.recordRecordPushButton.setCheckable(True)

        self.gridLayout_9.addWidget(self.recordRecordPushButton, 3, 0, 1, 2)


        self.gridLayout.addWidget(self.recordRecordingGroupBox, 0, 0, 1, 1)

        self.recordReviewRecordingStackedWidget = QStackedWidget(RecordingVirtualHandInterface)
        self.recordReviewRecordingStackedWidget.setObjectName(u"recordReviewRecordingStackedWidget")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.recordReviewRecordingStackedWidget.sizePolicy().hasHeightForWidth())
        self.recordReviewRecordingStackedWidget.setSizePolicy(sizePolicy1)
        self.emptyWidget_2 = QWidget()
        self.emptyWidget_2.setObjectName(u"emptyWidget_2")
        self.recordReviewRecordingStackedWidget.addWidget(self.emptyWidget_2)
        self.reviewRecordingWidget = QWidget()
        self.reviewRecordingWidget.setObjectName(u"reviewRecordingWidget")
        self.gridLayout_11 = QGridLayout(self.reviewRecordingWidget)
        self.gridLayout_11.setObjectName(u"gridLayout_11")
        self.reviewRecordingGroupBox = QGroupBox(self.reviewRecordingWidget)
        self.reviewRecordingGroupBox.setObjectName(u"reviewRecordingGroupBox")
        sizePolicy1.setHeightForWidth(self.reviewRecordingGroupBox.sizePolicy().hasHeightForWidth())
        self.reviewRecordingGroupBox.setSizePolicy(sizePolicy1)
        self.gridLayout_10 = QGridLayout(self.reviewRecordingGroupBox)
        self.gridLayout_10.setObjectName(u"gridLayout_10")
        self.reviewRecordingTaskLabel = QLabel(self.reviewRecordingGroupBox)
        self.reviewRecordingTaskLabel.setObjectName(u"reviewRecordingTaskLabel")

        self.gridLayout_10.addWidget(self.reviewRecordingTaskLabel, 0, 1, 1, 1)

        self.reviewRecordingAcceptPushButton = QPushButton(self.reviewRecordingGroupBox)
        self.reviewRecordingAcceptPushButton.setObjectName(u"reviewRecordingAcceptPushButton")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.reviewRecordingAcceptPushButton.sizePolicy().hasHeightForWidth())
        self.reviewRecordingAcceptPushButton.setSizePolicy(sizePolicy2)
        self.reviewRecordingAcceptPushButton.setStyleSheet(u"color: rgb(0, 0, 0); background-color: rgb(170, 255, 0);")

        self.gridLayout_10.addWidget(self.reviewRecordingAcceptPushButton, 3, 0, 1, 1)

        self.reviewRecordingLabelLineEdit = QLineEdit(self.reviewRecordingGroupBox)
        self.reviewRecordingLabelLineEdit.setObjectName(u"reviewRecordingLabelLineEdit")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.reviewRecordingLabelLineEdit.sizePolicy().hasHeightForWidth())
        self.reviewRecordingLabelLineEdit.setSizePolicy(sizePolicy3)

        self.gridLayout_10.addWidget(self.reviewRecordingLabelLineEdit, 1, 1, 1, 1)

        self.label_2 = QLabel(self.reviewRecordingGroupBox)
        self.label_2.setObjectName(u"label_2")

        self.gridLayout_10.addWidget(self.label_2, 1, 0, 1, 1)

        self.label_5 = QLabel(self.reviewRecordingGroupBox)
        self.label_5.setObjectName(u"label_5")

        self.gridLayout_10.addWidget(self.label_5, 0, 0, 1, 1)

        self.reviewRecordingRejectPushButton = QPushButton(self.reviewRecordingGroupBox)
        self.reviewRecordingRejectPushButton.setObjectName(u"reviewRecordingRejectPushButton")
        sizePolicy2.setHeightForWidth(self.reviewRecordingRejectPushButton.sizePolicy().hasHeightForWidth())
        self.reviewRecordingRejectPushButton.setSizePolicy(sizePolicy2)
        self.reviewRecordingRejectPushButton.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.reviewRecordingRejectPushButton.setStyleSheet(u"background-color: rgb(255, 0, 0);\n"
"color: rgb(0, 0, 0);")

        self.gridLayout_10.addWidget(self.reviewRecordingRejectPushButton, 3, 1, 1, 1)


        self.gridLayout_11.addWidget(self.reviewRecordingGroupBox, 0, 0, 1, 1)

        self.recordReviewRecordingStackedWidget.addWidget(self.reviewRecordingWidget)

        self.gridLayout.addWidget(self.recordReviewRecordingStackedWidget, 1, 0, 1, 1)


        self.retranslateUi(RecordingVirtualHandInterface)

        self.recordReviewRecordingStackedWidget.setCurrentIndex(1)


        QMetaObject.connectSlotsByName(RecordingVirtualHandInterface)
    # setupUi

    def retranslateUi(self, RecordingVirtualHandInterface):
        RecordingVirtualHandInterface.setWindowTitle(QCoreApplication.translate("RecordingVirtualHandInterface", u"Form", None))
        self.recordRecordingGroupBox.setTitle(QCoreApplication.translate("RecordingVirtualHandInterface", u"Record", None))
        self.label_7.setText(QCoreApplication.translate("RecordingVirtualHandInterface", u"Duration", None))
        self.recordTaskComboBox.setItemText(0, QCoreApplication.translate("RecordingVirtualHandInterface", u"Rest", None))
        self.recordTaskComboBox.setItemText(1, QCoreApplication.translate("RecordingVirtualHandInterface", u"Fist", None))
        self.recordTaskComboBox.setItemText(2, QCoreApplication.translate("RecordingVirtualHandInterface", u"Pinch", None))
        self.recordTaskComboBox.setItemText(3, QCoreApplication.translate("RecordingVirtualHandInterface", u"3FPinch", None))
        self.recordTaskComboBox.setItemText(4, QCoreApplication.translate("RecordingVirtualHandInterface", u"Thumb", None))
        self.recordTaskComboBox.setItemText(5, QCoreApplication.translate("RecordingVirtualHandInterface", u"Index", None))
        self.recordTaskComboBox.setItemText(6, QCoreApplication.translate("RecordingVirtualHandInterface", u"Middle", None))
        self.recordTaskComboBox.setItemText(7, QCoreApplication.translate("RecordingVirtualHandInterface", u"Ring", None))
        self.recordTaskComboBox.setItemText(8, QCoreApplication.translate("RecordingVirtualHandInterface", u"Pinky", None))

        self.recordUseKinematicsCheckBox.setText(QCoreApplication.translate("RecordingVirtualHandInterface", u"Use Kinematics of Virtual Hand Interface", None))
        self.label.setText(QCoreApplication.translate("RecordingVirtualHandInterface", u"Task", None))
        self.recordRecordPushButton.setText(QCoreApplication.translate("RecordingVirtualHandInterface", u"Record", None))
        self.reviewRecordingGroupBox.setTitle(QCoreApplication.translate("RecordingVirtualHandInterface", u"Review Recording", None))
        self.reviewRecordingTaskLabel.setText(QCoreApplication.translate("RecordingVirtualHandInterface", u"Placeholder", None))
        self.reviewRecordingAcceptPushButton.setText(QCoreApplication.translate("RecordingVirtualHandInterface", u"Accept", None))
        self.label_2.setText(QCoreApplication.translate("RecordingVirtualHandInterface", u"Recording Label", None))
        self.label_5.setText(QCoreApplication.translate("RecordingVirtualHandInterface", u"Task", None))
        self.reviewRecordingRejectPushButton.setText(QCoreApplication.translate("RecordingVirtualHandInterface", u"Reject", None))
    # retranslateUi

