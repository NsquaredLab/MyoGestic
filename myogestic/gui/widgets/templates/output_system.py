from abc import abstractmethod
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtGui import QCloseEvent

from myogestic.gui.widgets.templates.meta_qobject import MetaQObjectABC


class OutputSystemTemplate(QObject, metaclass=MetaQObjectABC):
    """
    Represents a base class handling initialization of main window and prediction type
    for classification or regression tasks. Determines the appropriate method for
    processing predictions based on the given prediction type.

    Parameters
    ----------
    main_window : Any
        The main application window instance. Cannot be None.
    prediction_is_classification : bool
        Indicates whether the prediction task is classification or regression.
        Cannot be None.

    Attributes
    ----------
    _main_window : Any
        A reference to the main application window instance.
    _prediction_is_classification : bool
        Specifies whether the prediction task is classification.
    process_prediction : Callable
        Function pointer to the appropriate method for processing predictions,
        defined based on `_prediction_is_classification`.
    """
    def __init__(
        self, main_window=None, prediction_is_classification: bool = None
    ) -> None:

        super().__init__()

        if main_window is None:
            raise ValueError("The _main_window must be provided.")
        if prediction_is_classification is None:
            raise ValueError("The _prediction_is_classification must be provided.")

        self._main_window = main_window
        self._prediction_is_classification = prediction_is_classification

        self.process_prediction = (
            self._process_prediction__classification
            if self._prediction_is_classification
            else self._process_prediction__regression
        )

    @abstractmethod
    def _process_prediction__classification(self, prediction: Any) -> Any:
        """
        An abstract method that processes classification predictions.

        This method is intended to be implemented by subclasses to handle
        classification-related prediction processing. The specific implementation
        is left to the subclass, allowing for custom behavior depending on the
        use case.

        Parameters
        ----------
        prediction : Any
            The prediction data/object that needs to be processed.

        Returns
        -------
        Any
            The processed output after applying classification-specific logic. The exact type depends on the
            subclass implementation.
        """
        pass

    @abstractmethod
    def _process_prediction__regression(self, prediction: Any) -> Any:
        """
        Process regression prediction abstract method.

        This is an abstract method that should be implemented by subclasses to
        handle regression predictions. The implementation is responsible for
        processing the given prediction in a regression-specific manner.

        Parameters
        ----------
        prediction : Any
            The input prediction data to be processed.

        Returns
        -------
        Any
            The processed regression prediction. The exact type depends on the
            subclass implementation.
        """
        pass

    @abstractmethod
    def send_prediction(self, prediction: Any) -> None:
        """
        An abstract method meant to be implemented by subclasses for the purpose
        of sending prediction values to a specific destination. The method is
        designed to handle any type of prediction and does not return a value.

        Parameters
        ----------
        prediction : Any
            The prediction value or object to be sent. The type of this parameter
            can vary depending on the specific implementation, allowing flexibility
            for various use cases.
        """
        pass

    @abstractmethod
    def close_event(self, event: QCloseEvent):  # noqa
        """
        Close event handler for the widget or window.

        This method is meant to be implemented in custom subclasses to handle the
        close event, which occurs when the widget or window is about to be closed.
        It serves as a central point to define tasks or behavior that should be
        executed during the closing process, such as cleanup operations, saving
        data, or confirming user actions.

        Parameters
        ----------
        event : QCloseEvent
            The close event object that contains information about the close action
            and provides options for accepting or ignoring the event.

        """
        pass
