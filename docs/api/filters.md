# Filters

Output-side smoothing filters for prediction-output control vectors. Custom filters implement the [`VectorFilter`][myogestic.filters.VectorFilter] protocol below. See [Post-process predictions](../how-to/post-process-output.md) for tuning guidance.

## The protocol

::: myogestic.filters.VectorFilter

## Built-in filters

::: myogestic.filters.OneEuroFilter

::: myogestic.filters.GaussianFilter

::: myogestic.filters.IdentityFilter

## Factory

::: myogestic.filters.make_filter
