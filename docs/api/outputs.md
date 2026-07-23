# Outputs

An `Output` owns a `.push(data)` method plus a daemon thread that drains the latest pushed value to its destination. See [Add a custom output](../how-to/add-an-output.md).

## Base class

::: myogestic.outputs.Output

## Built-in outputs

::: myogestic.outputs.LSLOutlet

::: myogestic.outputs.UDPOutput

!!! info "Optional — requires the `serial` extra"
    `SerialOutput` is import-only from `myogestic.outputs.serial_output` (needs `pyserial`).

::: myogestic.outputs.serial_output.SerialOutput
