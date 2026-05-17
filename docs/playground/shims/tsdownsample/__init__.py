"""Browser-only no-op replacement for `tsdownsample`.

The real `tsdownsample.M4Downsampler` is a Rust extension that picks
visually faithful min/max indices for a column at the screen-width
resolution. We don't have native extensions in the browser, so this
shim implements the same surface with a pure-NumPy approximation:
evenly-spaced samples. Good enough for a static playground demo;
clearly worse than M4 for noisy waveforms.

If MyoGestic ever upgrades `_signal_viewer_state.py` to require more
of the tsdownsample API, mirror it here.
"""

import numpy as np


class M4Downsampler:
    def downsample(self, x: np.ndarray, n_out: int) -> np.ndarray:
        """Return ``n_out`` evenly-spaced indices into ``x``.

        Real M4 picks four indices per bucket (min, max, first, last)
        for visual fidelity. This shim picks one - linearly spaced.
        Returns int64 indices; matches what the framework asserts on.
        """
        n = int(x.shape[0])
        n_out = int(n_out)
        if n <= n_out:
            return np.arange(n, dtype=np.int64)
        return np.linspace(0, n - 1, n_out, dtype=np.int64)
