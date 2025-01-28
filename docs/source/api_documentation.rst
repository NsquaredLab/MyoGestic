API Documentation
**************************

GUI Protocols (Panels)
======================
MyoGestic is made out of different panels that are used to control the software.
Internally we call these panels protocols since the researcher has to complete each panel from top to bottom, thus following a protocol.

.. toctree::
    :maxdepth: 2

    modules/protocols

Visual Interfaces
=================
MyoGesture supports any user made visual interface. By default we support our own visual hand interface.

.. toctree::
    :maxdepth: 2

    modules/visual_interface

Models
================
MyoGestic supports following models out of the box:

.. toctree::
    :maxdepth: 2

    modules/models

Config
================
The models and features can be set in the configuration file:

.. toctree::
    :maxdepth: 1

    modules/config

.. important:: If you wish to add a new model or feature, you must add it to the user configuration file. See :ref:`examples-index` for more information.
