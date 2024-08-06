API Documentation
**************************

GUI Protocols (Panels)
======================
MyoGestic is made out of different panels that are used to control the software.
Internally we call these panels protocols since the researcher has to complete each panel from top to bottom, thus following a protocol.

The protocols are as follows:

.. toctree::
    :maxdepth: 1

    modules/gui/record
    modules/gui/training
    modules/gui/online

The base protocol must be inherited by all other protocols. It is the base class for all protocols.

.. toctree::
    :maxdepth: 1

    modules/gui/default

Models
================
MyoGestic supports following models out of the box:

.. toctree::
    :maxdepth: 2

    modules/models/definitions

The models are configured in the configuration file:

.. toctree::
    :maxdepth: 1

    modules/models/config

.. important:: If you wish to add a new model, you must add it to the user configuration file. See :ref:`examples-index` for more information.


Features
================

.. warning:: The feature API will be changed in the future. We are currently working on a new feature API that will be more flexible and easier to use. Stay tuned for updates.

The features can be set in the configuration file:

.. toctree::
    :maxdepth: 1

    modules/models/config

Following features are supported out of the box:

.. toctree::
    :maxdepth: 2

    modules/features/temporal