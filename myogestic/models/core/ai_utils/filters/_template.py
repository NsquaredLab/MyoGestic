from typing import Literal, Sequence, Union

import numpy as np


class FilterBaseClass:
    """Base class for filters.

    Parameters
    ----------
    input_is_chunked : bool
        Whether the input is chunked or not.
    representations_to_filter : Union[Literal["all"], Sequence[int]]
        The representations to filter. If "all", all representations are filtered.
    allowed_input_type : Literal["both", "chunked", "not chunked"]
        Whether the filter accepts chunked input, not chunked input or both.
    changes_filtered_dimension : bool
        Whether the filter changes the filtered dimension. If True, representations_to_filter must be "all".

    Methods
    -------
    __call__(input_array: np.ndarray) -> np.ndarray
        Filters the input array. Input shape is determined by whether the allowed_input_type is "both", "chunked" or "not chunked".
    """

    def __init__(
        self,
        input_is_chunked: bool,
        representations_to_filter: Union[Literal["all"], Sequence[int]],
        allowed_input_type: Literal["both", "chunked", "not chunked"] = "both",
        changes_filtered_dimension: bool = False,
    ):
        self._allowed_input_type = allowed_input_type
        self._changes_filtered_dimension = changes_filtered_dimension

        self.input_is_chunked = input_is_chunked
        self.representations_to_filter = representations_to_filter

    @property
    def input_is_chunked(self) -> bool:
        return self._input_is_chunked

    @input_is_chunked.setter
    def input_is_chunked(self, value: bool):
        if self._allowed_input_type == "both":
            self._input_is_chunked = value
        elif self._allowed_input_type == "chunked":
            if value is False:
                raise ValueError(
                    f"This filter ({self.__class__.__name__}) only accepts chunked input."
                )
            self._input_is_chunked = value
        elif self._allowed_input_type == "not chunked":
            if value is True:
                raise ValueError(
                    f"This filter ({self.__class__.__name__}) only accepts **not** chunked input."
                )
            self._input_is_chunked = value

    @property
    def representations_to_filter(self) -> Union[Literal["all"], Sequence[int]]:
        return self._representations_to_filter

    @representations_to_filter.setter
    def representations_to_filter(self, value: Union[Literal["all"], Sequence[int]]):
        if self._changes_filtered_dimension and value != "all":
            raise ValueError(
                f"This filter ({self.__class__.__name__}) changes the filtered dimension. "
                f"Please set representations_to_filter to 'all'."
            )
        self._representations_to_filter = value

    def __call__(self, input_array: np.ndarray) -> np.ndarray:
        return self._filter(
            input_array, self._get_representations_to_filter_indices(input_array)
        )

    def _get_representations_to_filter_indices(
        self, input_array: np.ndarray
    ) -> np.ndarray:
        if self.representations_to_filter == "all":
            return np.arange(input_array.shape[0])
        else:
            return np.unique(self.representations_to_filter)

    def _filter(
        self, input_array: np.ndarray, representations_to_filter_indices: np.ndarray
    ) -> np.ndarray:
        raise NotImplementedError()

    def __repr__(self):
        return f'{self.__class__.__name__}({", ".join([f"{k}={v}" for k, v in self.__dict__.items() if not k.startswith("_")])})'

    def __str__(self):
        return self.__repr__()
