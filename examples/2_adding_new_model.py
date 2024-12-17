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

# print configuration file
with open("../myogestic/user_config.py", "r") as f:
    print(f.read())

# %%
# Create a new model
# ------------------
# Let's add a new model to MyoGestic.
#
# .. tip:: While we encourage you to add a new model in `user_config.py`, you can also add it in a separate file and import it in `user_config.py`.
#
# Our model is going to be a Logistic Regression model. We are going to use the `LogisticRegression` class from sklearn.
#

from sklearn.linear_model import LogisticRegression


# %%
# Add functions to save, load, train, and predict
# ------------------------------------------------
# We can use the `sklearn_models` functions that are already defined in the `myogestic.models.definitions` module.
# These should work for most models that are based on sklearn models.
#

from myogestic.models.definitions import sklearn_models
import inspect

print(inspect.getsource(sklearn_models.save))
print("".join(["-"] * 80))
print(inspect.getsource(sklearn_models.load))
print("".join(["-"] * 80))
print(inspect.getsource(sklearn_models.train))
print("".join(["-"] * 80))
print(inspect.getsource(sklearn_models.predict))

# %%
# Add parameters for the model
# ----------------------------
# Finally, we need to define the parameters that the model needs.
#
# .. note:: The parameters should be divided into `changeable` and `unchangeable` parameters. The `changeable` parameters are the ones that the user can change in the GUI. The `unchangeable` parameters are the ones that the user cannot change and are set by the system.
#
#
# For our model, we are going to allow 'C' to be a changeable parameters and 'penalty' to be an unchangeable parameter.
#

# The `ChangeableParameter` and `UnchangeableParameter` classes are used to define the parameters.
changeable_parameters = {
    "C": {"start_value": 1e-4, "end_value": 1e4, "step": 1e-4, "default_value": 1}
}

unchangeable_parameters = {"penalty": "l2"}

# %%
# Register the model
# ------------------
# We can now register the model in the configuration registry.
#
# .. note:: The register_model function is used to add a new model to MyoGestic.
#
# The function takes the following arguments:
#     - model_name: The name of the model.
#     - model_class: The python class of the model. Example: LinearRegression from sklearn.
#     - is_classifier: A boolean indicating whether the model is a classifier.
#     - save_function: The function to save the model.
#     - load_function: The function to load the model.
#     - train_function: The function to train the model.
#     - predict_function: The function to predict with the model.
#
# .. important:: The model_name must be unique.
#

from myogestic.utils.config import CONFIG_REGISTRY

CONFIG_REGISTRY.register_model(
    model_name="Logistic Regression",
    model_class=LogisticRegression,
    is_classifier=True,
    save_function=sklearn_models.save,
    load_function=sklearn_models.load,
    train_function=sklearn_models.train,
    predict_function=sklearn_models.predict,
    changeable_parameters=changeable_parameters,
    unchangeable_parameters=unchangeable_parameters,
)
