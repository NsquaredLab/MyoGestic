# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'virtual_cursor_window.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QSpacerItem, QSpinBox,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget)

class Ui_CursorInterface(object):
    def setupUi(self, CursorInterface):
        if not CursorInterface.objectName():
            CursorInterface.setObjectName(u"CursorInterface")
        CursorInterface.resize(1528, 844)
        self.tabWidget = QTabWidget(CursorInterface)
        self.tabWidget.setObjectName(u"tabWidget")
        self.tabWidget.setGeometry(QRect(20, 10, 381, 602))
        self.taskMappingTab = QWidget()
        self.taskMappingTab.setObjectName(u"taskMappingTab")
        self.groupBox = QGroupBox(self.taskMappingTab)
        self.groupBox.setObjectName(u"groupBox")
        self.groupBox.setGeometry(QRect(19, 10, 331, 171))
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.groupBox.sizePolicy().hasHeightForWidth())
        self.groupBox.setSizePolicy(sizePolicy)
        self.gridLayout = QGridLayout(self.groupBox)
        self.gridLayout.setObjectName(u"gridLayout")
        self.label_2 = QLabel(self.groupBox)
        self.label_2.setObjectName(u"label_2")

        self.gridLayout.addWidget(self.label_2, 1, 0, 1, 1)

        self.label_4 = QLabel(self.groupBox)
        self.label_4.setObjectName(u"label_4")

        self.gridLayout.addWidget(self.label_4, 3, 0, 1, 1)

        self.downMovementComboBox = QComboBox(self.groupBox)
        self.downMovementComboBox.addItem("")
        self.downMovementComboBox.addItem("")
        self.downMovementComboBox.addItem("")
        self.downMovementComboBox.addItem("")
        self.downMovementComboBox.addItem("")
        self.downMovementComboBox.setObjectName(u"downMovementComboBox")

        self.gridLayout.addWidget(self.downMovementComboBox, 1, 1, 1, 1)

        self.label_3 = QLabel(self.groupBox)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout.addWidget(self.label_3, 2, 0, 1, 1)

        self.upMovementComboBox = QComboBox(self.groupBox)
        self.upMovementComboBox.addItem("")
        self.upMovementComboBox.addItem("")
        self.upMovementComboBox.addItem("")
        self.upMovementComboBox.addItem("")
        self.upMovementComboBox.addItem("")
        self.upMovementComboBox.setObjectName(u"upMovementComboBox")

        self.gridLayout.addWidget(self.upMovementComboBox, 0, 1, 1, 1)

        self.rightMovementComboBox = QComboBox(self.groupBox)
        self.rightMovementComboBox.addItem("")
        self.rightMovementComboBox.addItem("")
        self.rightMovementComboBox.addItem("")
        self.rightMovementComboBox.addItem("")
        self.rightMovementComboBox.addItem("")
        self.rightMovementComboBox.setObjectName(u"rightMovementComboBox")

        self.gridLayout.addWidget(self.rightMovementComboBox, 2, 1, 1, 1)

        self.label = QLabel(self.groupBox)
        self.label.setObjectName(u"label")

        self.gridLayout.addWidget(self.label, 0, 0, 1, 1)

        self.leftMovementComboBox = QComboBox(self.groupBox)
        self.leftMovementComboBox.addItem("")
        self.leftMovementComboBox.addItem("")
        self.leftMovementComboBox.addItem("")
        self.leftMovementComboBox.addItem("")
        self.leftMovementComboBox.addItem("")
        self.leftMovementComboBox.setObjectName(u"leftMovementComboBox")
        self.leftMovementComboBox.setEnabled(True)
        self.leftMovementComboBox.setEditable(False)

        self.gridLayout.addWidget(self.leftMovementComboBox, 3, 1, 1, 1)

        self.updateMovementTaskMapPushButton = QPushButton(self.groupBox)
        self.updateMovementTaskMapPushButton.setObjectName(u"updateMovementTaskMapPushButton")

        self.gridLayout.addWidget(self.updateMovementTaskMapPushButton, 4, 0, 1, 2)

        self.tabWidget.addTab(self.taskMappingTab, "")
        self.cursorSettingsTab = QWidget()
        self.cursorSettingsTab.setObjectName(u"cursorSettingsTab")
        self.gridLayout_8 = QGridLayout(self.cursorSettingsTab)
        self.gridLayout_8.setObjectName(u"gridLayout_8")
        self.groupBox_2 = QGroupBox(self.cursorSettingsTab)
        self.groupBox_2.setObjectName(u"groupBox_2")
        self.gridLayout_2 = QGridLayout(self.groupBox_2)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.groupBox_5 = QGroupBox(self.groupBox_2)
        self.groupBox_5.setObjectName(u"groupBox_5")
        self.gridLayout_5 = QGridLayout(self.groupBox_5)
        self.gridLayout_5.setObjectName(u"gridLayout_5")
        self.label_11 = QLabel(self.groupBox_5)
        self.label_11.setObjectName(u"label_11")

        self.gridLayout_5.addWidget(self.label_11, 2, 0, 1, 1)

        self.middleDurationDoubleSpinBox = QDoubleSpinBox(self.groupBox_5)
        self.middleDurationDoubleSpinBox.setObjectName(u"middleDurationDoubleSpinBox")
        self.middleDurationDoubleSpinBox.setDecimals(1)
        self.middleDurationDoubleSpinBox.setSingleStep(0.100000000000000)

        self.gridLayout_5.addWidget(self.middleDurationDoubleSpinBox, 2, 1, 1, 1)

        self.label_15 = QLabel(self.groupBox_5)
        self.label_15.setObjectName(u"label_15")

        self.gridLayout_5.addWidget(self.label_15, 1, 0, 1, 1)

        self.middleUpperActivationLevelSpinBox = QSpinBox(self.groupBox_5)
        self.middleUpperActivationLevelSpinBox.setObjectName(u"middleUpperActivationLevelSpinBox")
        self.middleUpperActivationLevelSpinBox.setMaximum(100)
        self.middleUpperActivationLevelSpinBox.setValue(50)

        self.gridLayout_5.addWidget(self.middleUpperActivationLevelSpinBox, 1, 1, 1, 1)

        self.cursorStopConditionComboBox = QComboBox(self.groupBox_5)
        self.cursorStopConditionComboBox.addItem("")
        self.cursorStopConditionComboBox.addItem("")
        self.cursorStopConditionComboBox.addItem("")
        self.cursorStopConditionComboBox.setObjectName(u"cursorStopConditionComboBox")

        self.gridLayout_5.addWidget(self.cursorStopConditionComboBox, 0, 1, 1, 1)

        self.label_6 = QLabel(self.groupBox_5)
        self.label_6.setObjectName(u"label_6")

        self.gridLayout_5.addWidget(self.label_6, 0, 0, 1, 1)


        self.gridLayout_2.addWidget(self.groupBox_5, 5, 0, 1, 2)

        self.groupBox_3 = QGroupBox(self.groupBox_2)
        self.groupBox_3.setObjectName(u"groupBox_3")
        self.gridLayout_3 = QGridLayout(self.groupBox_3)
        self.gridLayout_3.setObjectName(u"gridLayout_3")
        self.restDurationDoubleSpinBox = QDoubleSpinBox(self.groupBox_3)
        self.restDurationDoubleSpinBox.setObjectName(u"restDurationDoubleSpinBox")
        self.restDurationDoubleSpinBox.setDecimals(1)
        self.restDurationDoubleSpinBox.setMaximum(100.000000000000000)
        self.restDurationDoubleSpinBox.setSingleStep(0.100000000000000)
        self.restDurationDoubleSpinBox.setValue(0.500000000000000)

        self.gridLayout_3.addWidget(self.restDurationDoubleSpinBox, 0, 1, 1, 1)

        self.label_7 = QLabel(self.groupBox_3)
        self.label_7.setObjectName(u"label_7")

        self.gridLayout_3.addWidget(self.label_7, 0, 0, 1, 1)


        self.gridLayout_2.addWidget(self.groupBox_3, 3, 0, 1, 2)

        self.label_12 = QLabel(self.groupBox_2)
        self.label_12.setObjectName(u"label_12")

        self.gridLayout_2.addWidget(self.label_12, 1, 0, 1, 1)

        self.groupBox_4 = QGroupBox(self.groupBox_2)
        self.groupBox_4.setObjectName(u"groupBox_4")
        self.gridLayout_4 = QGridLayout(self.groupBox_4)
        self.gridLayout_4.setObjectName(u"gridLayout_4")
        self.holdDurationDoubleSpinBox = QDoubleSpinBox(self.groupBox_4)
        self.holdDurationDoubleSpinBox.setObjectName(u"holdDurationDoubleSpinBox")
        self.holdDurationDoubleSpinBox.setDecimals(1)
        self.holdDurationDoubleSpinBox.setSingleStep(0.100000000000000)
        self.holdDurationDoubleSpinBox.setValue(0.500000000000000)

        self.gridLayout_4.addWidget(self.holdDurationDoubleSpinBox, 0, 1, 1, 1)

        self.label_9 = QLabel(self.groupBox_4)
        self.label_9.setObjectName(u"label_9")

        self.gridLayout_4.addWidget(self.label_9, 0, 0, 1, 1)


        self.gridLayout_2.addWidget(self.groupBox_4, 4, 0, 1, 2)

        self.cursorFrequencyDoubleSpinBox = QDoubleSpinBox(self.groupBox_2)
        self.cursorFrequencyDoubleSpinBox.setObjectName(u"cursorFrequencyDoubleSpinBox")
        self.cursorFrequencyDoubleSpinBox.setDecimals(1)
        self.cursorFrequencyDoubleSpinBox.setMinimum(0.100000000000000)
        self.cursorFrequencyDoubleSpinBox.setMaximum(10.000000000000000)
        self.cursorFrequencyDoubleSpinBox.setSingleStep(0.100000000000000)

        self.gridLayout_2.addWidget(self.cursorFrequencyDoubleSpinBox, 0, 1, 1, 1)

        self.label_5 = QLabel(self.groupBox_2)
        self.label_5.setObjectName(u"label_5")

        self.gridLayout_2.addWidget(self.label_5, 0, 0, 1, 1)

        self.referenceCursorRefreshRateComboBox = QComboBox(self.groupBox_2)
        self.referenceCursorRefreshRateComboBox.addItem("")
        self.referenceCursorRefreshRateComboBox.addItem("")
        self.referenceCursorRefreshRateComboBox.addItem("")
        self.referenceCursorRefreshRateComboBox.addItem("")
        self.referenceCursorRefreshRateComboBox.setObjectName(u"referenceCursorRefreshRateComboBox")

        self.gridLayout_2.addWidget(self.referenceCursorRefreshRateComboBox, 1, 1, 1, 1)


        self.gridLayout_8.addWidget(self.groupBox_2, 0, 0, 1, 1)

        self.targetBoxGroupBox = QGroupBox(self.cursorSettingsTab)
        self.targetBoxGroupBox.setObjectName(u"targetBoxGroupBox")
        self.targetBoxGroupBox.setEnabled(True)
        self.targetBoxGroupBox.setCheckable(True)
        self.targetBoxGroupBox.setChecked(False)
        self.gridLayout_7 = QGridLayout(self.targetBoxGroupBox)
        self.gridLayout_7.setObjectName(u"gridLayout_7")
        self.label_10 = QLabel(self.targetBoxGroupBox)
        self.label_10.setObjectName(u"label_10")

        self.gridLayout_7.addWidget(self.label_10, 0, 0, 1, 1)

        self.upperTargetRangeLevelSpinBox = QSpinBox(self.targetBoxGroupBox)
        self.upperTargetRangeLevelSpinBox.setObjectName(u"upperTargetRangeLevelSpinBox")
        self.upperTargetRangeLevelSpinBox.setMaximum(100)
        self.upperTargetRangeLevelSpinBox.setValue(20)

        self.gridLayout_7.addWidget(self.upperTargetRangeLevelSpinBox, 1, 1, 1, 1)

        self.label_17 = QLabel(self.targetBoxGroupBox)
        self.label_17.setObjectName(u"label_17")

        self.gridLayout_7.addWidget(self.label_17, 0, 1, 1, 1)

        self.lowerTargetRangeLevelSpinBox = QSpinBox(self.targetBoxGroupBox)
        self.lowerTargetRangeLevelSpinBox.setObjectName(u"lowerTargetRangeLevelSpinBox")
        self.lowerTargetRangeLevelSpinBox.setMaximum(100)
        self.lowerTargetRangeLevelSpinBox.setValue(20)

        self.gridLayout_7.addWidget(self.lowerTargetRangeLevelSpinBox, 1, 0, 1, 1)


        self.gridLayout_8.addWidget(self.targetBoxGroupBox, 1, 0, 1, 1)

        self.groupBox_6 = QGroupBox(self.cursorSettingsTab)
        self.groupBox_6.setObjectName(u"groupBox_6")
        self.gridLayout_6 = QGridLayout(self.groupBox_6)
        self.gridLayout_6.setObjectName(u"gridLayout_6")
        self.predictedCursorFreqDivFactorSpinBox = QSpinBox(self.groupBox_6)
        self.predictedCursorFreqDivFactorSpinBox.setObjectName(u"predictedCursorFreqDivFactorSpinBox")
        self.predictedCursorFreqDivFactorSpinBox.setMinimum(1)
        self.predictedCursorFreqDivFactorSpinBox.setMaximum(10)
        self.predictedCursorFreqDivFactorSpinBox.setValue(1)

        self.gridLayout_6.addWidget(self.predictedCursorFreqDivFactorSpinBox, 1, 1, 1, 1)

        self.label_13 = QLabel(self.groupBox_6)
        self.label_13.setObjectName(u"label_13")

        self.gridLayout_6.addWidget(self.label_13, 0, 0, 1, 1)

        self.smootheningFactorSpinBox = QSpinBox(self.groupBox_6)
        self.smootheningFactorSpinBox.setObjectName(u"smootheningFactorSpinBox")
        self.smootheningFactorSpinBox.setMinimum(1)
        self.smootheningFactorSpinBox.setMaximum(500)
        self.smootheningFactorSpinBox.setValue(25)

        self.gridLayout_6.addWidget(self.smootheningFactorSpinBox, 0, 1, 1, 1)

        self.label_14 = QLabel(self.groupBox_6)
        self.label_14.setObjectName(u"label_14")

        self.gridLayout_6.addWidget(self.label_14, 1, 0, 1, 1)


        self.gridLayout_8.addWidget(self.groupBox_6, 2, 0, 1, 1)

        self.streamingPushButton = QPushButton(self.cursorSettingsTab)
        self.streamingPushButton.setObjectName(u"streamingPushButton")
        self.streamingPushButton.setCheckable(True)
        self.streamingPushButton.setChecked(False)

        self.gridLayout_8.addWidget(self.streamingPushButton, 3, 0, 1, 1)

        self.tabWidget.addTab(self.cursorSettingsTab, "")
        self.tab = QWidget()
        self.tab.setObjectName(u"tab")
        self.gridLayout_13 = QGridLayout(self.tab)
        self.gridLayout_13.setObjectName(u"gridLayout_13")
        self.stimStreamGroupBox = QGroupBox(self.tab)
        self.stimStreamGroupBox.setObjectName(u"stimStreamGroupBox")
        self.gridLayout_12 = QGridLayout(self.stimStreamGroupBox)
        self.gridLayout_12.setObjectName(u"gridLayout_12")
        self.externalDeviceConnectPushButton = QPushButton(self.stimStreamGroupBox)
        self.externalDeviceConnectPushButton.setObjectName(u"externalDeviceConnectPushButton")
        self.externalDeviceConnectPushButton.setEnabled(True)
        self.externalDeviceConnectPushButton.setCheckable(True)

        self.gridLayout_12.addWidget(self.externalDeviceConnectPushButton, 4, 0, 1, 3)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.gridLayout_12.addItem(self.horizontalSpacer, 0, 1, 1, 1)

        self.externalDeviceStreamPushButton = QPushButton(self.stimStreamGroupBox)
        self.externalDeviceStreamPushButton.setObjectName(u"externalDeviceStreamPushButton")
        self.externalDeviceStreamPushButton.setCheckable(True)

        self.gridLayout_12.addWidget(self.externalDeviceStreamPushButton, 6, 0, 1, 3)

        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.gridLayout_12.addItem(self.horizontalSpacer_2, 1, 1, 1, 1)

        self.externalDeviceIPLineEdit = QLineEdit(self.stimStreamGroupBox)
        self.externalDeviceIPLineEdit.setObjectName(u"externalDeviceIPLineEdit")

        self.gridLayout_12.addWidget(self.externalDeviceIPLineEdit, 0, 2, 1, 1)

        self.label_25 = QLabel(self.stimStreamGroupBox)
        self.label_25.setObjectName(u"label_25")

        self.gridLayout_12.addWidget(self.label_25, 0, 0, 1, 1)

        self.label_26 = QLabel(self.stimStreamGroupBox)
        self.label_26.setObjectName(u"label_26")

        self.gridLayout_12.addWidget(self.label_26, 1, 0, 1, 1)

        self.externalDevicePortLineEdit = QLineEdit(self.stimStreamGroupBox)
        self.externalDevicePortLineEdit.setObjectName(u"externalDevicePortLineEdit")

        self.gridLayout_12.addWidget(self.externalDevicePortLineEdit, 1, 2, 1, 1)

        self.externalDeviceConfigurePushButton = QPushButton(self.stimStreamGroupBox)
        self.externalDeviceConfigurePushButton.setObjectName(u"externalDeviceConfigurePushButton")
        self.externalDeviceConfigurePushButton.setCheckable(True)
        self.externalDeviceConfigurePushButton.setChecked(False)

        self.gridLayout_12.addWidget(self.externalDeviceConfigurePushButton, 3, 0, 1, 3)


        self.gridLayout_13.addWidget(self.stimStreamGroupBox, 2, 0, 1, 1)

        self.stimPulseParamsGroupBox = QGroupBox(self.tab)
        self.stimPulseParamsGroupBox.setObjectName(u"stimPulseParamsGroupBox")
        self.gridLayout_14 = QGridLayout(self.stimPulseParamsGroupBox)
        self.gridLayout_14.setObjectName(u"gridLayout_14")
        self.label_27 = QLabel(self.stimPulseParamsGroupBox)
        self.label_27.setObjectName(u"label_27")

        self.gridLayout_14.addWidget(self.label_27, 0, 0, 1, 1)

        self.stimFrequencySpinBox = QSpinBox(self.stimPulseParamsGroupBox)
        self.stimFrequencySpinBox.setObjectName(u"stimFrequencySpinBox")
        self.stimFrequencySpinBox.setMinimum(1)
        self.stimFrequencySpinBox.setValue(35)

        self.gridLayout_14.addWidget(self.stimFrequencySpinBox, 0, 1, 1, 1)


        self.gridLayout_13.addWidget(self.stimPulseParamsGroupBox, 1, 0, 1, 1)

        self.stimUserParamsGroupBox = QGroupBox(self.tab)
        self.stimUserParamsGroupBox.setObjectName(u"stimUserParamsGroupBox")
        self.stimUserParamsGroupBox.setCheckable(True)
        self.stimUserParamsGroupBox.setChecked(False)
        self.gridLayout_10 = QGridLayout(self.stimUserParamsGroupBox)
        self.gridLayout_10.setObjectName(u"gridLayout_10")
        self.label_16 = QLabel(self.stimUserParamsGroupBox)
        self.label_16.setObjectName(u"label_16")

        self.gridLayout_10.addWidget(self.label_16, 0, 0, 1, 1)

        self.cursorDownStimThresholdSpinBox = QSpinBox(self.stimUserParamsGroupBox)
        self.cursorDownStimThresholdSpinBox.setObjectName(u"cursorDownStimThresholdSpinBox")
        self.cursorDownStimThresholdSpinBox.setMinimum(1)
        self.cursorDownStimThresholdSpinBox.setValue(99)

        self.gridLayout_10.addWidget(self.cursorDownStimThresholdSpinBox, 1, 1, 1, 1)

        self.label_24 = QLabel(self.stimUserParamsGroupBox)
        self.label_24.setObjectName(u"label_24")

        self.gridLayout_10.addWidget(self.label_24, 5, 0, 1, 1)

        self.label_19 = QLabel(self.stimUserParamsGroupBox)
        self.label_19.setObjectName(u"label_19")

        self.gridLayout_10.addWidget(self.label_19, 1, 0, 1, 1)

        self.cursorLeftStimThresholdSpinBox = QSpinBox(self.stimUserParamsGroupBox)
        self.cursorLeftStimThresholdSpinBox.setObjectName(u"cursorLeftStimThresholdSpinBox")
        self.cursorLeftStimThresholdSpinBox.setMinimum(1)
        self.cursorLeftStimThresholdSpinBox.setValue(99)

        self.gridLayout_10.addWidget(self.cursorLeftStimThresholdSpinBox, 3, 1, 1, 1)

        self.stimOnTimeSpinBox = QSpinBox(self.stimUserParamsGroupBox)
        self.stimOnTimeSpinBox.setObjectName(u"stimOnTimeSpinBox")
        self.stimOnTimeSpinBox.setMaximum(10000)
        self.stimOnTimeSpinBox.setSingleStep(10)

        self.gridLayout_10.addWidget(self.stimOnTimeSpinBox, 5, 1, 1, 1)

        self.label_28 = QLabel(self.stimUserParamsGroupBox)
        self.label_28.setObjectName(u"label_28")

        self.gridLayout_10.addWidget(self.label_28, 9, 0, 1, 1)

        self.label_21 = QLabel(self.stimUserParamsGroupBox)
        self.label_21.setObjectName(u"label_21")

        self.gridLayout_10.addWidget(self.label_21, 3, 0, 1, 1)

        self.label_20 = QLabel(self.stimUserParamsGroupBox)
        self.label_20.setObjectName(u"label_20")

        self.gridLayout_10.addWidget(self.label_20, 2, 0, 1, 1)

        self.stimOffTimeSpinBox = QSpinBox(self.stimUserParamsGroupBox)
        self.stimOffTimeSpinBox.setObjectName(u"stimOffTimeSpinBox")
        self.stimOffTimeSpinBox.setMaximum(10000)
        self.stimOffTimeSpinBox.setSingleStep(10)

        self.gridLayout_10.addWidget(self.stimOffTimeSpinBox, 9, 1, 1, 1)

        self.cursorRightStimThresholdSpinBox = QSpinBox(self.stimUserParamsGroupBox)
        self.cursorRightStimThresholdSpinBox.setObjectName(u"cursorRightStimThresholdSpinBox")
        self.cursorRightStimThresholdSpinBox.setMinimum(1)
        self.cursorRightStimThresholdSpinBox.setValue(99)

        self.gridLayout_10.addWidget(self.cursorRightStimThresholdSpinBox, 2, 1, 1, 1)

        self.cursorUpStimThresholdSpinBox = QSpinBox(self.stimUserParamsGroupBox)
        self.cursorUpStimThresholdSpinBox.setObjectName(u"cursorUpStimThresholdSpinBox")
        self.cursorUpStimThresholdSpinBox.setMinimum(1)
        self.cursorUpStimThresholdSpinBox.setValue(99)

        self.gridLayout_10.addWidget(self.cursorUpStimThresholdSpinBox, 0, 1, 1, 1)

        self.verticalSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)

        self.gridLayout_10.addItem(self.verticalSpacer, 4, 1, 1, 1)


        self.gridLayout_13.addWidget(self.stimUserParamsGroupBox, 0, 0, 1, 1)

        self.verticalLayout = QVBoxLayout()
        self.verticalLayout.setObjectName(u"verticalLayout")

        self.gridLayout_13.addLayout(self.verticalLayout, 3, 0, 1, 1)

        self.tabWidget.addTab(self.tab, "")
        self.CursorDisplayWidget = QWidget(CursorInterface)
        self.CursorDisplayWidget.setObjectName(u"CursorDisplayWidget")
        self.CursorDisplayWidget.setGeometry(QRect(409, 19, 1101, 791))
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.CursorDisplayWidget.sizePolicy().hasHeightForWidth())
        self.CursorDisplayWidget.setSizePolicy(sizePolicy1)
        self.groupBox_7 = QGroupBox(CursorInterface)
        self.groupBox_7.setObjectName(u"groupBox_7")
        self.groupBox_7.setGeometry(QRect(19, 620, 371, 201))
        self.gridLayout_9 = QGridLayout(self.groupBox_7)
        self.gridLayout_9.setObjectName(u"gridLayout_9")
        self.label_8 = QLabel(self.groupBox_7)
        self.label_8.setObjectName(u"label_8")

        self.gridLayout_9.addWidget(self.label_8, 0, 0, 1, 1)

        self.loggingScrollArea = QScrollArea(self.groupBox_7)
        self.loggingScrollArea.setObjectName(u"loggingScrollArea")
        self.loggingScrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents = QWidget()
        self.scrollAreaWidgetContents.setObjectName(u"scrollAreaWidgetContents")
        self.scrollAreaWidgetContents.setGeometry(QRect(0, 0, 349, 119))
        self.loggingTextEdit = QTextEdit(self.scrollAreaWidgetContents)
        self.loggingTextEdit.setObjectName(u"loggingTextEdit")
        self.loggingTextEdit.setGeometry(QRect(13, 13, 321, 91))
        self.loggingScrollArea.setWidget(self.scrollAreaWidgetContents)

        self.gridLayout_9.addWidget(self.loggingScrollArea, 2, 0, 1, 2)

        self.refCursorUpdateFPSLabel = QLabel(self.groupBox_7)
        self.refCursorUpdateFPSLabel.setObjectName(u"refCursorUpdateFPSLabel")

        self.gridLayout_9.addWidget(self.refCursorUpdateFPSLabel, 0, 1, 1, 1)

        self.label_18 = QLabel(self.groupBox_7)
        self.label_18.setObjectName(u"label_18")

        self.gridLayout_9.addWidget(self.label_18, 1, 0, 1, 1)

        self.predCursorUpdateFPSLabel = QLabel(self.groupBox_7)
        self.predCursorUpdateFPSLabel.setObjectName(u"predCursorUpdateFPSLabel")

        self.gridLayout_9.addWidget(self.predCursorUpdateFPSLabel, 1, 1, 1, 1)


        self.retranslateUi(CursorInterface)

        self.tabWidget.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(CursorInterface)
    # setupUi

    def retranslateUi(self, CursorInterface):
        CursorInterface.setWindowTitle(QCoreApplication.translate("CursorInterface", u"MyoGestic Virtual Cursor", None))
        self.groupBox.setTitle(QCoreApplication.translate("CursorInterface", u"Movement directions", None))
        self.label_2.setText(QCoreApplication.translate("CursorInterface", u"DOWN movment", None))
        self.label_4.setText(QCoreApplication.translate("CursorInterface", u"LEFT movement", None))
        self.downMovementComboBox.setItemText(0, QCoreApplication.translate("CursorInterface", u"Rest", None))
        self.downMovementComboBox.setItemText(1, QCoreApplication.translate("CursorInterface", u"Dorsiflexion", None))
        self.downMovementComboBox.setItemText(2, QCoreApplication.translate("CursorInterface", u"Plantarflexion", None))
        self.downMovementComboBox.setItemText(3, QCoreApplication.translate("CursorInterface", u"Inversion", None))
        self.downMovementComboBox.setItemText(4, QCoreApplication.translate("CursorInterface", u"Eversion", None))

        self.downMovementComboBox.setCurrentText(QCoreApplication.translate("CursorInterface", u"Rest", None))
        self.label_3.setText(QCoreApplication.translate("CursorInterface", u"RIGHT movement", None))
        self.upMovementComboBox.setItemText(0, QCoreApplication.translate("CursorInterface", u"Rest", None))
        self.upMovementComboBox.setItemText(1, QCoreApplication.translate("CursorInterface", u"Dorsiflexion", None))
        self.upMovementComboBox.setItemText(2, QCoreApplication.translate("CursorInterface", u"Plantarflexion", None))
        self.upMovementComboBox.setItemText(3, QCoreApplication.translate("CursorInterface", u"Inversion", None))
        self.upMovementComboBox.setItemText(4, QCoreApplication.translate("CursorInterface", u"Eversion", None))

        self.upMovementComboBox.setCurrentText(QCoreApplication.translate("CursorInterface", u"Rest", None))
        self.rightMovementComboBox.setItemText(0, QCoreApplication.translate("CursorInterface", u"Rest", None))
        self.rightMovementComboBox.setItemText(1, QCoreApplication.translate("CursorInterface", u"Dorsiflexion", None))
        self.rightMovementComboBox.setItemText(2, QCoreApplication.translate("CursorInterface", u"Plantarflexion", None))
        self.rightMovementComboBox.setItemText(3, QCoreApplication.translate("CursorInterface", u"Inversion", None))
        self.rightMovementComboBox.setItemText(4, QCoreApplication.translate("CursorInterface", u"Eversion", None))

        self.rightMovementComboBox.setCurrentText(QCoreApplication.translate("CursorInterface", u"Rest", None))
        self.label.setText(QCoreApplication.translate("CursorInterface", u"UP movement", None))
        self.leftMovementComboBox.setItemText(0, QCoreApplication.translate("CursorInterface", u"Rest", None))
        self.leftMovementComboBox.setItemText(1, QCoreApplication.translate("CursorInterface", u"Dorsiflexion", None))
        self.leftMovementComboBox.setItemText(2, QCoreApplication.translate("CursorInterface", u"Plantarflexion", None))
        self.leftMovementComboBox.setItemText(3, QCoreApplication.translate("CursorInterface", u"Inversion", None))
        self.leftMovementComboBox.setItemText(4, QCoreApplication.translate("CursorInterface", u"Eversion", None))

        self.leftMovementComboBox.setCurrentText(QCoreApplication.translate("CursorInterface", u"Rest", None))
        self.updateMovementTaskMapPushButton.setText(QCoreApplication.translate("CursorInterface", u"Update movement-task mapping", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.taskMappingTab), QCoreApplication.translate("CursorInterface", u"Task mapping", None))
        self.groupBox_2.setTitle(QCoreApplication.translate("CursorInterface", u"Reference cursor", None))
        self.groupBox_5.setTitle(QCoreApplication.translate("CursorInterface", u"Partial activation state", None))
        self.label_11.setText(QCoreApplication.translate("CursorInterface", u"Duration (s)", None))
        self.label_15.setText(QCoreApplication.translate("CursorInterface", u"Activation level (%)", None))
        self.cursorStopConditionComboBox.setItemText(0, QCoreApplication.translate("CursorInterface", u"When contracting", None))
        self.cursorStopConditionComboBox.setItemText(1, QCoreApplication.translate("CursorInterface", u"When relaxing", None))
        self.cursorStopConditionComboBox.setItemText(2, QCoreApplication.translate("CursorInterface", u"Both directions", None))

        self.label_6.setText(QCoreApplication.translate("CursorInterface", u"Cursor stop condition", None))
        self.groupBox_3.setTitle(QCoreApplication.translate("CursorInterface", u"Resting state (0%)", None))
        self.label_7.setText(QCoreApplication.translate("CursorInterface", u"Duration (s)", None))
        self.label_12.setText(QCoreApplication.translate("CursorInterface", u"Reference refresh rate (Hz)", None))
        self.groupBox_4.setTitle(QCoreApplication.translate("CursorInterface", u"Full activation state (100%)", None))
        self.label_9.setText(QCoreApplication.translate("CursorInterface", u"Duration (s)", None))
        self.label_5.setText(QCoreApplication.translate("CursorInterface", u"Cursor frequency (Hz)", None))
        self.referenceCursorRefreshRateComboBox.setItemText(0, QCoreApplication.translate("CursorInterface", u"60", None))
        self.referenceCursorRefreshRateComboBox.setItemText(1, QCoreApplication.translate("CursorInterface", u"30", None))
        self.referenceCursorRefreshRateComboBox.setItemText(2, QCoreApplication.translate("CursorInterface", u"20", None))
        self.referenceCursorRefreshRateComboBox.setItemText(3, QCoreApplication.translate("CursorInterface", u"10", None))

        self.targetBoxGroupBox.setTitle(QCoreApplication.translate("CursorInterface", u"Target box", None))
        self.label_10.setText(QCoreApplication.translate("CursorInterface", u"Inner bound range (%)", None))
        self.label_17.setText(QCoreApplication.translate("CursorInterface", u"Outer bound range (%)", None))
        self.groupBox_6.setTitle(QCoreApplication.translate("CursorInterface", u"Predicted cursor", None))
        self.label_13.setText(QCoreApplication.translate("CursorInterface", u"Smoothening factor", None))
        self.label_14.setText(QCoreApplication.translate("CursorInterface", u"Prediction freq. division factor", None))
        self.streamingPushButton.setText(QCoreApplication.translate("CursorInterface", u"Start Reference Streaming", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.cursorSettingsTab), QCoreApplication.translate("CursorInterface", u"Cursor settings", None))
        self.stimStreamGroupBox.setTitle(QCoreApplication.translate("CursorInterface", u"Stimulation external streaming", None))
        self.externalDeviceConnectPushButton.setText(QCoreApplication.translate("CursorInterface", u"Connect", None))
        self.externalDeviceStreamPushButton.setText(QCoreApplication.translate("CursorInterface", u"Stream", None))
        self.externalDeviceIPLineEdit.setText(QCoreApplication.translate("CursorInterface", u"192.168.14.10", None))
        self.label_25.setText(QCoreApplication.translate("CursorInterface", u"Ext. IP", None))
        self.label_26.setText(QCoreApplication.translate("CursorInterface", u"Ext. Port", None))
        self.externalDevicePortLineEdit.setText(QCoreApplication.translate("CursorInterface", u"12345", None))
        self.externalDeviceConfigurePushButton.setText(QCoreApplication.translate("CursorInterface", u"Configure", None))
        self.stimPulseParamsGroupBox.setTitle(QCoreApplication.translate("CursorInterface", u"Stimulation pulse parameters", None))
        self.label_27.setText(QCoreApplication.translate("CursorInterface", u"Frequency (Hz)", None))
        self.stimUserParamsGroupBox.setTitle(QCoreApplication.translate("CursorInterface", u"Stimulation ON/FF (checked) / Proportional (unchecked)", None))
        self.label_16.setText(QCoreApplication.translate("CursorInterface", u"UP stim threshold (%)", None))
        self.label_24.setText(QCoreApplication.translate("CursorInterface", u"Stimulation ON time (ms)", None))
        self.label_19.setText(QCoreApplication.translate("CursorInterface", u"DOWN stim threshold (%)", None))
        self.label_28.setText(QCoreApplication.translate("CursorInterface", u"Stimulation OFF time (ms)", None))
        self.label_21.setText(QCoreApplication.translate("CursorInterface", u"LEFT stim threshold (%)", None))
        self.label_20.setText(QCoreApplication.translate("CursorInterface", u"RIGHT stim threshold (%)", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab), QCoreApplication.translate("CursorInterface", u"Stimulation settings", None))
        self.groupBox_7.setTitle(QCoreApplication.translate("CursorInterface", u"Logging", None))
        self.label_8.setText(QCoreApplication.translate("CursorInterface", u"FPS display reference:", None))
        self.refCursorUpdateFPSLabel.setText(QCoreApplication.translate("CursorInterface", u"Placeholder", None))
        self.label_18.setText(QCoreApplication.translate("CursorInterface", u"FPS display prediction:", None))
        self.predCursorUpdateFPSLabel.setText(QCoreApplication.translate("CursorInterface", u"Placeholder", None))
    # retranslateUi

