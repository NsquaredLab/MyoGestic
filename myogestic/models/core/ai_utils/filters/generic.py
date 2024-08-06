from functools import partial
from typing import Literal, Sequence, Union

import numpy as np

from myogestic.models.core.ai_utils.filters._template import FilterBaseClass


class ApplyFunctionFilter(FilterBaseClass):
    """Filter that applies a function to the input array.

    Parameters
    ----------
    function : callable
        The function to apply. This can be any function that accepts a numpy array as input
        and returns a numpy array as output. Example: `np.mean` or lambda x: x + 1.
    input_is_chunked : bool
        Whether the input is chunked or not.
    representations_to_filter : Union[Literal["all"], Sequence[int]]
        The representations to filter. If "all", all representations are filtered.
    **function_kwargs
        Keyword arguments to pass to the function. For example, if the function is `np.mean`,
        then `axis=0` can be passed as a keyword argument.

    Methods
    -------
    __call__(input_array: np.ndarray) -> np.ndarray
        Filters the input array. Input shape is determined by whether the allowed_input_type
        is "both", "chunked" or "not chunked".
    """

    def __init__(
        self,
        function: callable,
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
        **function_kwargs,
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            allowed_input_type="both",
            changes_filtered_dimension=True,
        )
        self.function = function
        self.function_kwargs = function_kwargs

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        return self.function(
            input_array[representations_to_filter_indices], **self.function_kwargs
        )


class ApplyFiltersOverSameEMG(FilterBaseClass):
    """Filter that applies filters over the same EMG data.

    Parameters
    ----------
    filters : Sequence[FilterBaseClass]
        The filters to apply.
    input_is_chunked : bool
        Whether the input is chunked or not.
    representations_to_filter : Union[Literal["all"], Sequence[int]]
        The representations to filter. If "all", all representations are filtered.
    aggregation_function : callable
        The function to use to aggregate the results of the filters. This can be any function
        that accepts a list of numpy arrays as input and returns a numpy array as output. Example:
        `np.concatenate` or `np.mean`.

    Methods
    -------
    __call__(input_array: np.ndarray) -> np.ndarray
        Filters the input array. Input shape is determined by whether the allowed_input_type
        is "both", "chunked" or "not chunked".
    """

    def __init__(
        self,
        filters: Sequence[FilterBaseClass],
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
        aggregation_function: callable = partial(np.concatenate, axis=-1),
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            allowed_input_type="both",
            changes_filtered_dimension=True,
        )
        self.filters = filters
        self.aggregation_function = aggregation_function

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        return self.aggregation_function(
            [
                filter(input_array[representations_to_filter_indices])
                for filter in self.filters
            ]
        )


class IndexDataFilter(FilterBaseClass):
    """Filter that indexes the input array.

    Parameters
    ----------
    indices : Sequence[Union[int, slice]]
        The indices to use for indexing the input array. Example: [0, 1, slice(2, 4)] will select the
        first two elements of the first dimension and the third and fourth elements of the second dimension.
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
        indices: Sequence[Union[int, slice]],
        input_is_chunked: bool = True,
        representations_to_filter: Union[Literal["all"], Sequence[int]] = "all",
    ):
        super().__init__(
            input_is_chunked=input_is_chunked,
            representations_to_filter=representations_to_filter,
            allowed_input_type="both",
            changes_filtered_dimension=True,
        )
        self.indices = indices

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        return input_array[(representations_to_filter_indices, *self.indices)]
