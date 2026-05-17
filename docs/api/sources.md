# Sources

A `Source` wraps a device, file, or transport behind a uniform interface. Built-in sources live here; custom sources implement the [`Source`][myogestic.Source] protocol below. See [Add a custom source](../how-to/add-a-source.md) for the recipe.

## The protocol

::: myogestic.Source

## Built-in sources

::: myogestic.sources.LSLSource

::: myogestic.sources.ReplaySource

### `SerialSource`

Opt-in: lives at `myogestic.sources.serial_source.SerialSource`. Direct import only (requires the `serial` extra for `pyserial`).

::: myogestic.sources.serial_source.SerialSource
