# Getting Started with MyoGestic

MyoGestic: A software framework for developing and testing myocontrol algorithms with minimal setup time.

```{tip}
Take a look at our [documentation](https://nsquaredlab.github.io/MyoGestic/).
```


## Table of Contents
- [Introduction](#introduction)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [How to Use](#how-to-use)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [How to Cite](#how-to-cite)

## Introduction

MyoGestic is a software framework designed to help the myocontrol community develop and test new myocontrol algorithms. For researchers and clinicians working with individuals with neural lesions, MyoGestic streamlines the process of creating, implementing, and evaluating myoelectric control systems.

The framework is designed with two primary goals:
1. **Easy extensibility**: Add your own algorithms without extensive knowledge of the codebase
2. **Minimal setup time**: Especially important when working with clinical populations where time is limited

## Features

- **User-friendly interface**: Simple setup for clinical testing
- **Real-time processing**: Low-latency signal processing and control
- **Multiple device support**: Works with various EMG acquisition hardware
- **Customizable algorithms**: Implement your own control strategies
- **Data logging**: Capture and analyze performance metrics
- **Visualization tools**: Monitor signals and control outputs in real-time

## Requirements

- Windows 10 or later (for installer)
- Any OS supported by Python for manual installation (for maximum performance consider using Ubuntu 24.10)
- Python 3.12 or higher
- Compatible EMG acquisition hardware

## Installation
```{important}
The simplest way is to install MyoGestic using the installer. You can download the installer from the [releases page](https://github.com/NsquaredLab/MyoGestic/releases).
```


```{note}
The installer is only available for Windows. If you are using another operating system, you can follow the manual installation instructions.
```


```{note}
This does not allow you to add your own myocontrol algorithms. This is only for using the existing ones.
```



### Manual installation
The installation is made using uv. You can install it following the instructions at [https://github.com/astral-sh/uv](https://github.com/astral-sh/uv).

Then, you can install MyoGestic using the following command:
```bash
uv sync
```

## How to Use
[![MyoGestic Tutorial](https://img.youtube.com/vi/Re3VfgKhjCM/maxresdefault.jpg)](https://youtu.be/Re3VfgKhjCM)

If you prefer a PDF version, you can download it [here](
https://github.com/NsquaredLab/MyoGestic/tree/main/docs/source/_static/MyoGestic_Tutorial.pdf).

### Quick Start Guide

1. Install MyoGestic using one of the methods described above
2. Connect your EMG acquisition hardware
3. Launch the application
4. Select the desired algorithm and parameters
5. Begin recording and testing

## Development

If you want to contribute to the project, you can install the development dependencies using the following command:
```bash
uv sync --group dev --group docs
```

### Project Structure

```
MyoGestic/
├── myogestic/           # Main package
│   ├── models/          # Algorithm models and interfaces
│   │   ├── core/        # Core model implementations
│   │   └── definitions/ # Model definitions and specifications
│   ├── gui/             # User interface components
│   ├── utils/           # Helper functions and utilities
│   ├── main.py          # Application entry point
│   └── default_config.py # Default configuration settings
├── docs/                # Documentation
├── tests/               # Test suite
├── examples/            # Example usage and demonstrations
├── setup/               # Installation and setup files
└── pyproject.toml       # Project metadata and dependencies
```

### Adding Your Own Algorithm

To add a new algorithm:

1. Create a custom model class with the required methods:
   - `save`: Save model state to a file
   - `load`: Load model state from a file
   - `train`: Train the model on input data
   - `predict`: Make predictions with the model

2. Define the required lifecycle functions:
   - `save_function`: Function to save the model
   - `load_function`: Function to load the model
   - `train_function`: Function to train the model
   - `predict_function`: Function to make predictions

3. Define parameter configurations:
   - `changeable_parameters`: Parameters that can be modified through the UI
   - `unchangeable_parameters`: Parameters that remain fixed

4. Register your model in the `CONFIG_REGISTRY` in `user_config.py`

Example implementation can be found in `examples/01_add_functionality/2_add_model.py`.

Refer to the [documentation](https://nsquaredlab.github.io/MyoGestic/) for detailed instructions on implementing custom algorithms.

## Troubleshooting

### Common Issues

- **Hardware not detected**: Ensure your EMG device is properly connected and drivers are installed
- **Algorithm fails to load**: Check for missing dependencies or syntax errors in your implementation
- **Performance issues**: Consider optimizing your algorithm or checking system resources

For more detailed troubleshooting, please refer to the [documentation](https://nsquaredlab.github.io/MyoGestic/).

## How to Cite
If you use MyoGestic in your research, please cite the following paper:
```bibtex
TBD
```

## License

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
