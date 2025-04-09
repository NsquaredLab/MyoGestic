<img src="./docs/source/_static/myogestic_logo.png" height="250">

<a href="https://www.python.org/downloads/release/python-3100/"><img alt="Code style: black" src="https://img.shields.io/badge/python-%3E=3.10,%20%3C=3.13-blue"></a>

> [!TIP]
> Dive deeper into our features and usage with the official [documentation](https://nsquaredlab.github.io/MyoGestic/).

# MyoGestic - Why start myocontrol research from zero?

## What is MyoGestic?
MyoGestic is a software framework designed to help the myocontrol community develop and test new myocontrol algorithms. For researchers and clinicians working with individuals with neural lesions, MyoGestic streamlines the process of creating, implementing, and evaluating myoelectric control systems.

The framework is designed with two primary goals:
1. **Easy extensibility**: Add your own algorithms without extensive knowledge of the codebase
2. **Minimal setup time**: Especially important when working with clinical populations where time is limited

Key features include:
- **User-friendly interface**: Simple setup for clinical testing
- **Real-time processing**: Low-latency signal processing and control
- **Multiple device support**: Works with various EMG acquisition hardware
- **Customizable algorithms**: Implement your own control strategies
- **Data logging**: Capture and analyze performance metrics
- **Visualization tools**: Monitor signals and control outputs in real-time

> [!NOTE]  
> MyoGestic is actively developed at the [n-squared lab](https://www.nsquared.tf.fau.de/) at Friedrich-Alexander-Universität Erlangen-Nürnberg (FAU) by our dedicated team of PhD candidates, along with the Bachelor and Master students they supervise. 
>
> As development is closely tied to ongoing research and academic timelines, major updates often align with the completion of student theses. 
> While we strive to incorporate improvements regularly, much of the cutting-edge development remains internal until research milestones are reached. 
> 
> We appreciate your understanding and interest in the project!

## Requirements

- Windows 10 or later (for installer)
- Any OS supported by Python for manual installation (for maximum performance consider using Ubuntu 24.10)
- Python 3.12 or higher
- Compatible EMG acquisition hardware

## Installation

### Using `uv` - the preferred way

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/NsquaredLab/MyoGestic.git
    cd MyoGestic
    ```

2.  **Install uv:** If you don't have it yet, install `uv`. Follow the instructions on the [uv GitHub page](https://github.com/astral-sh/uv).

3.  **Set up Virtual Environment & Install Dependencies:** Use `uv` to create and sync your virtual environment with the project's dependencies.
    ```bash
    # Install base dependencies
    uv sync

    # To contribute or run documentation/examples, install optional groups:
    uv sync --group dev --group docs
    ```

### Using the Installer

> [!WARNING]  
> The installer is for a very old version of MyoGestic. 
> Until we find a better and/or reliable way of creating an executable we highly recommend using `uv`.

> 📝 **Note**: The installer is only available for Windows. If you are using another operating system, please follow the developer installation instructions below.

> 📝 **Note**: Using the installer does not allow you to add your own myocontrol algorithms. This is only for using the existing ones.

## How to Use / Tutorial

### Quick Start Guide

1. Install MyoGestic using one of the methods described above
2. Connect your EMG acquisition hardware
3. Launch the application: `python -m myogestic.main` (or use the installed executable if using the installer)
4. Select the desired algorithm and parameters
5. Begin recording and testing

### Video tutorial

[![MyoGestic Tutorial](https://img.youtube.com/vi/Re3VfgKhjCM/maxresdefault.jpg)](https://youtu.be/Re3VfgKhjCM)

If you prefer a PDF version, you can download it [here](
https://github.com/NsquaredLab/MyoGestic/tree/main/docs/source/_static/MyoGestic_Tutorial.pdf).

## Development

### What is what?

```
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
```

# How to Cite
If you use MyoGestic in your research, please cite the following [paper](https://www.science.org/doi/abs/10.1126/sciadv.ads9150):

```bibtex
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
```

# License
MyoGestic is licensed under the [GNU General Public License v3.0](LICENSE) (GPL-3.0).

This means you are free to:
- Use the software for any purpose
- Change the software to suit your needs
- Share the software with others
- Share the changes you make

Under the following conditions:
- You must disclose your source code when you share the software
- You must license any derivative work under the same or a compatible license
- You must state changes made to the software
- You must include the license and copyright notice with the software

This is a simplified explanation. For the full license text, see the [LICENSE](LICENSE) file or visit [GNU GPL v3](https://www.gnu.org/licenses/gpl-3.0.html).
