---
title: "Install the Virtual Hand Interface"
---
The Virtual Hand Interface (VHI) is a separate Godot 4.5 application. It
isn't bundled in the MyoGestic wheel - you download the platform-specific
release binary once and the framework's `virtual_hand()` registry picks
it up automatically.

## TL;DR

```bash
python -m myogestic.tools.install_vhi
# or after `pip install myogestic`:
myogestic-install-vhi
```

That pulls the latest release for your OS/arch, checks the download against
GitHub's per-asset SHA-256 when available, unpacks it atomically into the
location `virtual_hand()` searches, and prints a success summary. If the
digest is unavailable, it warns and continues without an integrity check.

!!! warning "MyoGestic 2.x needs VHI 2.0 or newer"
    MyoGestic drives VHI over the v2 control contract: it asks VHI which
    controls it exports and refuses to guess. A pre-2.0 build has no manifest to
    answer with, and the v1 bridge that used to cover for that was removed — so an
    older release is not limited, it does not work.

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

## What gets installed where

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

**Intel Macs are not supported by the binary.** Rosetta translates
x86_64 → arm64, not the reverse, so the released arm64 build cannot run
on Intel. Either use a different machine, or run from the Godot source
project (see "Source-mode" below).

## Pin a version for reproducibility

`latest` is convenient for a fresh checkout. In production - anything
that needs to behave the same months from now - pin the tag:

```bash
uv run python -m myogestic.tools.install_vhi --tag v2.1.0
```

The installer requests the SHA-256 digest from the GitHub release API
*before* downloading. A missing digest or failed API request does not stop
the download; a digest mismatch refuses the install before unpacking.

`--no-verify` is available but the warning is loud on purpose - use it
only for ad-hoc local builds where no digest exists.

## macOS Gatekeeper

VHI is ad-hoc signed (no Apple Developer ID, no notarisation). Two
launch paths, two different stories:

* **Via MyoGestic's `ProcessLauncher`** - works directly. The launcher
  calls `subprocess.Popen`, which bypasses Gatekeeper / LaunchServices
  entirely. This is the integrated workflow and the one you usually
  want.
* **Via Finder / `open` / double-click** - Gatekeeper blocks the first
  launch. The installer strips the `com.apple.quarantine` xattr after
  unpack, but Finder's first-launch check is separate. Once:

    1. Double-click `VHI.app` - macOS refuses to open it.
    2. **System Settings → Privacy & Security**, scroll to the blocked-app
       notice, click **Open Anyway**.
    3. Subsequent Finder launches succeed.

  (On macOS 14 and earlier, right-click → Open also works.)

The installer prints this same note at the end of every macOS install,
so you don't have to remember it.

## Source-mode (developing VHI itself)

For VHI development - editing the Godot project, not just consuming the
binary - point `$VHI_PATH` at a checkout of the Godot project and set
`$GODOT_BIN`:

```bash
export VHI_PATH=$HOME/code/Virtual-Hand-Interface
export GODOT_BIN=/Applications/Godot.app/Contents/MacOS/Godot   # macOS
# or
export GODOT_BIN=/usr/bin/godot4                                 # Linux

uv run python examples/synthetic/emg_classification.py
```

`virtual_hand()` auto-detects: if `$GODOT_BIN` is set (or `godot_bin=...`
is passed), it launches `godot --path $VHI_PATH` instead of the packaged
binary. Force one or the other with `$VHI_LAUNCH_MODE=binary` or
`=godot`.

## Reinstall / upgrade

```bash
python -m myogestic.tools.install_vhi --force          # latest
uv run python -m myogestic.tools.install_vhi --tag v2.1.0 --force
```

`--force` is required when the destination is non-empty. Without it,
the installer refuses rather than clobbering an unrelated directory.

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
