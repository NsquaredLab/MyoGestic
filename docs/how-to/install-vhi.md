---
title: "Install the Virtual Hand Interface"
---
The Virtual Hand Interface (VHI) is a separate Godot 4.5 application.
Download its platform-specific release binary for `virtual_hand()` to find it.

## TL;DR

```bash
python -m myogestic.tools.install_vhi
# or after `pip install myogestic`:
myogestic-install-vhi
```

That pulls the latest release for your OS/arch, checks the download against
GitHub's per-asset SHA-256 when available, prepares it beside the location
`virtual_hand()` searches, then puts it in place with directory renames and
prints a success summary. If the digest is unavailable, it warns and continues
without an integrity check.

!!! warning "MyoGestic 2.x needs VHI 2.0 or newer"
    MyoGestic queries VHI's manifest through the v2 control contract.
    Pre-2.0 builds lack this manifest and cannot work with MyoGestic 2.x.

    Both the installer and the launcher check. `install_vhi` checks the requested
    tag and resolves `latest` before downloading when the API is reachable. It refuses
    known versions below 2.0 and warns if `latest` cannot be resolved.
    `virtual_hand().launcher()` reads `vhi-version.txt` and refuses to start a
    pre-2.0 install. The launcher permits an install with no marker, since a source-mode
    checkout has none.

    Until a 2.x release is published, run a checkout from source:

    ```bash
    export VHI_PATH=/path/to/Virtual-Hand-Interface
    export GODOT_BIN=/path/to/godot          # Godot 4.x with .NET support
    ```

## Install locations

The default install root mirrors what `virtual_hand()` looks at:

| Context                                                | Install root                                                              |
|--------------------------------------------------------|---------------------------------------------------------------------------|
| Writable git checkout (`MyoGestic/.git` exists)        | `<repo>/tools/MyoGestic-VHI` - visible next to source, gitignored.        |
| Anywhere else (`pip install`, read-only checkouts)     | `<platformdirs.user_data_dir("myogestic")>/vhi`.                          |

Override the installer destination with `--dest /custom/path`. Set
`VHI_PATH=/custom/path` as well so `virtual_hand()` finds that install;
the installer does not read `$VHI_PATH`.

Inside the install root you get:

* `VHI.app` (macOS), `VHI.exe` (Windows), or `VHI.x86_64` (Linux) - the
  Godot-built binary the framework launches.
* `vhi-version.txt` - install marker recording tag, asset name, platform.
  The launcher reads its tag to check compatibility. Replacing a non-empty
  install requires `--force`.

## Platform support

The release matrix:

| OS       | Arch   | Asset                       | Notes                                       |
|----------|--------|-----------------------------|---------------------------------------------|
| macOS    | arm64  | `VHI-macos-arm64.zip`       | Apple Silicon only - see Rosetta note below.|
| Linux    | x86_64 | `VHI-linux-x64.tar.gz`      | No aarch64 build.                            |
| Windows  | x64    | `VHI-windows-x64.zip`       |                                              |

On Intel Macs, run the Godot source project under "Source-mode" below.
The released binary requires arm64; Rosetta translates x86_64 → arm64
and cannot run it on Intel.

## Pin a version for reproducibility

Pin the tag for reproducible installs:

```bash
uv run python -m myogestic.tools.install_vhi --tag v2.1.0
```

The installer requests the SHA-256 digest from the GitHub release API
*before* downloading. A missing digest or failed API request does not stop
the download; a digest mismatch refuses the install before unpacking.

`--no-verify` skips both the digest lookup and the SHA-256 check. It prints
a warning to stderr before downloading that the archive will not be
integrity-checked. Use it only for ad-hoc local builds where no digest exists.

## macOS Gatekeeper

VHI is ad-hoc signed without Apple Developer ID or notarization.
Launch method determines Gatekeeper behaviour:

* Via MyoGestic's `ProcessLauncher` - works directly. The launcher
  calls `subprocess.Popen`, which bypasses Gatekeeper / LaunchServices
  entirely.
* Via Finder / `open` / double-click - Gatekeeper blocks the first
  launch. The installer strips the `com.apple.quarantine` xattr after
  unpack, but Finder's first-launch check is separate. Once:

    1. Double-click `VHI.app` - macOS refuses to open it.
    2. System Settings → Privacy & Security, scroll to the blocked-app
       notice, click Open Anyway.
    3. Subsequent Finder launches succeed.

  On macOS 14 and earlier, right-click → Open also works.

The installer prints these instructions after each macOS install.

## Source-mode (developing VHI itself)

To edit VHI, point `$VHI_PATH` at a Godot project checkout and set
`$GODOT_BIN`:

```bash
export VHI_PATH=$HOME/code/Virtual-Hand-Interface
export GODOT_BIN=/Applications/Godot.app/Contents/MacOS/Godot   # macOS
# or
export GODOT_BIN=/usr/bin/godot4                                 # Linux

uv run python examples/synthetic/emg_classification.py
```

With `$GODOT_BIN` set or `godot_bin=...` passed,
`virtual_hand()` launches `godot --path $VHI_PATH` instead of the packaged
binary. Force one or the other with `$VHI_LAUNCH_MODE=binary` or
`=godot`.

## Reinstall / upgrade

```bash
python -m myogestic.tools.install_vhi --force          # latest
uv run python -m myogestic.tools.install_vhi --tag v2.1.0 --force
```

`--force` is required when the destination is non-empty. Without it,
the installer leaves the destination untouched.

The installer downloads and prepares the replacement in a temporary directory
beside the destination, on the same filesystem. Unpacking, validation, executable
permissions, the version marker and macOS quarantine removal all finish before
the current install is touched. It then renames the current install aside and
renames the prepared directory into place; there is a brief gap between those
two renames, so close VHI before upgrading.

If the replacement rename fails, the installer renames the previous install
back. If that restoration also fails, it keeps the previous install in its
backup directory and prints the path to stderr. It never copies a partially
prepared replacement into the destination. After a successful swap, failure to
remove the temporary directory prints a warning and leaves the new install usable.

## Uninstall

The installer doesn't ship an `uninstall` subcommand because the install
is a single directory. Delete it:

```bash
# Find where VHI was installed:
python -c "from myogestic.vhi.interfaces import _default_install_root; print(_default_install_root())"

# Then remove it:
rm -rf "$(python -c 'from myogestic.vhi.interfaces import _default_install_root; print(_default_install_root())')"
```

`virtual_hand()` will then raise its standard "not installed" error on
the next `launcher()` call, pointing you back at `install_vhi`.

## See also

* [Integrate the Virtual Hand](integrate-vhi.md) - wiring VHI into a
  MyoGestic app once installed.
* [`myogestic.tools.install_vhi`](../api/core.md) - installer module API.
