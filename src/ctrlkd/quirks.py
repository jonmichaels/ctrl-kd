"""ctrl-kd quirks: named, individually switchable departures from a literal
reading of the bytes.

THE RULE THIS SERVES. The engine is faithful by default. A WordStar file's
bytes say what they say, and there are plenty of reasons someone would want
what the file actually asks for -- so nothing here "cleans up" anything
silently. What this module adds is a way to NAME each departure, say in plain
words what it does, say why it applies to THIS document, and let a caller turn
it on or off one at a time.

TWO CLASSES, and the difference is evidence:

  auto    The document's own bytes point at the change. A WS7 header names the
          printer driver it was last printed through, and some of those
          drivers were patched so that a given character PRINTS as something
          other than its code page says. Reproducing what the paper showed IS
          the faithful answer for such a document, so these are ON by default
          -- but they are named, reported, and switchable, so a reader who
          wants the raw code-page character can have it.

  opt-in  Nothing in the file says the change is wanted; a human judged it
          from context. These are OFF by default and stay off until a caller
          asks for one by name.

THE REGISTRY IS THE EXTENSION POINT, and it is deliberately shaped like
`emit.py`'s emitter registry: a module-level dict, a decorator, and the same
entry-point plugin discovery (`ctrlkd.quirks`), so a third party can ship one
in their own package exactly as they can ship an output format. See
EXTENDING.md, "Adding a quirk".

WHERE THE CODE LIVES. A quirk's `apply` is a whole-document IR transform,
called once before any emitter reads the blocks -- the same shape and the same
place `layout.driver_substituted` already occupies. The five driver-keyed
quirks below are the exception and say so in their own docstrings: their
substitutions were already implemented, tested and ruled long before quirks
existed, threaded through the emitters at the points that know when to apply
them. Moving that code here would change nothing about the output and risk a
great deal, so it stayed where it is; those call sites ask `enabled()` instead,
and the registry supplies the name, the reason, the reporting and the switch.
"""
from dataclasses import dataclass, replace as _replace
from typing import Callable

__all__ = ['Quirk', 'AUTO', 'OPT_IN', 'quirk', 'register', 'get_quirk',
           'quirk_names', 'applicable', 'resolve', 'apply_quirks', 'enabled',
           'report', 'list_quirks', 'load_plugins', 'UnknownQuirk']

AUTO = 'auto'
OPT_IN = 'opt-in'

# Where a resolved decision is recorded on the document. Private by name so
# nothing mistakes it for part of the published `--diagnose`/layout-JSON
# surface: both of those select the meta keys they publish explicitly.
_META_KEY = '_quirks'


class UnknownQuirk(KeyError):
    """A caller named a quirk this build has never heard of. Carries the
    name it asked for and every name that IS registered, so a CLI or a GUI
    can say something better than "error"."""

    def __init__(self, name, known):
        self.name, self.known = name, list(known)
        super().__init__(name)

    def __str__(self):
        return f'unknown quirk {self.name!r} (known: {", ".join(self.known)})'


@dataclass(frozen=True)
class Quirk:
    """One named departure.

    `name`        kebab-case, stable forever once shipped: it is what a
                  caller types, what the layout JSON publishes, and what an
                  app stores as a per-document override.
    `description` ONE line of plain language, shown to users as-is. No
                  codenames, no register citations, no jargon -- an app puts
                  this next to a checkbox and a reader who has never heard of
                  WordStar has to understand what turning it on does.
    `quirk_class` AUTO or OPT_IN (see the module docstring).
    `detect`      `(doc) -> str | None`. The REASON this document trips the
                  quirk, in plain language ("last printed on the LJ6DTP
                  driver"), or None when it does not apply at all. Cheap and
                  IR-level: it runs on every document, quirks or not, so the
                  layout JSON can always say "applicable but off" as
                  distinct from "not applicable".
    `apply`       `(doc) -> Document`. The transform, non-mutating: return a
                  copy, never edit `doc` in place (one `convert()` hands the
                  same Document to several emitters). Returning `doc`
                  unchanged is legitimate and means the effect is implemented
                  at its render site, which asks `enabled()` -- see the
                  module docstring.
    """
    name: str
    description: str
    quirk_class: str
    detect: Callable
    apply: Callable


# name -> Quirk. Insertion-ordered, and that order is the order every listing
# and every JSON field uses, so a document's report is stable run to run.
_QUIRK_REGISTRY = {}


def register(q: Quirk):
    """Add (or replace) a quirk by name. Replacing matches `emitter()`'s own
    documented plain-assignment behaviour."""
    _QUIRK_REGISTRY[q.name] = q
    return q


