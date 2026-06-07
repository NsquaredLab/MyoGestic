# Widgets

Stateless function widgets you call from inside `@app.ui`. See [Widgets concept page](../concepts/widgets.md) for the contract and the [widget gallery](../widget-gallery.md) for a visual index of all of them on one page.

---

::: myogestic.widgets.signal_viewer

![signal_viewer](../images/widgets/signal_viewer.png){ loading=lazy }

---

::: myogestic.widgets.raw_signal_viewer

---

::: myogestic.widgets.recording_controls

![recording_controls](../images/widgets/recording_controls.png){ loading=lazy }

---

::: myogestic.widgets.session_manager

![session_manager](../images/widgets/session_manager.png){ loading=lazy }

---

::: myogestic.widgets.process_launcher

![process_launcher](../images/widgets/process_launcher.png){ loading=lazy }

---

::: myogestic.widgets.scatter2d

::: myogestic.widgets.scatter3d

::: myogestic.widgets.heatmap

::: myogestic.widgets.line_plot

---

::: myogestic.widgets.FilterControl

![FilterControl](../images/widgets/FilterControl.png){ loading=lazy }

---

::: myogestic.widgets.FeatureSelector

![FeatureSelector](../images/widgets/FeatureSelector.png){ loading=lazy }

---

::: myogestic.widgets.template_inspector

::: myogestic.widgets.training.template_inspector.TemplateInspectorRow

::: myogestic.widgets.trial_preview

::: myogestic.widgets.panel_header

::: myogestic.widgets.popout_panel

---

## Status and logs

::: myogestic.widgets.stream_panel

::: myogestic.widgets.log_panel

---

## Branding

::: myogestic.widgets.panels.app_logo.app_logo

![app_logo](../images/widgets/app_logo.png){ loading=lazy }

---

## ML readout

::: myogestic.widgets.training.prediction_label.prediction_label

![prediction_label](../images/widgets/prediction_label.png){ loading=lazy }

---

## Virtual Hand integration

::: myogestic.widgets.vhi.panel.VhiMovementPanel

![VhiMovementPanel](../images/widgets/VhiMovementPanel.png){ loading=lazy }

### Lower-level pieces

`VhiMovementPanel` wraps these for the common case. Reach for them directly when you want to share one state cache across multiple panels, or render the palette without owning a client.

::: myogestic.widgets.vhi.palette.vhi_movement_palette

::: myogestic.widgets.vhi.palette.VhiStateCache

::: myogestic.widgets.vhi.palette.VhiStateSnapshot

::: myogestic.widgets.vhi.palette.request_vhi_state_refresh
