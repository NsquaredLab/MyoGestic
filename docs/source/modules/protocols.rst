Protocols
==============================

MyoGestic is made out of different panels that are used to control the software.
Internally we call these panels "protocols" since the researcher has to complete
each panel from top to bottom, thus following a protocol.

The following protocols are available:

- **Protocol** — Base class for all protocols
- **RecordProtocol** — Handles EMG recording sessions with visual interfaces
- **TrainingProtocol** — Manages model training from recorded data
- **OnlineProtocol** — Runs real-time prediction with trained models

.. note::

   Protocols are internal GUI components and are not intended to be extended
   by users. For extending MyoGestic functionality, see the
   :doc:`visual_interface` and :doc:`config` documentation.