def quirk(name, description, quirk_class=AUTO, detect=None):
    """Register a quirk. Usable as a decorator over its `apply` function:

        @ctrlkd.quirk('my-quirk', description='What it does, in one line.',
                      quirk_class='opt-in', detect=my_detect)
        def my_apply(doc):
            ...
            return new_doc
    """
    def deco(apply_fn):
        register(Quirk(name=name, description=description,
                       quirk_class=quirk_class, detect=detect, apply=apply_fn))
        return apply_fn
    return deco


def get_quirk(name):
    try:
        return _QUIRK_REGISTRY[name]
    except KeyError:
        raise UnknownQuirk(name, _QUIRK_REGISTRY) from None


def quirk_names():
    """Every registered name, registration order -- for CLI help and choices."""
    return list(_QUIRK_REGISTRY)


def load_plugins():
    """Discover third-party quirks via the 'ctrlkd.quirks' entry-point group.

    Same mechanism, same two-Python-version dance, and the same
    first-registration-wins rule as `emit.load_plugins` -- see that function
    for why both `entry_points()` shapes have to work (requires-python >= 3.9).
    """
    from importlib.metadata import entry_points
    eps = entry_points()
    if hasattr(eps, 'select'):
        group = eps.select(group='ctrlkd.quirks')
    else:
        group = eps.get('ctrlkd.quirks', [])
    for ep in group:
        if ep.name not in _QUIRK_REGISTRY:
            q = ep.load()
            register(q if isinstance(q, Quirk) else q())


# ------------------------------------------------------------- applicability

def applicable(doc):
    """`[(name, reason), ...]` for every quirk this document trips, in
    registration order. Independent of what any caller enabled: this is the
    answer to "what does this file have available", which is what lets an app
    offer the choice on a plain, faithful run."""
    out = []
    for q in _QUIRK_REGISTRY.values():
        reason = q.detect(doc)
        if reason:
            out.append((q.name, reason))
    return out


def resolve(doc, enable=(), disable=(), mode='auto'):
    """Decide what runs for this document.

    `mode` is the baseline: 'auto' (the default -- every applicable AUTO
    quirk, no opt-in one), 'off' (nothing at all), or 'all' (every applicable
    quirk whichever class it is). `enable`/`disable` then override the
    baseline per name.

    Naming a quirk this document does not trip is a NO-OP, not an error -- a
    caller may hold a standing list of quirks it always wants and hand the
    same list to every document (an app's own settings do exactly that).
    Naming one that is not registered at all IS an error (`UnknownQuirk`):
    that is a typo or a missing plugin, and swallowing it would silently give
    the caller output it did not ask for.

    Returns `(applicable, applied)` -- the first `[(name, reason), ...]`, the
    second a list of names in registration order.
    """
    enable, disable = list(enable), list(disable)
    for name in enable + disable:
        get_quirk(name)                       # raises UnknownQuirk on a typo
    if mode not in ('auto', 'off', 'all'):
        raise ValueError(f'unknown quirks mode {mode!r}')
    applic = applicable(doc)
    applied = []
    for name, _reason in applic:
        q = _QUIRK_REGISTRY[name]
        if name in disable:
            continue
        on = (name in enable
              or mode == 'all'
              or (mode == 'auto' and q.quirk_class == AUTO))
        if on:
            applied.append(name)
    return applic, applied


def apply_quirks(doc, enable=(), disable=(), mode='auto'):
    """`doc` with the resolved quirks applied, and the decision recorded on
    it so every later pass -- the emitters, the layout JSON's own report, a
    render site that asks `enabled()` -- reads the SAME answer rather than
    re-deriving it.

    A host calls this ONCE, right after parsing, before handing the document
    to any emitter. A caller that never calls it gets the default decision
    anyway (`enabled()` falls back to "applicable AUTO quirks are on"), which
    is byte-identical to the engine before quirks existed.
    """
    applic, applied = resolve(doc, enable=enable, disable=disable, mode=mode)
    meta = dict(doc.meta or {})
    meta[_META_KEY] = {'applicable': applic, 'applied': list(applied)}
    doc = _replace(doc, meta=meta)
    for name in applied:
        doc = _QUIRK_REGISTRY[name].apply(doc)
        # apply() returns a copy; the decision has to survive it, and a
        # transform that rebuilt meta rather than carrying it would otherwise
        # lose the record of its own having run.
        if _META_KEY not in (doc.meta or {}):
            meta = dict(doc.meta or {})
            meta[_META_KEY] = {'applicable': applic, 'applied': list(applied)}
            doc = _replace(doc, meta=meta)
    return doc


