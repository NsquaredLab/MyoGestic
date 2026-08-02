# Outlets

An `Outlet` owns a `.push(data)` method plus a daemon thread that sends the latest pushed
value to its destination at a steady rate. See [Publish a data stream](../how-to/add-an-output.md).

!!! warning "If something moves, you want a target"
    An output is a paced sender and nothing else: no aliases, no declared range, no clamp,
    no neutral frame on shutdown. A hand, a motor, a haptic or a cursor is a
    [`Target`][myogestic.controls.Target] — see [Drive your own device](../how-to/add-a-target.md).

    An outlet is part of that road rather than an alternative to it:
    [`RemoteTarget`][myogestic.remote.RemoteTarget] builds one
    [`LSLOutlet`][myogestic.outputs.LSLOutlet] per control it drives.

## Outlet

The one base class in the public API. Everything else you implement against is a structural
`Protocol` — see [design principle 1](../concepts/design-principles.md). `Outlet` is a class
because it is sixty lines of running code rather than a shape: a paced daemon thread, a
latest-wins slot, and per-error-kind deduplication. Subclass it to add `_send`.

(The *package* stays `myogestic.outputs` because it also holds the output-side filters and
`EdgeTrigger`, which are not outlets.)

::: myogestic.outputs.Outlet

## Built-in outlets

::: myogestic.outputs.LSLOutlet
