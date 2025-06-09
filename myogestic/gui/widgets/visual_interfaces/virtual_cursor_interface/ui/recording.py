# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'recording.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QProgressBar,
    QPushButton, QSizePolicy, QSpinBox, QStackedWidget,
    QWidget)

class Ui_RecordingVirtualCursorInterface(object):
    def setupUi(self, RecordingVirtualCursorInterface):
        if not RecordingVirtualCursorInterface.objectName():
            RecordingVirtualCursorInterface.setObjectName(u"RecordingVirtualCursorInterface")
        RecordingVirtualCursorInterface.resize(397, 442)
        self.recordRecordingGroupBox = QGroupBox(RecordingVirtualCursorInterface)
        self.recordRecordingGroupBox.setObjectName(u"recordRecordingGroupBox")
        self.recordRecordingGroupBox.setGeometry(QRect(10, 10, 382, 271))
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.recordRecordingGroupBox.sizePolicy().hasHeightForWidth())
        self.recordRecordingGroupBox.setSizePolicy(sizePolicy)
        self.gridLayout_9 = QGridLayout(self.recordRecordingGroupBox)
        self.gridLayout_9.setObjectName(u"gridLayout_9")
        self.label_7 = QLabel(self.recordRecordingGroupBox)
        self.label_7.setObjectName(u"label_7")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.label_7.sizePolicy().hasHeightForWidth())
        self.label_7.setSizePolicy(sizePolicy1)

        self.gridLayout_9.addWidget(self.label_7, 4, 0, 1, 1)

        self.label_4 = QLabel(self.recordRecordingGroupBox)
        self.label_4.setObjectName(u"label_4")

        self.gridLayout_9.addWidget(self.label_4, 2, 0, 1, 1)

        self.recordMovementComboBox = QComboBox(self.recordRecordingGroupBox)
        self.recordMovementComboBox.addItem("")
        self.recordMovementComboBox.addItem("")
        self.recordMovementComboBox.addItem("")
        self.recordMovementComboBox.addItem("")
        self.recordMovementComboBox.addItem("")
        self.recordMovementComboBox.setObjectName(u"recordMovementComboBox")

        self.gridLayout_9.addWidget(self.recordMovementComboBox, 2, 1, 1, 1)

        self.groundTruthProgressBar = QProgressBar(self.recordRecordingGroupBox)
        self.groundTruthProgressBar.setObjectName(u"groundTruthProgressBar")
        self.groundTruthProgressBar.setValue(24)

        self.gridLayout_9.addWidget(self.groundTruthProgressBar, 9, 0, 1, 2)

        self.label = QLabel(self.recordRecordingGroupBox)
        self.label.setObjectName(u"label")

        self.gridLayout_9.addWidget(self.label, 1, 0, 1, 1)

        self.recordUseCursorKinematicsCheckBox = QCheckBox(self.recordRecordingGroupBox)
        self.recordUseCursorKinematicsCheckBox.setObjectName(u"recordUseCursorKinematicsCheckBox")
        self.recordUseCursorKinematicsCheckBox.setEnabled(True)
        self.recordUseCursorKinematicsCheckBox.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.recordUseCursorKinematicsCheckBox.setChecked(False)

        self.gridLayout_9.addWidget(self.recordUseCursorKinematicsCheckBox, 7, 0, 1, 1)

        self.recordDurationSpinBox = QSpinBox(self.recordRecordingGroupBox)
        self.recordDurationSpinBox.setObjectName(u"recordDurationSpinBox")
        self.recordDurationSpinBox.setValue(10)

        self.gridLayout_9.addWidget(self.recordDurationSpinBox, 4, 1, 1, 1)

        self.recordRecordPushButton = QPushButton(self.recordRecordingGroupBox)
        self.recordRecordPushButton.setObjectName(u"recordRecordPushButton")
        self.recordRecordPushButton.setCheckable(True)

        self.gridLayout_9.addWidget(self.recordRecordPushButton, 8, 0, 1, 2)

        self.label_3 = QLabel(self.recordRecordingGroupBox)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout_9.addWidget(self.label_3, 5, 0, 1, 1)

        self.recordTaskComboBox = QComboBox(self.recordRecordingGroupBox)
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.addItem("")
        self.recordTaskComboBox.setObjectName(u"recordTaskComboBox")

        self.gridLayout_9.addWidget(self.recordTaskComboBox, 1, 1, 1, 1)

        self.kinematicsSampFreqSpinBox = QSpinBox(self.recordRecordingGroupBox)
        self.kinematicsSampFreqSpinBox.setObjectName(u"kinematicsSampFreqSpinBox")
        self.kinematicsSampFreqSpinBox.setMinimum(1)
        self.kinematicsSampFreqSpinBox.setMaximum(120)
        self.kinematicsSampFreqSpinBox.setValue(60)

        self.gridLayout_9.addWidget(self.kinematicsSampFreqSpinBox, 5, 1, 1, 1)

        self.recordReviewRecordingStackedWidget = QStackedWidget(RecordingVirtualCursorInterface)
        self.recordReviewRecordingStackedWidget.setObjectName(u"recordReviewRecordingStackedWidget")
        self.recordReviewRecordingStackedWidget.setGeometry(QRect(10, 306, 382, 131))
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.recordReviewRecordingStackedWidget.sizePolicy().hasHeightForWidth())
        self.recordReviewRecordingStackedWidget.setSizePolicy(sizePolicy2)
        self.emptyWidget_2 = QWidget()
        self.emptyWidget_2.setObjectName(u"emptyWidget_2")
        self.recordReviewRecordingStackedWidget.addWidget(self.emptyWidget_2)
        self.reviewRecordingWidget = QWidget()
        self.reviewRecordingWidget.setObjectName(u"reviewRecordingWidget")
        self.gridLayout_11 = QGridLayout(self.reviewRecordingWidget)
        self.gridLayout_11.setObjectName(u"gridLayout_11")
        self.reviewRecordingGroupBox = QGroupBox(self.reviewRecordingWidget)
        self.reviewRecordingGroupBox.setObjectName(u"reviewRecordingGroupBox")
        sizePolicy2.setHeightForWidth(self.reviewRecordingGroupBox.sizePolicy().hasHeightForWidth())
        self.reviewRecordingGroupBox.setSizePolicy(sizePolicy2)
        self.gridLayout_10 = QGridLayout(self.reviewRecordingGroupBox)
        self.gridLayout_10.setObjectName(u"gridLayout_10")
        self.reviewRecordingTaskLabel = QLabel(self.reviewRecordingGroupBox)
        self.reviewRecordingTaskLabel.setObjectName(u"reviewRecordingTaskLabel")

        self.gridLayout_10.addWidget(self.reviewRecordingTaskLabel, 0, 1, 1, 1)

        self.reviewRecordingAcceptPushButton = QPushButton(self.reviewRecordingGroupBox)
        self.reviewRecordingAcceptPushButton.setObjectName(u"reviewRecordingAcceptPushButton")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.reviewRecordingAcceptPushButton.sizePolicy().hasHeightForWidth())
        self.reviewRecordingAcceptPushButton.setSizePolicy(sizePolicy3)
        self.reviewRecordingAcceptPushButton.setStyleSheet(u"color: rgb(0, 0, 0); background-color: rgb(170, 255, 0);")

        self.gridLayout_10.addWidget(self.reviewRecordingAcceptPushButton, 3, 0, 1, 1)

        self.reviewRecordingLabelLineEdit = QLineEdit(self.reviewRecordingGroupBox)
        self.reviewRecordingLabelLineEdit.setObjectName(u"reviewRecordingLabelLineEdit")
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy4.setHorizontalStretch(0)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.reviewRecordingLabelLineEdit.sizePolicy().hasHeightForWidth())
        self.reviewRecordingLabelLineEdit.setSizePolicy(sizePolicy4)

        self.gridLayout_10.addWidget(self.reviewRecordingLabelLineEdit, 1, 1, 1, 1)

        self.label_2 = QLabel(self.reviewRecordingGroupBox)
        self.label_2.setObjectName(u"label_2")

        self.gridLayout_10.addWidget(self.label_2, 1, 0, 1, 1)

        self.label_5 = QLabel(self.reviewRecordingGroupBox)
        self.label_5.setObjectName(u"label_5")

        self.gridLayout_10.addWidget(self.label_5, 0, 0, 1, 1)

        self.reviewRecordingRejectPushButton = QPushButton(self.reviewRecordingGroupBox)
        self.reviewRecordingRejectPushButton.setObjectName(u"reviewRecordingRejectPushButton")
        sizePolicy3.setHeightForWidth(self.reviewRecordingRejectPushButton.sizePolicy().hasHeightForWidth())
        self.reviewRecordingRejectPushButton.setSizePolicy(sizePolicy3)
        self.reviewRecordingRejectPushButton.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.reviewRecordingRejectPushButton.setStyleSheet(u"background-color: rgb(255, 0, 0);\n"
"color: rgb(0, 0, 0);")

        self.gridLayout_10.addWidget(self.reviewRecordingRejectPushButton, 3, 1, 1, 1)


        self.gridLayout_11.addWidget(self.reviewRecordingGroupBox, 0, 0, 1, 1)

        self.recordReviewRecordingStackedWidget.addWidget(self.reviewRecordingWidget)

        self.retranslateUi(RecordingVirtualCursorInterface)

        self.recordReviewRecordingStackedWidget.setCurrentIndex(1)


        QMetaObject.connectSlotsByName(RecordingVirtualCursorInterface)
    # setupUi

    def retranslateUi(self, RecordingVirtualCursorInterface):
        RecordingVirtualCursorInterface.setWindowTitle(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Form", None))
        self.recordRecordingGroupBox.setTitle(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Record Cursor", None))
        self.label_7.setText(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Duration", None))
        self.label_4.setText(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Leg Movement", None))
        self.recordMovementComboBox.setItemText(0, QCoreApplication.translate("RecordingVirtualCursorInterface", u"Rest", None))
        self.recordMovementComboBox.setItemText(1, QCoreApplication.translate("RecordingVirtualCursorInterface", u"Dorsiflexion", None))
        self.recordMovementComboBox.setItemText(2, QCoreApplication.translate("RecordingVirtualCursorInterface", u"Plantarflexion", None))
        self.recordMovementComboBox.setItemText(3, QCoreApplication.translate("RecordingVirtualCursorInterface", u"Inversion", None))
        self.recordMovementComboBox.setItemText(4, QCoreApplication.translate("RecordingVirtualCursorInterface", u"Eversion", None))

        self.label.setText(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Task cursor direction", None))
        self.recordUseCursorKinematicsCheckBox.setText(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Use Kinematics of Virtual Cursor Interface", None))
        self.recordRecordPushButton.setText(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Record", None))
        self.label_3.setText(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Kinematics samp freq", None))
        self.recordTaskComboBox.setItemText(0, QCoreApplication.translate("RecordingVirtualCursorInterface", u"Rest", None))
        self.recordTaskComboBox.setItemText(1, QCoreApplication.translate("RecordingVirtualCursorInterface", u"Up", None))
        self.recordTaskComboBox.setItemText(2, QCoreApplication.translate("RecordingVirtualCursorInterface", u"Down", None))
        self.recordTaskComboBox.setItemText(3, QCoreApplication.translate("RecordingVirtualCursorInterface", u"Right", None))
        self.recordTaskComboBox.setItemText(4, QCoreApplication.translate("RecordingVirtualCursorInterface", u"Left", None))

        self.reviewRecordingGroupBox.setTitle(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Review Recording", None))
        self.reviewRecordingTaskLabel.setText(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Placeholder", None))
        self.reviewRecordingAcceptPushButton.setText(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Accept", None))
        self.label_2.setText(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Recording Label", None))
        self.label_5.setText(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Task", None))
        self.reviewRecordingRejectPushButton.setText(QCoreApplication.translate("RecordingVirtualCursorInterface", u"Reject", None))
    # retranslateUi

