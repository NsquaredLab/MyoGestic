"""
=========================================
Part 0: What is a Visual Interface?
=========================================

A **Visual Interface** is a graphical user interface (GUI) that allows us to perform experiments, visualize data, and interact with the models trained in MyoGestic.

Further it is the main way we can communicate to participants what they should do during the experiment and what they can control.

For example, the :ref:`virtual_hand_interface` is a Visual Interface that allows users to visualize their hand movements in real-time despite neural lesions or amputations.
It is designed to have as little visual clutter as possible to avoid overwhelming the user with information. Two virtual hands are displayed on the screen, one that represents the user's hand and another that represents the target hand.

Technical Considerations (Probably why you are here):
------------------------------------------------------
.. important::
   A Visual Interface is generally intended to be a standalone program that can communicate (both receiving and sending) through information exchange protocols (e.g., UDP).
   This way the interface is a standalone process that will not be hindered by MyoGestic's runtime.

   **If you have not already, please create your standalone visual interface before proceeding.**


To integrate a new Visual Interface in MyoGestic you must add three components:

1. **Setup Interface**: Configures the parameters and initializes the system (e.g. hardware, data pipeline).
2. **Recording Interface**: Manages runtime interactions and data visualization.
3. **Output Interface**: Defines how results are presented (e.g., virtual hands, plots).

"""