def _decision(doc):
    """The recorded decision, or the default one (computed once and cached on
    the document, since `enabled()` is asked repeatedly by the render sites)."""
    meta = doc.meta
    if meta is None:
        return {'applicable': [], 'applied': []}
    got = meta.get(_META_KEY)
    if got is None:
        applic, applied = resolve(doc)
        got = {'applicable': applic, 'applied': applied, 'default': True}
        meta[_META_KEY] = got
    return got


def enabled(doc, name) -> bool:
    """Is `name` in force for this document? The question every render site
    that implements an auto quirk asks."""
    return name in _decision(doc)['applied']


def report(doc):
    """`(applicable_names, applied_names)` for the layout JSON -- both in
    registration order, both empty lists when this document trips nothing."""
    d = _decision(doc)
    return [n for n, _ in d['applicable']], list(d['applied'])


def list_quirks(doc=None):
    """Every registered quirk as plain dicts, for `--list-quirks` and for any
    host building a settings list. With a `doc`, each row also carries whether
    it applies to that document, why, and whether it is in force."""
    rows = []
    reasons = dict(applicable(doc)) if doc is not None else {}
    on = set(report(doc)[1]) if doc is not None else set()
    for q in _QUIRK_REGISTRY.values():
        row = {'name': q.name, 'description': q.description,
               'class': q.quirk_class}
        if doc is not None:
            row['applicable'] = q.name in reasons
            row['reason'] = reasons.get(q.name)
            row['enabled'] = q.name in on
        rows.append(row)
    return rows


# ------------------------------------------------------- shared IR scanning

def _driver(doc):
    """The WS7 header's own 9-byte printer-driver name, upper-cased."""
    return ((getattr(doc, 'meta', None) or {}).get('printer_driver')
            or '').strip().upper()


# ------------------------------------------------------- the driver quirks
#
# All five below were shipped, tested and ruled before quirks mode existed
# (Jon's ruling 2026-09-11 for the euro; register entry C7 and the 2026-08-06
# M7 ruling for the LJ6DTP substitutions). Their `apply` returns the document
# unchanged ON PURPOSE: the transforms live at the call sites that know when
# to run them -- `layout.peseta_euro_table`, `layout.modern_flow`,
# `layout.driver_substituter`, `pdf._lj_substitute` and the PDF writer's own
# colour/pattern resources -- and those sites ask `enabled()`. Rewriting
# correct, ruled, tested code to fit a reporting layer would have been pure
# risk; the quirks design note (2026-09-16) settled it that way.

# WHY DETECTION IS THE DRIVER NAME ALONE, and not "does this file contain the
# character the swap would change". Two reasons, and the second decides it:
#
#  1. It IS the provenance a reader should be shown. A document whose own
#     header names a patched driver has these swaps available whether or not
#     today's text happens to use the affected characters -- "this document's
#     own printer header triggered three automatic changes" is the thing worth
#     telling, and a narrower test would hide it on exactly the files it
#     explains.
#  2. `enabled()` then reads EXACTLY the predicate these call sites already
#     used before quirks existed (the driver name, in the patched set), so the
#     switch adds a name and a report without being able to change one byte of
#     anybody's output by default. A content test would have been a second,
#     parallel answer to "does this rule apply" -- and these substitutions
#     reach text this IR does not hold all of (resolved running heads, TOC and
#     index entries), which is exactly where two answers drift apart.

def _detect_euro(doc):
    from .layout import EURO_PATCHED_DRIVERS
    name = _driver(doc)
    if name not in EURO_PATCHED_DRIVERS:
        return None
    return (f'last printed on the {name} driver, one of the three that were '
            f'patched to print a euro in the peseta character\u2019s slot')


@quirk('driver-euro-sign',
       description='Euro instead of peseta',
       quirk_class=AUTO, detect=_detect_euro)
def _apply_euro(doc):
    """No IR transform here: `layout.peseta_euro_table` is the one place that
    decides, and every emitter already asks it. It asks `enabled()` now."""
    return doc


def _detect_lj(doc):
    """Same rule, same reasoning as `_detect_euro` above: the driver name,
    nothing else."""
    return ('last printed on the LJ6DTP driver'
            if _driver(doc) == 'LJ6DTP' else None)


@quirk('lj6dtp-typography',
       description='Real dashes, curly quotes, ellipsis, ©',
       quirk_class=AUTO,
       detect=_detect_lj)
def _apply_lj_typography(doc):
    """No IR transform: `layout.modern_flow`, `layout.driver_substituter` and
    `pdf._lj_substitute` hold the tables and ask `enabled()`."""
    return doc


