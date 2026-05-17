"""Browser-only no-op replacement for the `mne_lsl` package.

MyoGestic touches `mne_lsl` lazily inside source/output/recording paths
to get LSL clock timestamps and pull/push samples. In the browser there
is no LSL network, so the only call we have to satisfy is
``mne_lsl.lsl.local_clock``, which MyoGestic uses as a monotonic clock
when adding label events to a session.

This shim provides the bare minimum so `import mne_lsl.lsl` and
`mne_lsl.lsl.local_clock()` succeed. Any code path that actually needs
LSL transport (LSLSource, LSLOutlet, the EMG generator CLI) is gated
out of the playground at the import-site level.
"""

from . import lsl

__all__ = ["lsl"]
