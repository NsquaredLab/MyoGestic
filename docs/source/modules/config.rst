Config
==============================
The Registy class is used to (**gasp**) register different elements so they are available throughout the MyoGestic software.
The configuration parameters are used to set the parameters of the different models and features.

Following elements can be registered:

- Models
- Features (must be capable of running in real-time)
- Post prediction filters (mainly for smoothing)
- Visual interfaces
- Output systems (e.g. connection to a prosthetic)

Registry
------------------------

.. currentmodule:: myogestic.utils.config
.. autosummary::
    :toctree: generated/config
    :template: class.rst

    Registry

Configuration Parameters
------------------------
.. autotypeddict:: myogestic.utils.config.BoolParameter
.. autotypeddict:: myogestic.utils.config.IntParameter
.. autotypeddict:: myogestic.utils.config.FloatParameter
.. autotypeddict:: myogestic.utils.config.StringParameter
.. autotypeddict:: myogestic.utils.config.CategoricalParameter


.. _changeable_parameter:
.. autodata:: myogestic.utils.config.ChangeableParameter
    :annotation:

.. _unchangeable_parameter:
.. autodata:: myogestic.utils.config.UnchangeableParameter
    :annotation:

