from __future__ import annotations

from typing import List, Literal, Sequence, Tuple, Union

import numpy as np
from scipy.fft import irfft, rfft, rfftfreq
from scipy.signal import savgol_filter, sosfilt, sosfiltfilt

from myogestic.models.core.ai_utils.filters._template import FilterBaseClass


class SOSFrequencyFilter(FilterBaseClass):
    """Filter that applies a second-order-section filter to the input array.

    Parameters
    ----------
    sos_filter_coefficients : tuple[np.ndarray, np.ndarray | float, np.ndarray]
        The second-order-section filter coefficients. This is a tuple of the form (sos, gain, delay).
    forwards_and_backwards : bool
        Whether to apply the filter forwards and backwards or only forwards.
    append_result_to_input : bool
        Whether to append the filtered result to the input array or not.
    input_is_chunked : bool
        Whether the input is chunked or not.
    representations_to_filter : Union[Literal["all"], Sequence[int]]
        The representations to filter. If "all", all representations are filtered.

    Methods
    -------
    __call__(input_array: np.ndarray) -> np.ndarray
        Filters the input array. Input shape is determined by whether the allowed_input_type
        is "both", "chunked" or "not chunked".
    """

    def __init__(
        self,
        sos_filter_coefficients: tuple[
            np.ndarray, Union[np.ndarray, float], np.ndarray
        ],
        forwards_and_backwards: bool = True,
        append_result_to_input: bool = True,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = (0,),
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
        )
        self.sos_filter_coefficients = sos_filter_coefficients
        self.forwards_and_backwards = forwards_and_backwards
        self.append_result_to_input = append_result_to_input

        self._filtering_method = sosfiltfilt if self.forwards_and_backwards else sosfilt

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = np.zeros(
            (len(representations_to_filter_indices), *input_array.shape[1:])
        )

        output_array[representations_to_filter_indices] = self._filtering_method(
            self.sos_filter_coefficients,
            input_array[representations_to_filter_indices],
            axis=-1,
        )

        if self.append_result_to_input:
            return np.concatenate([input_array, output_array], axis=0)

        return output_array


class RectifyFilter(FilterBaseClass):
    """Rectifies the windowed signal."""

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.abs(
                    input_array[
                        representations_to_filter_indices, ..., i : i + self.window_size
                    ]
                )
            )

        return np.concatenate(output_array, axis=-1)


class RMSFilter(FilterBaseClass):
    """Filter that computes the root mean square of the input array.

    Parameters
    ----------
    window_size : int
        The window size to use.
    shift : int
        The shift to use.
    input_is_chunked : bool
        Whether the input is chunked or not.
    representations_to_filter : Union[Literal["all"], Sequence[int]]
        The representations to filter. If "all", all representations are filtered.

    Methods
    -------
    __call__(input_array: np.ndarray) -> np.ndarray
        Filters the input array. Input shape is determined by whether the allowed_input_type
        is "both", "chunked" or "not chunked".
    """

    """Computes the Root Mean Square with given window length and window shift over the input signal. See formula in the
    following paper: https://doi.org/10.1080/10255842.2023.2165068.
    """

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.sqrt(
                    np.mean(
                        input_array[
                            representations_to_filter_indices,
                            ...,
                            i : i + self.window_size,
                        ]
                        ** 2,
                        axis=-1,
                        keepdims=True,
                    )
                )
            )

        return np.concatenate(output_array, axis=-1)


class MAVFilter(FilterBaseClass):
    """Computes the Mean Absolute Value with given window length and window shift over the input signal. See formula in
    the following paper: https://doi.org/10.1080/10255842.2023.2165068.
    """

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.mean(
                    np.abs(
                        input_array[
                            representations_to_filter_indices,
                            ...,
                            i : i + self.window_size,
                        ]
                    ),
                    axis=-1,
                    keepdims=True,
                )
            )

        return np.concatenate(output_array, axis=-1)


class IAVFilter(FilterBaseClass):
    """Computes the Integrated Absolute Value with given window length and window shift over the input signal. See
    formula in the following paper: https://doi.org/10.1080/10255842.2023.2165068.
    """

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.sum(
                    np.abs(
                        input_array[
                            representations_to_filter_indices,
                            ...,
                            i : i + self.window_size,
                        ]
                    ),
                    axis=-1,
                    keepdims=True,
                )
            )

        return np.concatenate(output_array, axis=-1)


class VARFilter(FilterBaseClass):
    """Computes the Variance with given window length and window shift over the input signal."""

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.var(
                    (
                        input_array[
                            representations_to_filter_indices,
                            ...,
                            i : i + self.window_size,
                        ]
                    ),
                    axis=-1,
                    keepdims=True,
                )
            )

        return np.concatenate(output_array, axis=-1)


