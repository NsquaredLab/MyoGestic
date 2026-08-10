"""Native pure-Python sources for OTB devices (Muovi / Muovi+ & Quattrocento)."""

from myogestic.sources.otb.muovi import MuoviSource
from myogestic.sources.otb.quattrocento import QuattrocentoSource
from myogestic.sources.otb.sessantaquattro import SessantaquattroSource

__all__ = ["MuoviSource", "QuattrocentoSource", "SessantaquattroSource"]
