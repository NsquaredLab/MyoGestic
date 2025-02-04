"""
=========================================
Part 0: Create the UI
=========================================

.. note::
   A visual interface is generally intended to be a standalone program that can communicate (both receiving and sending) through information exchange protocols (e.g., UDP).
   This way the visual interface is a standalone process that will not be hindered by MyoGestic's runtime.

Visual interfaces in MyoGestic must include three modular components:

1. **Setup Interface**: Configures the parameters and initializes the system (e.g. hardware, data pipeline).
2. **Recording Interface**: Manages runtime interactions and data visualization.
3. **Output Interface**: Defines how results are presented (e.g., virtual hands, plots).

.. important::
    To start copy the UI files in ``myogestic > gui > widgets > visual_interfaces > ui`` and adapt them with the functionality you need.

    You need to modify them with `QT-Designer <https://doc.qt.io/qtforpython-6/tools/pyside-designer.html>`_ and convert them using `UIC <https://doc.qt.io/qtforpython-6/tools/pyside-uic.html>`_ to a python file.

"""