import PyInstaller.__main__
import shutil
import os
import sys
import vispy
import vispy.glsl
import vispy.io
import distributed

# Collect data files
data_files = [
    (os.path.dirname(vispy.glsl.__file__), os.path.join("vispy", "glsl")),
    (
        os.path.join(os.path.dirname(vispy.io.__file__), "_data"),
        os.path.join("vispy", "io", "_data"),
    ),
    (os.path.join(os.path.dirname(distributed.__file__)), "distributed"),
]

data_file1 = os.path.dirname(vispy.glsl.__file__)
data_file1_sec = os.path.join("vispy", "glsl")
data_file2 = os.path.join(os.path.dirname(vispy.io.__file__), "_data")
data_file2_sec = os.path.join("vispy", "io", "_data")
data_file3 = os.path.join(os.path.dirname(distributed.__file__))
data_file3_sec = "distributed"


def compile():
    # Define the base path relative to the script's location
    base_path = os.path.dirname(os.path.abspath(__file__))
    # Paths to Unity executables for each OS
    unity_executables = [
        (
            os.path.join(
                base_path, "myogestic", "dist", "windows", "Virtual Hand Interface.exe"
            ),
            "windows/Virtual Hand Interface.exe",
        ),
        (
            os.path.join(
                base_path, "myogestic", "dist", "macOS", "Virtual Hand Interface.app"
            ),
            "macOS/Virtual Hand Interface.app",
        ),
        (
            os.path.join(
                base_path, "myogestic", "dist", "linux", "VirtualHandInterface.x86_64"
            ),
            "linux/VirtualHandInterface.x86_64",
        ),
    ]

    # Windows
    unity_folder = os.path.join(base_path, "myogestic", "dist")
    # Base PyInstaller arguments
    pyinstaller_args = [
        os.path.join(base_path, "myogestic", "main.py"),
        "--onefile",
        "--windowed",  # use --windowed instead of --window
        r"--specpath=bin",
        r"--distpath=bin\dist",
        r"--workpath=bin\build",
        "--name=MyoGestic",
        # "--icon=videoIcon.ico",
        f"--add-data={data_file1};{data_file1_sec}",
        f"--add-data={data_file2};{data_file2_sec}",
        f"--add-data={data_file3};{data_file3_sec}",
        "--hidden-import=vispy.ext._bundled.six",
        "--hidden-import=vispy.app.backends._pyside6",
        f"--add-data={unity_folder};dist",
    ]

    # Add Unity executables to the PyInstaller arguments
    # for exe_src, exe_dst in unity_executables:
    #     pyinstaller_args.append(f"--add-binary={exe_src};{exe_dst}")

    # Run PyInstaller with the constructed arguments
    PyInstaller.__main__.run_monitoring(pyinstaller_args)


if __name__ == "__main__":
    compile()
