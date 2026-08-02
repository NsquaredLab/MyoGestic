# Outputs

An `Output` owns a `.push(data)` method plus a daemon thread that sends the latest pushed
value to its destination at a steady rate. See [Publish a data stream](../how-to/add-an-output.md).

!!! warning "If something moves, you want a target"
    An output is a paced sender and nothing else: no aliases, no declared range, no clamp,
    no neutral frame on shutdown. A hand, a motor, a haptic or a cursor is a
    [`Target`][myogestic.controls.Target] — see [Drive your own device](../how-to/add-a-target.md).

    Outputs are part of that road rather than an alternative to it:
    [`RemoteTarget`][myogestic.remote.RemoteTarget] builds one
    [`LSLOutlet`][myogestic.outputs.LSLOutlet] per control it drives.

## Base class

::: myogestic.outputs.Output

## Built-in outputs

::: myogestic.outputs.LSLOutlet
