Config
==============================
The :class:`~myogestic.utils.config.Registry` is the central registration
mechanism for all extensible components in MyoGestic.  It is instantiated
once as ``CONFIG_REGISTRY`` and imported throughout the application.

.. py:module:: myogestic.default_config

   Built-in component registrations (models, features, filters, VIs).

.. py:module:: myogestic.user_config

   User-defined component registrations -- add your own models, features,
   filters, VIs and output systems here.

Registration Workflow
-----------------------
Default components (built-in models, features, VIs) are registered in
:mod:`myogestic.default_config`.  User extensions are registered in
:mod:`myogestic.user_config`, which is loaded after the defaults and can
add new components or override existing ones.

The following elements can be registered:

- **Models** -- via :meth:`~myogestic.utils.config.Registry.register_model`
- **Features** -- via :meth:`~myogestic.utils.config.Registry.register_feature`
  (must be capable of running in real-time)
- **Post-prediction filters** -- via
  :meth:`~myogestic.utils.config.Registry.register_real_time_filter`
  (mainly for smoothing regression output)
- **Visual interfaces** -- via
  :meth:`~myogestic.utils.config.Registry.register_visual_interface`
- **Output systems** -- via
  :meth:`~myogestic.utils.config.Registry.register_output_system`

.. seealso::
   The :doc:`/auto_examples/01_add_functionality/index` tutorials walk
   through adding each type of component.

Registry
------------------------

.. currentmodule:: myogestic.utils.config
.. autosummary::
    :toctree: generated/config
    :template: class.rst

    Registry

.. _config_parameters:

Configuration Parameters
------------------------
.. _changeable_parameter:

Changeable Parameter
^^^^^^^^^^^^^^^^^^^^^
.. autodata:: myogestic.utils.config.ChangeableParameter
    :annotation:

.. autotypeddict:: myogestic.utils.config.BoolParameter
.. autotypeddict:: myogestic.utils.config.IntParameter
.. autotypeddict:: myogestic.utils.config.FloatParameter
.. autotypeddict:: myogestic.utils.config.StringParameter
.. autotypeddict:: myogestic.utils.config.CategoricalParameter

.. _unchangeable_parameter:

Unchangeable Parameter
^^^^^^^^^^^^^^^^^^^^^^^
.. autodata:: myogestic.utils.config.UnchangeableParameter
    :annotation:

