# Force ramps on Windows — from nothing to a recorded session

A step-by-step guide that assumes no programming, written for a
Sessantaquattro+ with a force transducer. The first run takes about
15 minutes, almost all of it automatic downloading; every run after that
starts in seconds. No amplifier to hand? The last section runs the same
task against a simulated sensor.

## 1. Install uv (once)

uv is the tool that fetches Python and everything MyoGestic needs. You never
have to install Python yourself.

1. Press the **Windows key**, type `powershell`, press Enter. A blue window
   opens.
2. Paste the line below (right-click pastes in PowerShell) and press Enter:

   ```powershell
   irm https://astral.sh/uv/install.ps1 | iex
   ```

3. When it says it is done, **close the window**. Only a freshly opened
   window knows about uv.

## 2. Get MyoGestic (once)

1. Go to <https://github.com/NsquaredLab/MyoGestic>.
2. Press the green **Code** button, then **Download ZIP**.
3. Right-click the downloaded ZIP → **Extract All…** → put it somewhere easy,
   like the Desktop. You now have a folder called `MyoGestic-main`.

## 3. Start the app

1. Open a new PowerShell window (Windows key → `powershell` → Enter).
2. Type `cd ` (with a space), then **drag the `MyoGestic-main` folder onto
   the window** — the path fills itself in. Press Enter.
3. Run:

   ```powershell
   uv run python examples/start_here/force_ramps.py
   ```

The first run prints a lot of text while it downloads Python and the
packages — let it finish. The app window then opens on its own.

## 4. Connect the Sessantaquattro+

Plug the force transducer into the **AUX input** of the Sessantaquattro+ and
put the EMG electrodes on as usual. Then:

1. Power the device on. In the Windows Wi-Fi menu (bottom-right corner),
   join the device's own Wi-Fi network. It has no internet — that is normal;
   if Windows offers to switch you back to another network, say no.
2. In the app's right-hand column, on the **Source** tab, the dropdown at
   the very top says which stream you are setting up — leave it on **emg**.
3. In the device list, pick **Sessantaquattro / +**. (The ⓘ button next to
   it repeats these connection steps.)
4. In the settings that appear, leave Channels and Sample rate alone, but
   switch **AUX + IMU + counters** to **On** — the force sensor arrives on
   those AUX channels, so with this Off the task has nothing to read.
5. Press **Connect**. The device dials in to the PC, which can take a few
   seconds. If Windows pops up a firewall question about Python, click
   **Allow access** — blocking it means the device can never reach the app.

The Signal tab on the left now shows live EMG.

## 5. Point the force task at the sensor

On the left side, switch to the **Force** tab:

1. In its stream dropdown, pick **emg** — the force channel travels inside
   the same stream as the EMG.
2. In the channel dropdown, pick **aux0**. That is the AUX socket the
   transducer is plugged into.

## 6. Calibrate

The task needs to learn what your "relaxed" and your "as hard as you can"
look like:

1. Relax completely, then press **Capture** in the **Zero** row.
2. Push on the transducer as hard as you can and press **Capture** in the
   **MVC** row. It watches for your peak for about 3 seconds — keep pushing
   until the countdown ends, then relax. (MVC = maximum voluntary
   contraction, your personal 100%.)

The status line changes to **ready**. Until both captures are done, the
**Start** button stays greyed out — hovering it tells you what is missing.

## 7. Record a block

1. In the right-hand column, press **Record**.
2. On the Force tab, press **Start**. A target line rises, holds, and falls —
   push on the transducer so that your trace follows it. The block ends by
   itself when the target comes back down to zero.
3. Press **Stop** on the recorder, then **Save**.

The session appears in the panel at the bottom right, and the data is saved
in a `sessions` folder inside `MyoGestic-main`.

## No amplifier to hand?

The same task runs against a built-in simulated sensor, where you "push" by
dragging a slider. On the **Source** tab set the top dropdown to **force**,
pick **Synthetic force (no hardware)**, press **Connect**, and on the Force
tab set the stream dropdown to **force**. From there everything above is the
same, with the **Effort** slider as your muscle.

## If something goes wrong

- **"uv is not recognized"** — the PowerShell window is older than the uv
  install. Close it and open a new one.
- **Red text during the first run** — almost always the network. Run the
  same command again; it continues where it stopped.
- **Connect waits and then gives up** — check the Wi-Fi menu: Windows likes
  to hop back to a network that has internet. You must be on the device's
  own network the whole time.
- **Start is greyed out** — hover it; the tooltip names the missing step
  (usually the Zero or MVC capture).
