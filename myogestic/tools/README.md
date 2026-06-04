# myogestic.tools

Two audiences share this namespace:

- **End-user:** `install_vhi.py` — downloads the Virtual Hand Interface release
  binary (`python -m myogestic.tools.install_vhi`, console script
  `myogestic-install-vhi`).
- **Development / testing:** `emg_generator.py` and `lsl_dummy.py` — synthetic
  LSL signal generators used by `examples/` and for local testing
  (`python -m myogestic.tools.emg_generator`). Not needed for normal use.

These intentionally stay under `myogestic.tools`: the `-m` entry points and the
example imports depend on these paths, so the modules are not relocated.