class DASDVFilter(FilterBaseClass):
    """Computes the Difference Absolute Standard Deviation with given window length and window shift over the input
    signal. See formula in the following paper: https://doi.org/10.1016/j.eswa.2012.01.102.
    """

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.sqrt(
                    np.sum(
                        (
                            input_array[
                                representations_to_filter_indices,
                                ...,
                                i + 1 : i + self.window_size,
                            ]
                            - input_array[
                                representations_to_filter_indices,
                                ...,
                                i : i + self.window_size - 1,
                            ]
                        )
                        ** 2,
                        axis=-1,
                        keepdims=True,
                    )
                    / (self.window_size - 1)
                )
            )
        return np.concatenate(output_array, axis=-1)


class VOrderFilter(FilterBaseClass):
    """Computes the v-Order with given window length and window shift over the input signal. See formula in the
    following paper: https://doi.org/10.1186/1743-0003-7-21.
    """

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        v: int = 3,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift
        self.v = v

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.mean(
                    abs(
                        input_array[
                            representations_to_filter_indices,
                            ...,
                            i : i + self.window_size,
                        ]
                    )
                    ** self.v,
                    axis=-1,
                    keepdims=True,
                )
                ** (1 / self.v)
            )
        return np.concatenate(output_array, axis=-1)


class AACFilter(FilterBaseClass):
    """Computes the Average Amplitude Change with given window length and window shift over the input signal.
    See formula in the following paper: https://doi.org/10.1016/j.eswa.2012.01.102.
    """

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.mean(
                    abs(
                        input_array[
                            representations_to_filter_indices,
                            ...,
                            i + 1 : i + self.window_size,
                        ]
                        - input_array[
                            representations_to_filter_indices,
                            ...,
                            i : i + self.window_size - 1,
                        ]
                    ),
                    axis=-1,
                    keepdims=True,
                )
            )
        return np.concatenate(output_array, axis=-1)


class MFLFilter(FilterBaseClass):
    """Computes the Maximum Fractal Length with given window length and window shift over the input signal.

    See formula in the following paper [1]_ .

    Notes
    -----
    .. [1] https://doi.org/10.1016/j.eswa.2012.03.039
    """

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.log10(
                    np.sqrt(
                        np.sum(
                            (
                                input_array[
                                    representations_to_filter_indices,
                                    ...,
                                    i + 1 : i + self.window_size,
                                ]
                                - input_array[
                                    representations_to_filter_indices,
                                    ...,
                                    i : i + self.window_size - 1,
                                ]
                            )
                            ** 2,
                            axis=-1,
                            keepdims=True,
                        )
                    )
                )
            )
        return np.concatenate(output_array, axis=-1)


class WFLFilter(FilterBaseClass):
    """Computes the Waveform Length with given window length and window shift over the input signal. See
    formula in the following paper: https://doi.org/10.1080/10255842.2023.2165068.
    """

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.sum(
                    np.abs(
                        np.diff(
                            input_array[
                                representations_to_filter_indices,
                                ...,
                                i : i + self.window_size,
                            ]
                        )
                    ),
                    axis=-1,
                    keepdims=True,
                )
            )

        return np.concatenate(output_array, axis=-1)


class ZCFilter(FilterBaseClass):
    """Computes the Zero Crossings with given window length and window shift over the input signal. See formula in the
    following paper: https://doi.org/10.1080/10255842.2023.2165068.
    """

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.sum(
                    np.abs(
                        np.diff(
                            np.sign(
                                input_array[
                                    representations_to_filter_indices,
                                    ...,
                                    i : i + self.window_size,
                                ]
                            )
                        )
                    )
                    // 2,
                    axis=-1,
                    keepdims=True,
                )
            )

        return np.concatenate(output_array, axis=-1)


class SSCFilter(FilterBaseClass):
    """Computes the Slope Sign Change with given window length and window shift over the input signal. See formula in
    the following paper: https://doi.org/10.1080/10255842.2023.2165068.
    """

    def __init__(
        self,
        window_size: int,
        shift: int = 1,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            changes_filtered_dimension=True,
        )
        self.window_size = window_size
        self.shift = shift

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        output_array = []

        for i in range(0, input_array.shape[-1] - self.window_size + 1, self.shift):
            output_array.append(
                np.sum(
                    np.abs(
                        np.diff(
                            np.sign(
                                np.diff(
                                    input_array[
                                        representations_to_filter_indices,
                                        ...,
                                        i : i + self.window_size,
                                    ]
                                )
                            )
                        )
                    )
                    // 2,
                    axis=-1,
                    keepdims=True,
                )
            )

        return np.concatenate(output_array, axis=-1)