@quirk('lj6dtp-box-corners',
       description='Card suits as box corners (Univers)',
       quirk_class=AUTO,
       detect=_detect_lj)
def _apply_lj_corners(doc):
    """No IR transform: `layout.LJ_SUBST_UNIVERS` and `pdf._LJ_SUBST_UNIVERS`
    hold the tables and their call sites ask `enabled()`."""
    return doc


@quirk('lj6dtp-colour-as-gray',
       description='Screen colors as gray',
       quirk_class=AUTO, detect=_detect_lj)
def _apply_lj_colour(doc):
    """No IR transform: the PDF writer's own colour state (`pdf.py`'s
    `_COLOUR_GRAY_LJ6DTP` gate) asks `enabled()`."""
    return doc


@quirk('lj6dtp-fill-patterns',
       description='Colors 9–14 as hatch patterns',
       quirk_class=AUTO, detect=_detect_lj)
def _apply_lj_patterns(doc):
    """No IR transform: the PDF writer's own pattern resources (`pdf.py`'s
    `_LJ6DTP_HP_PATTERNS` gate) ask `enabled()`."""
    return doc


# --------------------------------------------------- the stray strike quirk

def _style_strike_blocks(doc):
    return [b for b in getattr(doc, 'blocks', ()) or ()
            if 'strike' in b.style_attrs]


def _typed_strike(doc):
    """Did the WRITER type a strikeout? `Span.styles` carries only what the
    typist toggled inline (WordStar's `^PX`, byte 0x18); a paragraph style's
    own attribute word arrives separately, on `Block.style_attrs`. That
    separation is the whole basis of this quirk: it can tell a cross-out
    somebody meant from one a style declared."""
    for b in getattr(doc, 'blocks', ()) or ():
        for ln in b.lines:
            for sp in ln.spans:
                if 'strike' in sp.styles:
                    return True
    return False


def _detect_stray_style_strikeout(doc):
    if _typed_strike(doc):
        return None
    if not _style_strike_blocks(doc):
        return None
    names = []
    for b in _style_strike_blocks(doc):
        if b.style_name and b.style_name not in names:
            names.append(b.style_name)
    where = (f'the paragraph style {names[0]!r} turns it on'
             if names else 'a paragraph style turns it on')
    return (f'{where} and the writing never types a cross-out of its own')


@quirk('stray-style-strikeout',
       description='Ignore a strikeout set only by a style',
       quirk_class=OPT_IN, detect=_detect_stray_style_strikeout)
def _apply_stray_style_strikeout(doc):
    """Drop the style-declared strikeout, and only that.

    Every other attribute a style declares is untouched, and so is every
    attribute the writer typed: `detect` has already established there is no
    typed cross-out anywhere in this document, so removing `'strike'` from the
    paragraph styles' own attribute sets cannot take away a cross-out anybody
    meant. Bold, italic and underline declared by the SAME style survive --
    NOVEL.WS's heading style is strike plus bold, and it stays bold.
    """
    blocks = [_replace(b, style_attrs=b.style_attrs - {'strike'})
              if 'strike' in b.style_attrs else b
              for b in doc.blocks]
    out = _replace(doc, blocks=blocks)
    # The STYLE LIBRARY's own derived attribute set, too -- RTF's
    # `\stylesheet` group and HTML's generated per-style CSS are built from
    # `entry['attrs']` (emit.py's `_style_css` and `_rtf_stylesheet`), not
    # from the blocks, so a style left declaring a strike there would put the
    # line back through the reader's own style application. The RAW record
    # fields (`attrs_on`/`attrs_off`) are deliberately NOT touched: those are
    # a pass-through of the file's own bytes, and the bytes really do say
    # strikeout -- this quirk changes what is RENDERED, never what the
    # document is recorded as saying.
    out.styles = [dict(e, attrs=e['attrs'] - {'strike'})
                  if 'strike' in (e.get('attrs') or frozenset()) else e
                  for e in (doc.styles or [])]
    # Running heads and feet carry the same style-declared attributes on
    # their own parallel maps (core's `header_style_attrs` and friends) --
    # a head set in a struck style would otherwise keep the line.
    for attr in ('header_style_attrs', 'footer_style_attrs'):
        d = getattr(out, attr, None)
        if d:
            setattr(out, attr, {k: v - {'strike'} for k, v in d.items()})
    for attr in ('header_style_attrs_parity', 'footer_style_attrs_parity'):
        d = getattr(out, attr, None)
        if d:
            setattr(out, attr, {k: {p: v - {'strike'} for p, v in per.items()}
                                for k, per in d.items()})
    return out
