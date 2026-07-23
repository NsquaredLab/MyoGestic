# API reference

Auto-generated from docstrings via [mkdocstrings](https://mkdocstrings.github.io/). Pick the part of the library you're working with — or, for a signatures-only lookup, use the [API cheatsheet](../reference/api-cheatsheet.md).

<div class="grid cards" markdown>

-   :material-application-braces-outline:{ .lg .middle } __Core__

    ---

    App lifecycle, shared context, streams, layout, and event helpers.

    [`App`][myogestic.App] · [`Stream`][myogestic.Stream] · [`Context`][myogestic.Context]

    [:octicons-arrow-right-24: Core API](core.md)

-   :material-access-point:{ .lg .middle } __Sources__

    ---

    Live devices, LSL inlets, serial transports, or recorded replays.

    [`LSLSource`][myogestic.sources.LSLSource] · [`ReplaySource`][myogestic.sources.ReplaySource]

    [:octicons-arrow-right-24: Sources API](sources.md)

-   :material-export:{ .lg .middle } __Outputs__

    ---

    Push prediction output to LSL, UDP, or serial destinations.

    [`LSLOutlet`][myogestic.outputs.LSLOutlet] · [`UDPOutput`][myogestic.outputs.UDPOutput]

    [:octicons-arrow-right-24: Outputs API](outputs.md)

-   :material-camera-outline:{ .lg .middle } __Bridges__

    ---

    Subprocess acquisition for heavy data that doesn't fit the LSL pull model.

    [`WebCamBridge`][myogestic.bridges.WebCamBridge] · [`CustomBridge`][myogestic.bridges.CustomBridge]

    [:octicons-arrow-right-24: Bridges API](bridges.md)

-   :material-brain:{ .lg .middle } __ML pipeline__

    ---

    Train / predict hooks, pipeline state, and model persistence.

    [`Pipeline`][myogestic.ml.Pipeline] · [`save_pickle`][myogestic.ml.save_pickle]

    [:octicons-arrow-right-24: ML API](ml.md)

-   :material-widgets-outline:{ .lg .middle } __Widgets__

    ---

    Every public widget: viewers, plots, recording, training, status.

    [`SignalViewer`][myogestic.widgets.SignalViewer] · [`RecordingControls`][myogestic.widgets.RecordingControls]

    [:octicons-arrow-right-24: Widgets API](widgets.md)

-   :material-robot-outline:{ .lg .middle } __Models__

    ---

    Constructor recipes for CatBoost / scikit-learn estimators.

    [`catboost_classifier`][myogestic.recipes.estimators.catboost_classifier] · [`sklearn_classifier`][myogestic.recipes.estimators.sklearn_classifier]

    [:octicons-arrow-right-24: Models API](models.md)

-   :material-database-outline:{ .lg .middle } __Session__

    ---

    Read back recorded sessions: labeled / aligned windows, raw store.

    [`open_session_store`][myogestic.session.open_session_store] · [`iter_labeled_windows`][myogestic.session.iter_labeled_windows]

    [:octicons-arrow-right-24: Session API](session.md)

-   :material-filter-variant:{ .lg .middle } __Filters__

    ---

    Output-side smoothing for prediction control vectors.

    [`OneEuroFilter`][myogestic.outputs.filters.OneEuroFilter] · [`GaussianFilter`][myogestic.outputs.filters.GaussianFilter]

    [:octicons-arrow-right-24: Filters API](filters.md)

</div>
