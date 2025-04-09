.. |logo| image:: _static/myogestic_logo.png
   :height: 80px
   :align: middle

Welcome to |logo|
==========================================
**Why start myocontrol research from zero?**

MyoGestic is a software framework designed to help the myocontrol community develop and test new myocontrol algorithms. For researchers and clinicians working with individuals with neural lesions, MyoGestic streamlines the process of creating, implementing, and evaluating myoelectric control systems.

The framework is designed with two primary goals:

1. **Easy extensibility**: Add your own algorithms without extensive knowledge of the codebase
2. **Minimal setup time**: Especially important when working with clinical populations where time is limited

Usage Examples
--------------
Get a quick glimpse of MyoGestic in action through our video demos:

.. raw:: html

   <div style="display: flex; justify-content: space-around; flex-wrap: wrap;">

.. youtube:: NPemwlSg-mE
   :align: center
   :width: 30%

.. youtube:: 3BvVAu8Nq8c
   :align: center
   :width: 30%

.. youtube:: zxICSVn-3P8
   :align: center
   :width: 30%

.. raw:: html

   </div>

Key Features
------------
- **Rapid Prototyping & Testing**: User-friendly interface, minimal setup, and efficient clinical testing workflows.
- **Real-time Performance**: Low-latency signal processing and control visualization.
- **Hardware Agnostic**: Supports various EMG acquisition devices.
- **Extensible & Customizable**: Easily incorporate new sensors, algorithms, or device interfaces.
- **Data Logging**: Capture and analyze performance metrics.
- **Community-Driven**: Built for collaboration and knowledge sharing.


.. note::
   MyoGestic is actively developed at the `n-squared lab <https://www.nsquared.tf.fau.de/>`_ at Friedrich-Alexander-Universität Erlangen-Nürnberg (FAU) by our dedicated team of PhD candidates, along with the Bachelor and Master students they supervise.

   As development is closely tied to ongoing research and academic timelines, major updates often align with the completion of student theses.
   While we strive to incorporate improvements regularly, much of the cutting-edge development remains internal until research milestones are reached.

   We appreciate your understanding and interest in the project!

Package Structure
-----------------
.. code-block:: text

   MyoGestic/
   ├── myogestic/           # Main package source code
   │   ├── data/            # Default data/configurations used by the package
   │   ├── gui/             # Graphical User Interface components
   │   ├── models/          # Myocontrol algorithm models and interfaces
   │   │   ├── core/        # Core model implementations (assuming this still exists)
   │   │   └── definitions/ # Model definitions and specifications (assuming this still exists)
   │   ├── utils/           # Helper functions and utilities
   │   ├── main.py          # Main application entry point
   │   ├── default_config.py # Default configuration settings
   │   └── user_config.py   # User-specific configuration
   ├── docs/                # Documentation source files
   ├── examples/            # Example usage scripts and notebooks
   ├── tests/               # Automated tests
   ├── pyproject.toml       # Project metadata, dependencies, and build configuration
   └── uv.lock              # Pinned versions of dependencies managed by uv

.. toctree::
   :maxdepth: 2
   :caption: Get Started:
   :hidden:

   Examples <auto_examples/index.rst>

.. toctree::
   :maxdepth: 1
   :caption: API:
   :hidden:

   api_documentation.rst

Tutorial
--------
Explore the fundamentals in our comprehensive tutorial:

.. raw:: html

   <div style="text-align: center; margin-bottom: 1em;">
       <object data="_static/MyoGestic_Tutorial.pdf#view=Fit#toolbar=0#statusbar=0#navpanes=0" type="application/pdf" width="960" height="540">
           <p>Your browser does not support PDFs. <a href="_static/MyoGestic_Tutorial.pdf">Download the PDF</a>.</p>
       </object>
   </div>

Or download it for offline use: :download:`Download the PDF <_static/MyoGestic_Tutorial.pdf>`

How to Cite
-----------
If you use MyoGestic in your research, please cite the following paper:

.. code-block:: bibtex

    @article{
        Sîmpetru2025,
        author = {Raul C. Sîmpetru  and Dominik I. Braun  and Arndt U. Simon  and Michael März  and Vlad Cnejevici  and Daniela Souza de Oliveira  and Nico Weber  and Jonas Walter  and Jörg Franke  and Daniel Höglinger  and Cosima Prahm  and Matthias Ponfick  and Alessandro Del Vecchio },
        title = {MyoGestic: EMG interfacing framework for decoding multiple spared motor dimensions in individuals with neural lesions},
        journal = {Science Advances},
        volume = {11},
        number = {15},
        pages = {eads9150},
        year = {2025},
        doi = {10.1126/sciadv.ads9150},
        URL = {https://www.science.org/doi/abs/10.1126/sciadv.ads9150},
        eprint = {https://www.science.org/doi/pdf/10.1126/sciadv.ads9150},
    }

License
-------
MyoGestic is licensed under the `GNU General Public License v3.0 <https://github.com/NsquaredLab/MyoGestic/blob/main/LICENSE>`_ (GPL-3.0).

Stay tuned for more tutorials, tips, and community showcases as we continue to grow MyoGestic!