# Sources

A `Source` wraps a device, file, or transport behind a uniform interface. Built-in sources live here; custom sources implement the [`Source`][myogestic.Source] protocol below. See [Add a custom source](../how-to/add-a-source.md) for the recipe.

## The protocol

::: myogestic.Source

## Built-in sources

::: myogestic.sources.LSLSource

::: myogestic.sources.ReplaySource

::: myogestic.sources.SyntheticSource

::: myogestic.sources.SyntheticForceSource

`TargetSource` takes any [`Trajectory`][myogestic.tracking.Trajectory] — a [`Trapezoid`][myogestic.tracking.Trapezoid] in percent of MVC, a [`Pursuit`][myogestic.tracking.Pursuit] in signed `[-1, +1]` control units, or your own shape with the same three members. The channel is named `target_pct` whichever it is: the name predates the signed trajectories and renaming it would orphan every recording made so far, so the unit is the trajectory's, not the channel name's.

::: myogestic.sources.TargetSource

::: myogestic.sources.target.PHASE_CODES

!!! info "Optional — requires the `serial` extra"
    `SerialSource` is import-only from `myogestic.sources.serial_source` (needs `pyserial`).

::: myogestic.sources.serial_source.SerialSource
