---
title: "File names"
---
Generated take names and model autosaves share one pattern. They identify the participant
and contents in Finder and Explorer without opening the files.

```text
data/<ID>/recordings/   <ID>_<YYYYMMDD-HHMM>_<what>.mg.zip
data/<ID>/predictions/  <ID>_<YYYYMMDD-HHMM>_<what>.mg.zip
data/<ID>/models/       <ID>_<YYYYMMDD-HHMM>_<model>.joblib
```

The folder says what kind of file it is, so the name never repeats it. The participant ID
stays in the name, so a file copied out of `data/` still says whose it is.

## The parts

| Part | Example | Rule |
| --- | --- | --- |
| `<ID>` | `P-023` | ASCII letters, digits, `-` and `_`; other characters become dashes, repeated dashes collapse, and the result is trimmed to 40 characters with edge dashes/underscores removed. Left out when no usable ID remains. |
| `<YYYYMMDD-HHMM>` | `20261105-1533` | Local time the take started, to the minute. `meta.json`'s `created` keeps it to the second. |
| `<what>` | `F`, `R+F`, `follow-F` | What happened in the take, see below. |
| `<model>` | `spar-mlp` | The model's type, lowercase. |

`_` separates the parts, `-` joins the words inside one. A name taken already, by another
take of the same minute with the same `<what>`, gets `-2`, `-3`, … at the end. Nothing is
ever overwritten.

`StatusBar` shows the participant folder using the same safe ID, before the kind subfolder:
`P 001` becomes `data/P-001`. If no usable ID remains, it shows the data root.

## `<what>`

| Take | `<what>` | Example |
| --- | --- | --- |
| Calibration, one gesture | its code | `P-023_20261105-1533_F.mg.zip` |
| Calibration, several gestures | their codes joined by `+` | `P-023_20261103-1035_Re+T+I+M+Ri+L.mg.zip` |
| More than 40 characters of codes | the first three and a count | `…_R+F+P+6-more.mg.zip` |
| Free prediction | `free`, or `free-` and the labelled gesture | `…_free-F.mg.zip` |
| Guided run | `guided` | `…_guided.mg.zip` |
| Follow run | `follow-` and the gesture it followed | `…_follow-F.mg.zip` |
| Named on Stop | the codes, then the name | `…_R+F_practice.mg.zip` |

A take in `recordings/` names the classes with recorded time, in the
app's class order. An unnamed calibration take with no recorded class time omits the
`_<what>` suffix. A take in `predictions/` is a `free` run unless its `Session.name` says
otherwise. `FollowRun` names its take `follow-<code>`, and an app sets `guided` for a
guided run.

## Gesture codes

A code is the first letter of the gesture, capitalized. A gesture of several words takes the
first letter of each, so `Three-Finger-Pinch` becomes `Tfp`. A number stays whole, so
`Pose 10` becomes `P10`. If codes match when ignoring case, both take more letters of their
first word until they differ. `Rest` and `Ring` become `Re` and `Ri`.

```python
from myogestic.session import class_codes

print(class_codes(["Rest", "Thumb", "Index", "Middle", "Ring", "Little"]))
# {'Rest': 'Re', 'Thumb': 'T', 'Index': 'I', 'Middle': 'M', 'Ring': 'Ri', 'Little': 'L'}
print(class_codes(["Rest", "Fist", "Pinch", "Three-Finger-Pinch"]))
# {'Rest': 'R', 'Fist': 'F', 'Pinch': 'P', 'Three-Finger-Pinch': 'Tfp'}
```

Codes are worked out over the app's whole class list, so a gesture keeps its code in every
take of that app. Adding `Ring` to an app with
`Rest` and Rest moves from `R` to `Re`. Once an app has data, pin its codes next to its class
list:

```python
from myogestic import App

app = App("Bracelet")
app.ctx.class_names = ["Rest", "Fist", "Pinch", "Ring"]
app.ctx.class_codes = {"Rest": "R"}  # the rest are worked out around it: Ring → Ri
```

Every take saves the whole map as `meta.json`'s `class_codes`, so any file decodes later,
whatever the app's codes are by then.

## Models

[`Pipeline.autosave_dir`][myogestic.ml.Pipeline] saves each trained model as
`<ID>_<YYYYMMDD-HHMM>_<model>.joblib`, where `<model>` is `pipeline.model_name`
(`"spar-mlp"`) or, unset, the trained object's class (`MLPDirectV3` → `mlp-direct-v3`). An app
that saves models itself gets the same name from
[`model_path(root, participant, model)`][myogestic.session.model_path].

## Older files

`open_session_store` accepts any `.zip` with `meta.json` and its declared stream arrays,
including `P-023_2026-11-05_15-33-30_Fist.session.zip`. Match takes with `*.zip` and models
with `*.joblib`. Never match a fixed naming suffix. Files on disk keep their names.
