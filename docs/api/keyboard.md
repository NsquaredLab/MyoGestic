# Keyboard

Press keys when a control is active. The second target this library ships, and the one that
shows the [control standard](controls.md) was not built around a hand.

```toml
[dofs]
close = "vhi.prediction.index"          # a finger
walk  = "keyboard.hold.letter.w"        # held while the control is above 0.5
fire  = "keyboard.tap.edit.space"       # one press per crossing
```

Both targets share one file and one `ControlBus`. Nothing in the map format, the bus or the
core distinguishes a key from a finger.

## Nothing here is new

A key is a **two-state discrete control**, so every part of "press it when the signal goes
over 0.5" already existed:

| what you want | what does it |
|---|---|
| activate above a threshold | a scalar selects the non-rest state of a two-state control |
| choose the threshold | `Capability.activation_threshold`, declared by this target as `0.5` |
| override it per control | `threshold_fraction` on the binding |
| ignore a chattering signal | `debounce_s` on the binding |
| know when it *changed* | `ControlBus` delivers discrete edges, not levels |

That is why this module is small: it maps an edge onto a key press and nothing else.

## Addresses

`keyboard.<mode>.<category>.<key>`, mode first, around 220 of them — every key in both
modes. The dots are what the editor's picker builds its tree from, so the address shape is
also the shape you navigate.

```
keyboard
├─ hold        key down while the control is active
│  ├─ letter   a … z
│  ├─ digit    0 … 9
│  ├─ nav      left, right, up, down, home, end, page_up, page_down
│  ├─ edit     enter, tab, space, escape, backspace, delete, insert
│  ├─ modifier shift, ctrl, alt, cmd
│  ├─ function f1 … f20
│  ├─ numpad   n0 … n9, add, subtract, multiply, divide, decimal
│  ├─ punctuation
│  └─ media
└─ tap         one press-and-release per activation
   └─ (the same categories)
```

`hold` is right for movement — walking, aiming, push-to-talk. `tap` is right for commands,
where one gesture should mean one keystroke however long you hold it.

!!! danger "This types into whatever window has focus"
    A twitchy signal on `keyboard.tap.edit.enter` acts on your terminal. A
    [`KeyboardTarget`][myogestic.keyboard.KeyboardTarget] therefore starts **disarmed** and
    sends nothing until [`arm`][myogestic.keyboard.KeyboardTarget.arm] is called; it disarms
    itself on `stop`, on a backend failure, and when the process exits.

    Prefer `tap` for anything destructive. A held key outlives the process that set it, and
    no teardown runs on `SIGKILL`.

!!! note "Installing, and the macOS permission"
    Needs the `keyboard` extra: `uv sync --extra keyboard`. That is
    [`pynput`](https://pynput.readthedocs.io) — *not* the PyPI package called `keyboard`,
    which needs root on macOS and Linux and is effectively unmaintained.

    On macOS the process also needs **Accessibility** permission, under System Settings ›
    Privacy & Security › Accessibility. Without it `pynput` reports success and nothing
    happens, which is indistinguishable from a broken map — so `arm` says so rather than
    letting you hunt for it.

## Reference

::: myogestic.keyboard.KeyboardTarget

::: myogestic.keyboard.keyboard_capabilities
