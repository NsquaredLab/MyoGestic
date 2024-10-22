"""
Adding a new model to MyoGestic
================================

This example shows how to add a new model to MyoGestic.
"""

# %%
# MyoGestic makes use of a configuration file to define the models that are available to the user in the GUI.
#
# For ease of use, we have provided a template configuration file that you can use to add your own models
# `myogestic/user_config.py`.
#
# This file contains 3 dictionaries (see :ref:`models_config` for more details):
#
# - `MODELS_MAP`: a dictionary where the keys are the model names and the values are a tuple containing the model class and whether the model is a classifier or not.
# - `FUNCTIONS_MAP`: a dictionary where the keys are the model names and the values are a tuple containing the function to save, load, and train the model.
# - `PARAMETERS_MAP`: a dictionary where the keys are the model names and the values are a dictionary containing the parameters that the model needs. This dictionary is used to create the GUI for the model in the MyoGestic interface.

# print configuration file
with open("../myogestic/user_config.py", "r") as f:
    print(f.read())

# %%
# Create a new model
# ------------------
# Let's add a new model to MyoGestic.
#
# .. tip:: While we encourage you to add a new model in a separate file than the `user_config.py`, you can add it directly to the user_config.py file if you prefer since all that matters is that the model class you make ends up in the `MODELS_MAP` dictionary.
#
# .. note:: The model class should be able to recieve keyword arguments that are passed from the GUI. Also the model should have a function to save, load, train, and predict.
#
# Our model is going to be a per finger regressor using the `CatBoostRegressor` from the `catboost` library.
#
# .. important:: Each model should have an unique name that is consistent across the `MODELS_MAP`, `FUNCTIONS_MAP`, and `PARAMETERS_MAP` dictionaries. This name will be displayed in the GUI.

from sklearn.multioutput import MultiOutputRegressor
from catboost import CatBoostRegressor

# for such a model. we do not need to define a new class. We can use a lambda function to create the model.
my_new_model = lambda **params: MultiOutputRegressor(CatBoostRegressor(**params))

# Add the model to the MODELS_MAP dictionary
MODELS_MAP = {
    "My New Model": (
        my_new_model,
        False,  # False because it is *not* a classifier
    ),
}

# %%
# Add functions to save, load, and train the model
# ------------------------------------------------
# Next, we need to define the functions to save, load, and train the model.
#
# .. note:: The save and load functions should take the model and a file path as arguments. The train function should take the model, the training data, the training ground truth, and a logger as arguments. See :ref:`sklearn_models` for more details.
#
# We can use the `sklearn_models` functions that are already defined in the `myogestic.models.definitions` module.

from myogestic.models.definitions import sklearn_models

# Add the functions to the FUNCTIONS_MAP dictionary
FUNCTIONS_MAP = {
    "My New Model": {
        "save_function": sklearn_models.save,
        "load_function": sklearn_models.load,
        "train_function": sklearn_models.train,
    },
}

# %%
# Add parameters for the model
# ----------------------------
# Finally, we need to define the parameters that the model needs.
#
# .. note:: The parameters should be divided into `changeable` and `unchangeable` parameters. The `changeable` parameters are the ones that the user can change in the GUI. The `unchangeable` parameters are the ones that the user cannot change and are set by the system.
#
# .. important:: Changeable parameters are dictionaries where the keys are predefined depending on the type of parameter. See :ref:`models_config` for details. The keys are self-explanatory.
#
# .. important:: Unchangeable parameters are just key-value pairs.
#
# For our model, we are going to define the following changeable parameters:
#
# - `iterations`: the number of iterations for the CatBoostRegressor.
# - `l2_leaf_reg`: the L2 regularization parameter for the CatBoostRegressor.
# - `border_count`: the number of splits for numerical features for the CatBoostRegressor.
#
# We are also going to define the following unchangeable parameters:
#
# - `task_type`: the task type for the CatBoostRegressor. We are going to set it to "GPU" if there is a GPU available, otherwise we are going to set it to "CPU".
# - `train_dir`: the directory where the model is saved. This is set to `None` since the model should be saved using our function and not directly by the library.

from catboost.utils import get_gpu_device_count

# Add the parameters to the PARAMETERS_MAP dictionary
PARAMETERS_MAP = {
    "My New Model": {
        "changeable": {
            "iterations": {
                "start_value": 10,
                "end_value": 1000,
                "step": 10,
                "default_value": 100,
            },
            "l2_leaf_reg": {
                "start_value": 1,
                "end_value": 10,
                "step": 1,
                "default_value": 5,
            },
            "border_count": {
                "start_value": 1,
                "end_value": 255,
                "step": 1,
                "default_value": 128,
            },
        },
        "unchangeable": {
            "task_type": "GPU" if get_gpu_device_count() > 0 else "CPU",
            "train_dir": None,
        },
    },
}
