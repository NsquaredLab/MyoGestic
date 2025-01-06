# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main_window_v2.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLayout, QLineEdit, QMainWindow,
    QProgressBar, QPushButton, QRadioButton, QScrollArea,
    QSizePolicy, QSpacerItem, QSpinBox, QStackedWidget,
    QStatusBar, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget)

from biosignal_device_interface.gui.plot_widgets.biosignal_plot_widget import BiosignalPlotWidget

class Ui_MyoGestic(object):
    def setupUi(self, MyoGestic):
        if not MyoGestic.objectName():
            MyoGestic.setObjectName(u"MyoGestic")
        MyoGestic.resize(945, 971)
        self.actionPreferences = QAction(MyoGestic)
        self.actionPreferences.setObjectName(u"actionPreferences")
        self.actionPreferences.setEnabled(True)
        self.centralwidget = QWidget(MyoGestic)
        self.centralwidget.setObjectName(u"centralwidget")
        self.gridLayout = QGridLayout(self.centralwidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.verticalLayout = QVBoxLayout()
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setSpacing(0)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalLayout.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.horizontalLayout.setContentsMargins(-1, 0, 0, 0)
        self.toggleVispyPlotCheckBox = QCheckBox(self.centralwidget)
        self.toggleVispyPlotCheckBox.setObjectName(u"toggleVispyPlotCheckBox")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.toggleVispyPlotCheckBox.sizePolicy().hasHeightForWidth())
        self.toggleVispyPlotCheckBox.setSizePolicy(sizePolicy)
        self.toggleVispyPlotCheckBox.setChecked(True)

        self.horizontalLayout.addWidget(self.toggleVispyPlotCheckBox)

        self.label_9 = QLabel(self.centralwidget)
        self.label_9.setObjectName(u"label_9")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.label_9.sizePolicy().hasHeightForWidth())
        self.label_9.setSizePolicy(sizePolicy1)

        self.horizontalLayout.addWidget(self.label_9)

        self.timeShownDoubleSpinBox = QDoubleSpinBox(self.centralwidget)
        self.timeShownDoubleSpinBox.setObjectName(u"timeShownDoubleSpinBox")
        sizePolicy1.setHeightForWidth(self.timeShownDoubleSpinBox.sizePolicy().hasHeightForWidth())
        self.timeShownDoubleSpinBox.setSizePolicy(sizePolicy1)
        self.timeShownDoubleSpinBox.setDecimals(1)
        self.timeShownDoubleSpinBox.setMinimum(0.100000000000000)
        self.timeShownDoubleSpinBox.setMaximum(300.000000000000000)
        self.timeShownDoubleSpinBox.setValue(10.000000000000000)

        self.horizontalLayout.addWidget(self.timeShownDoubleSpinBox)


        self.verticalLayout.addLayout(self.horizontalLayout)

        self.vispyPlotWidget = BiosignalPlotWidget(self.centralwidget)
        self.vispyPlotWidget.setObjectName(u"vispyPlotWidget")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.MinimumExpanding)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.vispyPlotWidget.sizePolicy().hasHeightForWidth())
        self.vispyPlotWidget.setSizePolicy(sizePolicy2)
        self.vispyPlotWidget.setMinimumSize(QSize(500, 634))
        self.vispyPlotWidget.setSizeIncrement(QSize(0, 0))

        self.verticalLayout.addWidget(self.vispyPlotWidget)


        self.gridLayout.addLayout(self.verticalLayout, 0, 1, 2, 1)

        self.loggingGroupBox = QGroupBox(self.centralwidget)
        self.loggingGroupBox.setObjectName(u"loggingGroupBox")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.loggingGroupBox.sizePolicy().hasHeightForWidth())
        self.loggingGroupBox.setSizePolicy(sizePolicy3)
        self.loggingGroupBox.setMinimumSize(QSize(0, 200))
        self.gridLayout_14 = QGridLayout(self.loggingGroupBox)
        self.gridLayout_14.setObjectName(u"gridLayout_14")
        self.loggingScrollArea = QScrollArea(self.loggingGroupBox)
        self.loggingScrollArea.setObjectName(u"loggingScrollArea")
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sizePolicy4.setHorizontalStretch(0)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.loggingScrollArea.sizePolicy().hasHeightForWidth())
        self.loggingScrollArea.setSizePolicy(sizePolicy4)
        self.loggingScrollArea.setWidgetResizable(True)
        self.loggingScrollAreaWidgetContents = QWidget()
        self.loggingScrollAreaWidgetContents.setObjectName(u"loggingScrollAreaWidgetContents")
        self.loggingScrollAreaWidgetContents.setGeometry(QRect(0, 0, 298, 186))
        self.gridLayout_15 = QGridLayout(self.loggingScrollAreaWidgetContents)
        self.gridLayout_15.setObjectName(u"gridLayout_15")
        self.loggingTextEdit = QTextEdit(self.loggingScrollAreaWidgetContents)
        self.loggingTextEdit.setObjectName(u"loggingTextEdit")

        self.gridLayout_15.addWidget(self.loggingTextEdit, 0, 0, 1, 1)

        self.loggingScrollArea.setWidget(self.loggingScrollAreaWidgetContents)

        self.gridLayout_14.addWidget(self.loggingScrollArea, 1, 0, 1, 2)

        self.label_4 = QLabel(self.loggingGroupBox)
        self.label_4.setObjectName(u"label_4")

        self.gridLayout_14.addWidget(self.label_4, 0, 0, 1, 1)

        self.appUpdateFPSLabel = QLabel(self.loggingGroupBox)
        self.appUpdateFPSLabel.setObjectName(u"appUpdateFPSLabel")

        self.gridLayout_14.addWidget(self.appUpdateFPSLabel, 0, 1, 1, 1)


        self.gridLayout.addWidget(self.loggingGroupBox, 1, 0, 1, 1)

        self.mindMoveTabWidget = QTabWidget(self.centralwidget)
        self.mindMoveTabWidget.setObjectName(u"mindMoveTabWidget")
        sizePolicy4.setHeightForWidth(self.mindMoveTabWidget.sizePolicy().hasHeightForWidth())
        self.mindMoveTabWidget.setSizePolicy(sizePolicy4)
        self.setupTab = QWidget()
        self.setupTab.setObjectName(u"setupTab")
        self.gridLayout_6 = QGridLayout(self.setupTab)
        self.gridLayout_6.setObjectName(u"gridLayout_6")
        self.setupVerticalLayout = QVBoxLayout()
        self.setupVerticalLayout.setObjectName(u"setupVerticalLayout")

        self.gridLayout_6.addLayout(self.setupVerticalLayout, 0, 0, 1, 1)

        self.mindMoveTabWidget.addTab(self.setupTab, "")
        self.procotolWidget = QWidget()
        self.procotolWidget.setObjectName(u"procotolWidget")
        self.gridLayout_2 = QGridLayout(self.procotolWidget)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.protocolModeStackedWidget = QStackedWidget(self.procotolWidget)
        self.protocolModeStackedWidget.setObjectName(u"protocolModeStackedWidget")
        self.recordWidget = QWidget()
        self.recordWidget.setObjectName(u"recordWidget")
        self.gridLayout_5 = QGridLayout(self.recordWidget)
        self.gridLayout_5.setObjectName(u"gridLayout_5")
        self.recordVerticalLayout = QVBoxLayout()
        self.recordVerticalLayout.setObjectName(u"recordVerticalLayout")

        self.gridLayout_5.addLayout(self.recordVerticalLayout, 1, 0, 1, 1)

        self.verticalSpacer_5 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.gridLayout_5.addItem(self.verticalSpacer_5, 4, 0, 1, 1)

        self.groupBox = QGroupBox(self.recordWidget)
        self.groupBox.setObjectName(u"groupBox")
        self.gridLayout_8 = QGridLayout(self.groupBox)
        self.gridLayout_8.setObjectName(u"gridLayout_8")
        self.recordEMGProgressBar = QProgressBar(self.groupBox)
        self.recordEMGProgressBar.setObjectName(u"recordEMGProgressBar")
        self.recordEMGProgressBar.setValue(24)

        self.gridLayout_8.addWidget(self.recordEMGProgressBar, 0, 0, 1, 1)


        self.gridLayout_5.addWidget(self.groupBox, 0, 0, 1, 1)

        self.protocolModeStackedWidget.addWidget(self.recordWidget)
        self.trainingWidget = QWidget()
        self.trainingWidget.setObjectName(u"trainingWidget")
        self.gridLayout_12 = QGridLayout(self.trainingWidget)
        self.gridLayout_12.setObjectName(u"gridLayout_12")
        self.trainingCreateDatasetGroupBox = QGroupBox(self.trainingWidget)
        self.trainingCreateDatasetGroupBox.setObjectName(u"trainingCreateDatasetGroupBox")
        sizePolicy5 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy5.setHorizontalStretch(0)
        sizePolicy5.setVerticalStretch(0)
        sizePolicy5.setHeightForWidth(self.trainingCreateDatasetGroupBox.sizePolicy().hasHeightForWidth())
        self.trainingCreateDatasetGroupBox.setSizePolicy(sizePolicy5)
        self.gridLayout_13 = QGridLayout(self.trainingCreateDatasetGroupBox)
        self.gridLayout_13.setObjectName(u"gridLayout_13")
        self.label_6 = QLabel(self.trainingCreateDatasetGroupBox)
        self.label_6.setObjectName(u"label_6")

        self.gridLayout_13.addWidget(self.label_6, 3, 0, 1, 1)

        self.trainingCreateDatasetsSelectRecordingsPushButton = QPushButton(self.trainingCreateDatasetGroupBox)
        self.trainingCreateDatasetsSelectRecordingsPushButton.setObjectName(u"trainingCreateDatasetsSelectRecordingsPushButton")

        self.gridLayout_13.addWidget(self.trainingCreateDatasetsSelectRecordingsPushButton, 0, 0, 1, 1)

        self.trainingRemoveAllSelectedRecordingsPushButton = QPushButton(self.trainingCreateDatasetGroupBox)
        self.trainingRemoveAllSelectedRecordingsPushButton.setObjectName(u"trainingRemoveAllSelectedRecordingsPushButton")

        self.gridLayout_13.addWidget(self.trainingRemoveAllSelectedRecordingsPushButton, 2, 1, 1, 1)

        self.trainingRemoveSelectedRecordingPushButton = QPushButton(self.trainingCreateDatasetGroupBox)
        self.trainingRemoveSelectedRecordingPushButton.setObjectName(u"trainingRemoveSelectedRecordingPushButton")

        self.gridLayout_13.addWidget(self.trainingRemoveSelectedRecordingPushButton, 2, 0, 1, 1)

        self.trainingCreateDatasetSelectedRecordingsTableWidget = QTableWidget(self.trainingCreateDatasetGroupBox)
        if (self.trainingCreateDatasetSelectedRecordingsTableWidget.columnCount() < 3):
            self.trainingCreateDatasetSelectedRecordingsTableWidget.setColumnCount(3)
        __qtablewidgetitem = QTableWidgetItem()
        self.trainingCreateDatasetSelectedRecordingsTableWidget.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.trainingCreateDatasetSelectedRecordingsTableWidget.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.trainingCreateDatasetSelectedRecordingsTableWidget.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        self.trainingCreateDatasetSelectedRecordingsTableWidget.setObjectName(u"trainingCreateDatasetSelectedRecordingsTableWidget")
        sizePolicy6 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sizePolicy6.setHorizontalStretch(0)
        sizePolicy6.setVerticalStretch(0)
        sizePolicy6.setHeightForWidth(self.trainingCreateDatasetSelectedRecordingsTableWidget.sizePolicy().hasHeightForWidth())
        self.trainingCreateDatasetSelectedRecordingsTableWidget.setSizePolicy(sizePolicy6)

        self.gridLayout_13.addWidget(self.trainingCreateDatasetSelectedRecordingsTableWidget, 1, 0, 1, 2)

        self.trainingCreateDatasetLabelLineEdit = QLineEdit(self.trainingCreateDatasetGroupBox)
        self.trainingCreateDatasetLabelLineEdit.setObjectName(u"trainingCreateDatasetLabelLineEdit")
        sizePolicy5.setHeightForWidth(self.trainingCreateDatasetLabelLineEdit.sizePolicy().hasHeightForWidth())
        self.trainingCreateDatasetLabelLineEdit.setSizePolicy(sizePolicy5)

        self.gridLayout_13.addWidget(self.trainingCreateDatasetLabelLineEdit, 3, 1, 1, 1)

        self.trainingCreateDatasetPushButton = QPushButton(self.trainingCreateDatasetGroupBox)
        self.trainingCreateDatasetPushButton.setObjectName(u"trainingCreateDatasetPushButton")

        self.gridLayout_13.addWidget(self.trainingCreateDatasetPushButton, 4, 1, 1, 1)

        self.trainingCreateDatasetSelectFeaturesPushButton = QPushButton(self.trainingCreateDatasetGroupBox)
        self.trainingCreateDatasetSelectFeaturesPushButton.setObjectName(u"trainingCreateDatasetSelectFeaturesPushButton")

        self.gridLayout_13.addWidget(self.trainingCreateDatasetSelectFeaturesPushButton, 4, 0, 1, 1)


        self.gridLayout_12.addWidget(self.trainingCreateDatasetGroupBox, 0, 0, 1, 1)

        self.trainingTrainModelGroupBox = QGroupBox(self.trainingWidget)
        self.trainingTrainModelGroupBox.setObjectName(u"trainingTrainModelGroupBox")
        sizePolicy5.setHeightForWidth(self.trainingTrainModelGroupBox.sizePolicy().hasHeightForWidth())
        self.trainingTrainModelGroupBox.setSizePolicy(sizePolicy5)
        self.gridLayout_7 = QGridLayout(self.trainingTrainModelGroupBox)
        self.gridLayout_7.setObjectName(u"gridLayout_7")
        self.trainingModelSelectionComboBox = QComboBox(self.trainingTrainModelGroupBox)
        self.trainingModelSelectionComboBox.setObjectName(u"trainingModelSelectionComboBox")

        self.gridLayout_7.addWidget(self.trainingModelSelectionComboBox, 1, 1, 1, 1)

        self.label_8 = QLabel(self.trainingTrainModelGroupBox)
        self.label_8.setObjectName(u"label_8")

        self.gridLayout_7.addWidget(self.label_8, 3, 0, 1, 1)

        self.trainingTrainModelPushButton = QPushButton(self.trainingTrainModelGroupBox)
        self.trainingTrainModelPushButton.setObjectName(u"trainingTrainModelPushButton")

        self.gridLayout_7.addWidget(self.trainingTrainModelPushButton, 5, 0, 2, 2)

        self.trainingSelectDatasetPushButton = QPushButton(self.trainingTrainModelGroupBox)
        self.trainingSelectDatasetPushButton.setObjectName(u"trainingSelectDatasetPushButton")

        self.gridLayout_7.addWidget(self.trainingSelectDatasetPushButton, 0, 0, 1, 1)

        self.label_3 = QLabel(self.trainingTrainModelGroupBox)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout_7.addWidget(self.label_3, 1, 0, 1, 1)

        self.trainingSelectedDatasetLabel = QLabel(self.trainingTrainModelGroupBox)
        self.trainingSelectedDatasetLabel.setObjectName(u"trainingSelectedDatasetLabel")

        self.gridLayout_7.addWidget(self.trainingSelectedDatasetLabel, 0, 1, 1, 1)

        self.trainingModelLabelLineEdit = QLineEdit(self.trainingTrainModelGroupBox)
        self.trainingModelLabelLineEdit.setObjectName(u"trainingModelLabelLineEdit")
        sizePolicy5.setHeightForWidth(self.trainingModelLabelLineEdit.sizePolicy().hasHeightForWidth())
        self.trainingModelLabelLineEdit.setSizePolicy(sizePolicy5)

        self.gridLayout_7.addWidget(self.trainingModelLabelLineEdit, 3, 1, 1, 1)

        self.trainingModelParametersPushButton = QPushButton(self.trainingTrainModelGroupBox)
        self.trainingModelParametersPushButton.setObjectName(u"trainingModelParametersPushButton")

        self.gridLayout_7.addWidget(self.trainingModelParametersPushButton, 2, 0, 1, 2)


        self.gridLayout_12.addWidget(self.trainingTrainModelGroupBox, 1, 0, 1, 1)

        self.verticalSpacer_2 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.gridLayout_12.addItem(self.verticalSpacer_2, 2, 0, 1, 1)

        self.protocolModeStackedWidget.addWidget(self.trainingWidget)
        self.onlineWidget = QWidget()
        self.onlineWidget.setObjectName(u"onlineWidget")
        self.gridLayout_4 = QGridLayout(self.onlineWidget)
        self.gridLayout_4.setObjectName(u"gridLayout_4")
        self.verticalSpacer_3 = QSpacerItem(10, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.gridLayout_4.addItem(self.verticalSpacer_3, 2, 0, 1, 1)

        self.onlineLoadModelGroupBox = QGroupBox(self.onlineWidget)
        self.onlineLoadModelGroupBox.setObjectName(u"onlineLoadModelGroupBox")
        sizePolicy5.setHeightForWidth(self.onlineLoadModelGroupBox.sizePolicy().hasHeightForWidth())
        self.onlineLoadModelGroupBox.setSizePolicy(sizePolicy5)
        self.gridLayout_18 = QGridLayout(self.onlineLoadModelGroupBox)
        self.gridLayout_18.setObjectName(u"gridLayout_18")
        self.onlineLoadModelPushButton = QPushButton(self.onlineLoadModelGroupBox)
        self.onlineLoadModelPushButton.setObjectName(u"onlineLoadModelPushButton")
        self.onlineLoadModelPushButton.setCheckable(False)

        self.gridLayout_18.addWidget(self.onlineLoadModelPushButton, 0, 0, 1, 1)

        self.onlineModelLabel = QLabel(self.onlineLoadModelGroupBox)
        self.onlineModelLabel.setObjectName(u"onlineModelLabel")

        self.gridLayout_18.addWidget(self.onlineModelLabel, 0, 1, 1, 1)


        self.gridLayout_4.addWidget(self.onlineLoadModelGroupBox, 0, 0, 1, 1)

        self.onlineCommandsGroupBox = QGroupBox(self.onlineWidget)
        self.onlineCommandsGroupBox.setObjectName(u"onlineCommandsGroupBox")
        sizePolicy5.setHeightForWidth(self.onlineCommandsGroupBox.sizePolicy().hasHeightForWidth())
        self.onlineCommandsGroupBox.setSizePolicy(sizePolicy5)
        self.gridLayout_19 = QGridLayout(self.onlineCommandsGroupBox)
        self.gridLayout_19.setObjectName(u"gridLayout_19")
        self.onlineRecordTogglePushButton = QPushButton(self.onlineCommandsGroupBox)
        self.onlineRecordTogglePushButton.setObjectName(u"onlineRecordTogglePushButton")
        self.onlineRecordTogglePushButton.setCheckable(True)

        self.gridLayout_19.addWidget(self.onlineRecordTogglePushButton, 0, 1, 1, 1)

        self.onlinePredictionTogglePushButton = QPushButton(self.onlineCommandsGroupBox)
        self.onlinePredictionTogglePushButton.setObjectName(u"onlinePredictionTogglePushButton")
        self.onlinePredictionTogglePushButton.setCheckable(True)

        self.gridLayout_19.addWidget(self.onlinePredictionTogglePushButton, 0, 0, 1, 1)


        self.gridLayout_4.addWidget(self.onlineCommandsGroupBox, 4, 0, 1, 1)

        self.conformalPredictionGroupBox = QGroupBox(self.onlineWidget)
        self.conformalPredictionGroupBox.setObjectName(u"conformalPredictionGroupBox")
        self.conformalPredictionGroupBox.setEnabled(True)
        sizePolicy5.setHeightForWidth(self.conformalPredictionGroupBox.sizePolicy().hasHeightForWidth())
        self.conformalPredictionGroupBox.setSizePolicy(sizePolicy5)
        self.gridLayout_32 = QGridLayout(self.conformalPredictionGroupBox)
        self.gridLayout_32.setObjectName(u"gridLayout_32")
        self.labelCpKernelSize = QLabel(self.conformalPredictionGroupBox)
        self.labelCpKernelSize.setObjectName(u"labelCpKernelSize")

        self.gridLayout_32.addWidget(self.labelCpKernelSize, 3, 0, 1, 1)

        self.conformalPredictionSolvingComboBox = QComboBox(self.conformalPredictionGroupBox)
        self.conformalPredictionSolvingComboBox.addItem("")
        self.conformalPredictionSolvingComboBox.addItem("")
        self.conformalPredictionSolvingComboBox.addItem("")
        self.conformalPredictionSolvingComboBox.setObjectName(u"conformalPredictionSolvingComboBox")
        self.conformalPredictionSolvingComboBox.setEnabled(False)
        sizePolicy7 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy7.setHorizontalStretch(0)
        sizePolicy7.setVerticalStretch(0)
        sizePolicy7.setHeightForWidth(self.conformalPredictionSolvingComboBox.sizePolicy().hasHeightForWidth())
        self.conformalPredictionSolvingComboBox.setSizePolicy(sizePolicy7)
        self.conformalPredictionSolvingComboBox.setEditable(False)

        self.gridLayout_32.addWidget(self.conformalPredictionSolvingComboBox, 2, 2, 1, 1)

        self.conformalPredictionSetPushButton = QPushButton(self.conformalPredictionGroupBox)
        self.conformalPredictionSetPushButton.setObjectName(u"conformalPredictionSetPushButton")
        self.conformalPredictionSetPushButton.setCheckable(True)

        self.gridLayout_32.addWidget(self.conformalPredictionSetPushButton, 4, 2, 1, 1)

        self.labelCpSolvingMethod = QLabel(self.conformalPredictionGroupBox)
        self.labelCpSolvingMethod.setObjectName(u"labelCpSolvingMethod")

        self.gridLayout_32.addWidget(self.labelCpSolvingMethod, 2, 0, 1, 1)

        self.conformalPredictionTypeComboBox = QComboBox(self.conformalPredictionGroupBox)
        self.conformalPredictionTypeComboBox.addItem("")
        self.conformalPredictionTypeComboBox.addItem("")
        self.conformalPredictionTypeComboBox.addItem("")
        self.conformalPredictionTypeComboBox.addItem("")
        self.conformalPredictionTypeComboBox.setObjectName(u"conformalPredictionTypeComboBox")
        sizePolicy5.setHeightForWidth(self.conformalPredictionTypeComboBox.sizePolicy().hasHeightForWidth())
        self.conformalPredictionTypeComboBox.setSizePolicy(sizePolicy5)

        self.gridLayout_32.addWidget(self.conformalPredictionTypeComboBox, 0, 2, 1, 1)

        self.labelCpAlpha = QLabel(self.conformalPredictionGroupBox)
        self.labelCpAlpha.setObjectName(u"labelCpAlpha")

        self.gridLayout_32.addWidget(self.labelCpAlpha, 1, 0, 1, 1)

        self.label_16 = QLabel(self.conformalPredictionGroupBox)
        self.label_16.setObjectName(u"label_16")

        self.gridLayout_32.addWidget(self.label_16, 0, 0, 1, 1)

        self.conformalPredictionSolvingKernel = QSpinBox(self.conformalPredictionGroupBox)
        self.conformalPredictionSolvingKernel.setObjectName(u"conformalPredictionSolvingKernel")
        sizePolicy5.setHeightForWidth(self.conformalPredictionSolvingKernel.sizePolicy().hasHeightForWidth())
        self.conformalPredictionSolvingKernel.setSizePolicy(sizePolicy5)
        self.conformalPredictionSolvingKernel.setMaximum(111)
        self.conformalPredictionSolvingKernel.setValue(5)

        self.gridLayout_32.addWidget(self.conformalPredictionSolvingKernel, 3, 2, 1, 1)

        self.conformalPredictionAlphaDoubleSpinBox = QDoubleSpinBox(self.conformalPredictionGroupBox)
        self.conformalPredictionAlphaDoubleSpinBox.setObjectName(u"conformalPredictionAlphaDoubleSpinBox")
        sizePolicy5.setHeightForWidth(self.conformalPredictionAlphaDoubleSpinBox.sizePolicy().hasHeightForWidth())
        self.conformalPredictionAlphaDoubleSpinBox.setSizePolicy(sizePolicy5)
        self.conformalPredictionAlphaDoubleSpinBox.setMaximum(1.000000000000000)
        self.conformalPredictionAlphaDoubleSpinBox.setSingleStep(0.010000000000000)
        self.conformalPredictionAlphaDoubleSpinBox.setValue(0.100000000000000)

        self.gridLayout_32.addWidget(self.conformalPredictionAlphaDoubleSpinBox, 1, 2, 1, 1)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.gridLayout_32.addItem(self.horizontalSpacer, 2, 1, 1, 1)


        self.gridLayout_4.addWidget(self.conformalPredictionGroupBox, 1, 0, 1, 1)

        self.onlineFiltersGroupBox = QGroupBox(self.onlineWidget)
        self.onlineFiltersGroupBox.setObjectName(u"onlineFiltersGroupBox")
        sizePolicy5.setHeightForWidth(self.onlineFiltersGroupBox.sizePolicy().hasHeightForWidth())
        self.onlineFiltersGroupBox.setSizePolicy(sizePolicy5)
        self.onlineFiltersGroupBox.setMinimumSize(QSize(122, 0))
        self.onlineFiltersGroupBox.setMaximumSize(QSize(16777215, 16777215))
        self.gridLayout_16 = QGridLayout(self.onlineFiltersGroupBox)
        self.gridLayout_16.setObjectName(u"gridLayout_16")
        self.onlineFiltersComboBox = QComboBox(self.onlineFiltersGroupBox)
        self.onlineFiltersComboBox.setObjectName(u"onlineFiltersComboBox")
        sizePolicy8 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy8.setHorizontalStretch(0)
        sizePolicy8.setVerticalStretch(0)
        sizePolicy8.setHeightForWidth(self.onlineFiltersComboBox.sizePolicy().hasHeightForWidth())
        self.onlineFiltersComboBox.setSizePolicy(sizePolicy8)

        self.gridLayout_16.addWidget(self.onlineFiltersComboBox, 0, 0, 1, 1)


        self.gridLayout_4.addWidget(self.onlineFiltersGroupBox, 3, 0, 1, 1)

        self.protocolModeStackedWidget.addWidget(self.onlineWidget)

        self.gridLayout_2.addWidget(self.protocolModeStackedWidget, 2, 0, 1, 1)

        self.protocolModeGroupBox = QGroupBox(self.procotolWidget)
        self.protocolModeGroupBox.setObjectName(u"protocolModeGroupBox")
        self.gridLayout_3 = QGridLayout(self.protocolModeGroupBox)
        self.gridLayout_3.setObjectName(u"gridLayout_3")
        self.protocolTrainingRadioButton = QRadioButton(self.protocolModeGroupBox)
        self.protocolTrainingRadioButton.setObjectName(u"protocolTrainingRadioButton")

        self.gridLayout_3.addWidget(self.protocolTrainingRadioButton, 0, 1, 1, 1)

        self.protocolOnlineRadioButton = QRadioButton(self.protocolModeGroupBox)
        self.protocolOnlineRadioButton.setObjectName(u"protocolOnlineRadioButton")

        self.gridLayout_3.addWidget(self.protocolOnlineRadioButton, 0, 2, 1, 1)

        self.protocolRecordRadioButton = QRadioButton(self.protocolModeGroupBox)
        self.protocolRecordRadioButton.setObjectName(u"protocolRecordRadioButton")
        self.protocolRecordRadioButton.setChecked(True)

        self.gridLayout_3.addWidget(self.protocolRecordRadioButton, 0, 0, 1, 1)


        self.gridLayout_2.addWidget(self.protocolModeGroupBox, 0, 0, 1, 1)

        self.mindMoveTabWidget.addTab(self.procotolWidget, "")

        self.gridLayout.addWidget(self.mindMoveTabWidget, 0, 0, 1, 1)

        MyoGestic.setCentralWidget(self.centralwidget)
        self.statusbar = QStatusBar(MyoGestic)
        self.statusbar.setObjectName(u"statusbar")
        MyoGestic.setStatusBar(self.statusbar)

        self.retranslateUi(MyoGestic)

        self.mindMoveTabWidget.setCurrentIndex(1)
        self.protocolModeStackedWidget.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(MyoGestic)
    # setupUi

    def retranslateUi(self, MyoGestic):
        MyoGestic.setWindowTitle(QCoreApplication.translate("MyoGestic", u"MyoGestic - n-squared lab @ AIBE @ FAU", None))
        self.actionPreferences.setText(QCoreApplication.translate("MyoGestic", u"Preferences", None))
        self.toggleVispyPlotCheckBox.setText(QCoreApplication.translate("MyoGestic", u"Toggle Plot", None))
        self.label_9.setText(QCoreApplication.translate("MyoGestic", u"Time shown (s)", None))
        self.loggingGroupBox.setTitle(QCoreApplication.translate("MyoGestic", u"Logging", None))
        self.label_4.setText(QCoreApplication.translate("MyoGestic", u"FPS:", None))
        self.appUpdateFPSLabel.setText(QCoreApplication.translate("MyoGestic", u"Placeholder", None))
        self.mindMoveTabWidget.setTabText(self.mindMoveTabWidget.indexOf(self.setupTab), QCoreApplication.translate("MyoGestic", u"Setup", None))
        self.groupBox.setTitle(QCoreApplication.translate("MyoGestic", u"EMG", None))
        self.trainingCreateDatasetGroupBox.setTitle(QCoreApplication.translate("MyoGestic", u"Create Training Dataset", None))
        self.label_6.setText(QCoreApplication.translate("MyoGestic", u"Dataset Label", None))
        self.trainingCreateDatasetsSelectRecordingsPushButton.setText(QCoreApplication.translate("MyoGestic", u"Select Recordings", None))
        self.trainingRemoveAllSelectedRecordingsPushButton.setText(QCoreApplication.translate("MyoGestic", u"Remove All", None))
        self.trainingRemoveSelectedRecordingPushButton.setText(QCoreApplication.translate("MyoGestic", u"Remove Item", None))
        ___qtablewidgetitem = self.trainingCreateDatasetSelectedRecordingsTableWidget.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("MyoGestic", u"Task", None));
        ___qtablewidgetitem1 = self.trainingCreateDatasetSelectedRecordingsTableWidget.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("MyoGestic", u"Recorded Time", None));
        ___qtablewidgetitem2 = self.trainingCreateDatasetSelectedRecordingsTableWidget.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("MyoGestic", u"Labels", None));
        self.trainingCreateDatasetPushButton.setText(QCoreApplication.translate("MyoGestic", u"Create Dataset", None))
        self.trainingCreateDatasetSelectFeaturesPushButton.setText(QCoreApplication.translate("MyoGestic", u"Select Features", None))
        self.trainingTrainModelGroupBox.setTitle(QCoreApplication.translate("MyoGestic", u"Train Model", None))
        self.label_8.setText(QCoreApplication.translate("MyoGestic", u"Model Label", None))
        self.trainingTrainModelPushButton.setText(QCoreApplication.translate("MyoGestic", u"Train", None))
        self.trainingSelectDatasetPushButton.setText(QCoreApplication.translate("MyoGestic", u"Select Dataset", None))
        self.label_3.setText(QCoreApplication.translate("MyoGestic", u"Model", None))
        self.trainingSelectedDatasetLabel.setText(QCoreApplication.translate("MyoGestic", u"Placeholder", None))
        self.trainingModelParametersPushButton.setText(QCoreApplication.translate("MyoGestic", u"Change Parameters", None))
        self.onlineLoadModelGroupBox.setTitle(QCoreApplication.translate("MyoGestic", u"Load Model", None))
        self.onlineLoadModelPushButton.setText(QCoreApplication.translate("MyoGestic", u"Select Model", None))
        self.onlineModelLabel.setText(QCoreApplication.translate("MyoGestic", u"Placeholder", None))
        self.onlineCommandsGroupBox.setTitle(QCoreApplication.translate("MyoGestic", u"Commands", None))
        self.onlineRecordTogglePushButton.setText(QCoreApplication.translate("MyoGestic", u"Start Recording", None))
        self.onlinePredictionTogglePushButton.setText(QCoreApplication.translate("MyoGestic", u"Start Prediction", None))
        self.conformalPredictionGroupBox.setTitle(QCoreApplication.translate("MyoGestic", u"Conformal Prediction ", None))
        self.labelCpKernelSize.setText(QCoreApplication.translate("MyoGestic", u"Kernel Size", None))
        self.conformalPredictionSolvingComboBox.setItemText(0, QCoreApplication.translate("MyoGestic", u"Mode", None))
        self.conformalPredictionSolvingComboBox.setItemText(1, QCoreApplication.translate("MyoGestic", u"Weighted Mode", None))
        self.conformalPredictionSolvingComboBox.setItemText(2, QCoreApplication.translate("MyoGestic", u"Set Weighting", None))

        self.conformalPredictionSetPushButton.setText(QCoreApplication.translate("MyoGestic", u"Set", None))
        self.labelCpSolvingMethod.setText(QCoreApplication.translate("MyoGestic", u"Solving method", None))
        self.conformalPredictionTypeComboBox.setItemText(0, QCoreApplication.translate("MyoGestic", u"None", None))
        self.conformalPredictionTypeComboBox.setItemText(1, QCoreApplication.translate("MyoGestic", u"LAC", None))
        self.conformalPredictionTypeComboBox.setItemText(2, QCoreApplication.translate("MyoGestic", u"RAPS", None))
        self.conformalPredictionTypeComboBox.setItemText(3, QCoreApplication.translate("MyoGestic", u"APS", None))

        self.labelCpAlpha.setText(QCoreApplication.translate("MyoGestic", u"Alpha", None))
        self.label_16.setText(QCoreApplication.translate("MyoGestic", u"Type", None))
        self.onlineFiltersGroupBox.setTitle(QCoreApplication.translate("MyoGestic", u"Real-Time FIlters", None))
        self.protocolModeGroupBox.setTitle(QCoreApplication.translate("MyoGestic", u"Mode", None))
        self.protocolTrainingRadioButton.setText(QCoreApplication.translate("MyoGestic", u"Training", None))
        self.protocolOnlineRadioButton.setText(QCoreApplication.translate("MyoGestic", u"Online", None))
        self.protocolRecordRadioButton.setText(QCoreApplication.translate("MyoGestic", u"Record", None))
        self.mindMoveTabWidget.setTabText(self.mindMoveTabWidget.indexOf(self.procotolWidget), QCoreApplication.translate("MyoGestic", u"Protocol", None))
    # retranslateUi

