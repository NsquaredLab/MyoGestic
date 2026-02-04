Visual Interfaces
==============================

A **Visual Interface** (VI) is an external application that provides visual
feedback to participants during experiments.  MyoGestic communicates with VIs
over UDP and manages their lifecycle.

Each VI integration consists of three components:

- **Setup Interface** -- Launches/stops the external process and manages
  communication (e.g., UDP sockets).
- **Recording Interface** -- Manages per-VI recording settings and ground
  truth collection.
- **Output System** -- Routes model predictions to the VI during online
  sessions.

MyoGestic supports **multiple active VIs simultaneously**.  The main window
exposes them via ``active_visual_interfaces``, a ``dict[str, VisualInterface]``
keyed by the VI short name (e.g., ``"VHI"``).

.. seealso::
   :doc:`/auto_examples/02_add_visual_interface/0_add_ui` for a tutorial on
   adding a new VI.

Templates
---------------------
.. currentmodule:: myogestic.gui.widgets.templates
.. autosummary::
    :toctree: generated/visual_interface
    :template: class.rst

    VisualInterface
    SetupInterfaceTemplate
    RecordingInterfaceTemplate

.. _output_system_template:

Output System Template
----------------------
.. currentmodule:: myogestic.gui.widgets.templates
.. autosummary::
    :toctree: generated/visual_interface
    :template: class.rst

    OutputSystemTemplate

Pre-implemented Visual Interfaces
===================================

.. _virtual_hand_interface:

Virtual Hand Interface (VHI)
------------------------------
Displays two virtual hands (user pose vs target pose) using a Unity
application.  Records 9 DOF of hand kinematics at 60 Hz and maps 10
gestures.

.. currentmodule:: myogestic.gui.widgets.visual_interfaces.virtual_hand_interface
.. autosummary::
    :toctree: generated/visual_interface
    :template: class.rst

    VirtualHandInterface_SetupInterface
    VirtualHandInterface_RecordingInterface
    VirtualHandInterface_OutputSystem

.. _kappa_hand_interface:

Kappa Hand Interface (KHI)
------------------------------
Similar to VHI with a different rendering backend.  Shares the **Hand** task
category (``HAND_TASK_MAP`` -- 10 gestures).

.. currentmodule:: myogestic.gui.widgets.visual_interfaces.kappa_hand_interface
.. autosummary::
    :toctree: generated/visual_interface
    :template: class.rst

    KappaHandInterface_SetupInterface
    KappaHandInterface_RecordingInterface
    KappaHandInterface_OutputSystem

.. _virtual_cursor_interface:

Virtual Cursor Interface (VCI)
-------------------------------
A 2-D cursor tracking task.  Uses the **Cursor** task category
(``CURSOR_TASK_MAP`` -- 5 directions: rest, up, down, right, left).

.. currentmodule:: myogestic.gui.widgets.visual_interfaces.virtual_cursor_interface
.. autosummary::
    :toctree: generated/visual_interface
    :template: class.rst

    VirtualCursorInterface_SetupInterface
    VirtualCursorInterface_RecordingInterface
    VirtualCursorInterface_OutputSystem
