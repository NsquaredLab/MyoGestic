# Filters

Output-side smoothing filters for prediction-output control vectors. Custom filters implement the [`VectorFilter`][myogestic.outputs.filters.VectorFilter] protocol below. See [Post-process predictions](../how-to/post-process-output.md) for tuning guidance.

## The protocol

::: myogestic.outputs.filters.VectorFilter

## Built-in filters

::: myogestic.outputs.filters.OneEuroFilter

::: myogestic.outputs.filters.GaussianFilter

::: myogestic.outputs.filters.IdentityFilter

## Factory

::: myogestic.outputs.filters.make_filter

## Composition

::: myogestic.outputs.filters.chain
