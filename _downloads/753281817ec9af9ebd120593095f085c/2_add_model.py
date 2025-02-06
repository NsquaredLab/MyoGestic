"""
==============================
Add a Custom Model
==============================

This example demonstrates how to create and register a custom model to **MyoGestic**
using the ``CONFIG_REGISTRY`` from *user_config.py*. This example also explains
how to define **changeable** and **unchangeable** parameters in your configuration.

.. admonition:: We Recommend Implementing any Additions in *user_config.py*

   The *user_config.py* module is specifically designed for end-users to register
   and configure their own custom components such as models, features,
   and filters. This keeps your modifications modular, reduces conflicts with
   core MyoGestic settings, and simplifies upgrades in the future.

   .. important::
      By registering your addition in ``user_config.py``, you ensure that your custom
      configuration stays separate from core MyoGestic functionality and remains
      compatible with future updates.

Example Overview
----------------
1. **Create** a custom model class.
2. **Define** ``save``, ``load``, ``train``, and ``predict`` functions.
3. **Specify** parameters (changeable and unchangeable) for the model.
4. **Register** the model into ``CONFIG_REGISTRY`` using *user_config.py*.

"""
from myogestic.utils.config import CONFIG_REGISTRY


# %%
# --------------------------------
# Step 1: Define your custom model
# --------------------------------
class MyExampleModel:
    """
    A simple example model for demonstration purposes.

    This model is intentionally minimal—focus on the registration
    process rather than advanced machine learning logic.
    """

    def __init__(self, param1: float, param2: int):
        """
        Initialize the model with parameters.

        Parameters
        ----------
        param1 : float
            A parameter that can be changed (e.g., a hyperparameter).
        param2 : int
            A parameter that stays the same (e.g., a fixed architectural detail).
        """
        self.param1 = param1
        self.param2 = param2
        self.training_data = None

    def save(self, path: str):
        """
        Save the model to the specified path.

        Parameters
        ----------
        path : str
            The filepath to save this model instance.
        """
        with open(path, "w") as f:
            f.write(f"Model(param1={self.param1}, param2={self.param2})")

    def load(self, path: str):
        """
        Load the model from the specified path.

        Parameters
        ----------
        path : str
            The filepath to load model information from.
        """
        with open(path, "r") as f:
            data = f.read()
            print(f"Loaded model: {data}")

    def train(self, x, y):
        """
        Train the model on the specified data.

        Parameters
        ----------
        x : array-like
            Input features for training.
        y : array-like
            Target values for training.
        """
        self.training_data = {"x": x, "y": y}
        print(f"Model trained on {len(x)} samples with param1={self.param1}")

    def predict(self, x):
        """
        Predict on input data.

        Parameters
        ----------
        x : array-like
            Input features for prediction.

        Returns
        -------
        list
            A list of predictions computed by multiplying each input by param1.

        Raises
        ------
        RuntimeError
            If the model is not yet trained.
        """
        if self.training_data is None:
            raise RuntimeError("The model must be trained before making predictions.")
        return [x_i * self.param1 for x_i in x]


# %%
# ---------------------------------------------------------
# Step 2: Define required functions for the model lifecycle
# ---------------------------------------------------------
def save_function(model_path: str, model: MyExampleModel):
    """
    Save the model to the given path.

    Parameters
    ----------
    model_path : str
        Filepath to save the model.
    model : MyExampleModel
        An instance of MyExampleModel to be saved.
    """
    model.save(model_path)


def load_function(model_path: str):
    """
    Load the model from the given path and return a new instance.

    Parameters
    ----------
    model_path : str
        Filepath from which to load the model.

    Returns
    -------
    MyExampleModel
        A fresh instance of MyExampleModel with default initialization,
        then loaded.
    """
    model = MyExampleModel(param1=1.0, param2=10)  # Default initialization
    model.load(model_path)
    return model


def train_function(model: MyExampleModel, dataset, is_classifier: bool, logger):
    """
    Train the model on the given dataset.

    Parameters
    ----------
    model : MyExampleModel
        The model instance to train.
    dataset : dict
        A dictionary or object containing "x" and "y" for training.
    is_classifier : bool
        Indicates whether the model is used for classification tasks.
    logger : Any
        An optional logger for status messages or debug output.

    Returns
    -------
    MyExampleModel
        The trained model instance.
    """
    x_train = dataset["x"]  # e.g., Extract x training data
    y_train = dataset["y"]  # e.g., Extract y training targets
    model.train(x_train, y_train)
    return model


def predict_function(model: MyExampleModel, input_data, is_classifier: bool):
    """
    Perform prediction with the model on input data.

    Parameters
    ----------
    model : MyExampleModel
        The model instance to use for prediction.
    input_data : array-like
        The data on which you want predictions.
    is_classifier : bool
        Indicates classification usage; if True, handle accordingly.

    Returns
    -------
    list
        The predictions from the model.
    """
    predictions = model.predict(input_data)
    return predictions


# %%
# -----------------------------------------------------
# Step 3: Define changeable and unchangeable parameters
# -----------------------------------------------------
# For information on configuring parameters, refer to the :ref:`config_parameters`.
# This structure is used to define the model's hyperparameters and fixed settings,
# ensuring seamless integration with MyoGestic's UI so that they may be changed at runtime.
from myogestic.utils.config import ChangeableParameter, UnchangeableParameter  # noqa

changeable_params: dict[str, ChangeableParameter] = {
    "param1": {
        "default_value": 1.0,
        "start_value": 0.1,
        "end_value": 5.0,
        "step": 0.1,
    }
}

unchangeable_params: dict[str, UnchangeableParameter] = {
    "param2": 10
}  # Fixed value that cannot be changed dynamically

# %%
# -----------------------------------------------
# Step 4: Register the model into CONFIG_REGISTRY
# -----------------------------------------------
CONFIG_REGISTRY.register_model(
    name="MyExampleModel",
    model_class=MyExampleModel,
    is_classifier=False,  # Update if your model is for classification
    save_function=save_function,
    load_function=load_function,
    train_function=train_function,
    predict_function=predict_function,
    changeable_parameters=changeable_params,
    unchangeable_parameters=unchangeable_params,
)
