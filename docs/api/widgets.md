# Widgets

Widget classes you construct once and render with `.ui(...)` from inside `@app.ui`. See the [Widgets concept page](../concepts/widgets.md) for the contract and the [widget gallery](../widget-gallery.md) for a visual index of all of them on one page.

## Signal viewers

::: myogestic.widgets.SignalViewer

![signal_viewer](../images/widgets/signal_viewer.png){ loading=lazy }

::: myogestic.widgets.RawSignalViewer

## Recording and sessions

::: myogestic.widgets.RecordingControls

![recording_controls](../images/widgets/recording_controls.png){ loading=lazy }

::: myogestic.widgets.SessionManager

![session_manager](../images/widgets/session_manager.png){ loading=lazy }

## Process management

::: myogestic.widgets.ProcessLauncher

![process_launcher](../images/widgets/process_launcher.png){ loading=lazy }

## Plotting

::: myogestic.widgets.Scatter2D

::: myogestic.widgets.Scatter3D

::: myogestic.widgets.Heatmap

::: myogestic.widgets.LinePlot

## Output processing

::: myogestic.widgets.PostProcessor

![FilterControl](../images/widgets/FilterControl.png){ loading=lazy }

::: myogestic.widgets.FilterProcessor
    options:
      summary:
        functions: true
        attributes: true

::: myogestic.widgets.FilterSpec

::: myogestic.widgets.FilterParam

## Feature selection

::: myogestic.widgets.FeatureSelector

![FeatureSelector](../images/widgets/FeatureSelector.png){ loading=lazy }

## Training and inspection

::: myogestic.widgets.TemplateInspector

::: myogestic.widgets.training.template_inspector.TemplateInspectorRow

::: myogestic.widgets.TrialPreview

## Layout helpers

::: myogestic.widgets.panel_header

::: myogestic.widgets.popout_panel

## Status and logs

::: myogestic.widgets.StreamPanel

::: myogestic.widgets.LogPanel

## Branding

::: myogestic.widgets.Image

::: myogestic.widgets.AppLogo

![app_logo](../images/widgets/app_logo.png){ loading=lazy }

## ML readout

::: myogestic.widgets.PredictionLabel

![prediction_label](../images/widgets/prediction_label.png){ loading=lazy }

## Virtual Hand integration

::: myogestic.widgets.vhi.panel.VhiMovementPanel

![VhiMovementPanel](../images/widgets/VhiMovementPanel.png){ loading=lazy }

### Lower-level pieces

`VhiMovementPanel` wraps these for the common case. Reach for them directly when you want to share one state cache across multiple panels, or render the palette without owning a client.

::: myogestic.widgets.vhi.palette.vhi_movement_palette

::: myogestic.widgets.vhi.palette.VhiStateCache

::: myogestic.widgets.vhi.palette.VhiStateSnapshot

::: myogestic.widgets.vhi.palette.request_vhi_state_refresh
