# Getting Started with MyoGestic

MyoGestic is a software framework made to help the myocontrol community to develop and test new myocontrol algorithms.
It is made to be easily extensible and to minimize dead time when testing on injured individuals.

## Installation
> [!IMPORTANT]
> The simplest way is to install MyoGestic using the installer. You can download the installer from the [releases page](https://github.com/NsquaredLab/MyoGestic/releases).

> [!NOTE]
> The installer is only available for Windows. If you are using another operating system, you can follow the manual installation instructions.

> [!NOTE]  
> This does not allow you to add your own myocontrol algorithms. This is only for using the existing ones.

### Manual installation
The installation is made using Poetry. You can install it using the following command:
```bash
pip install poetry
```

Then, you can install the dependencies using the following command:
```bash
poetry install
```

## How to use
> [!TIP]
> You can find a more detailed explanation in the [documentation](https://nsquaredlab.github.io/MyoGestic/).

[![MyoGestic Tutorial](https://img.youtube.com/vi/Re3VfgKhjCM/maxresdefault.jpg)](https://youtu.be/Re3VfgKhjCM)

## Development installation
If you want to contribute to the project, you can install the development dependencies using the following command:
```bash
poetry install --with dev,docs
```

Then you need to install the development version of the submodule `device_interface` using the following command:
```bash
poetry run poe install-dev
```

## How to cite
If you use MyoGestic in your research, please cite the following paper:
```bibtex
TBD
```
