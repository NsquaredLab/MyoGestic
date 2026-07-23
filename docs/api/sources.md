# Sources

A `Source` wraps a device, file, or transport behind a uniform interface. Built-in sources live here; custom sources implement the [`Source`][myogestic.Source] protocol below. See [Add a custom source](../how-to/add-a-source.md) for the recipe.

## The protocol

::: myogestic.Source

## Built-in sources

::: myogestic.sources.LSLSource

::: myogestic.sources.ReplaySource

!!! info "Optional — requires the `serial` extra"
    `SerialSource` is import-only from `myogestic.sources.serial_source` (needs `pyserial`).

::: myogestic.sources.serial_source.SerialSource
