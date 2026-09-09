"""Planning #231: `.poe`/`.poo` even/odd page offset in Printed mode.

Root cause (2026-09-08 #202 batch, cause 6): WordStar's `.PO can optionally
specify even or odd number page offsets` (WSFORMAT.WS) -- `.poe`/`.poo` are
real, distinct 3-letter dot commands, but nothing in this engine's
pagination model tracked a page's own odd/even PARITY, so they parsed as
ordinary unrecognized dot commands (preserved verbatim, no effect on
layout). Measured against real WS7 (sawyer/REF/-HOW-TO.RJS, ws7-prints/v4,
private corpus): the brief's own rule -- "odd pages use .poo (or .po), even
pages .poe (or .po)."

Implementation, both new axes:

  1. core.py: `.poe`/`.poo` are independently STATEFUL (same family as
     `.po`/`.lh`/`.oc`), carried per line as `Line.poe_cols`/`Line.poo_cols`
     (None each = "no override in force"). Which of the two, if either,
     ever governs a given PHYSICAL line depends on the PARITY of the page
     it lands on -- not knowable at parse time (pagination is a later,
     separate pass) -- so these are recorded but never resolved to a final
     left origin at parse time.
  2. pdf.py: `_doc_to_pagelines`/`_body_stream_printed` record a candidate
     `(even_pt, odd_pt)` pair on `PageLine.parity_left` for any line
     `.poe`/`.poo` governs. `_close_page` -- the one place in the whole
     pipeline that actually knows which page number a line landed on --
     resolves the pair to a final `.left` once that page closes. The same
     parity feeds `Page.po_cols` (the header/footer LEFT edge) via new
     `_poe_checkpoints`/`_poo_checkpoints` (mirroring `_po_checkpoints`).

A document that never uses `.poe`/`.poo` costs nothing: every new field
stays None throughout, `parity_left` is never set, `_left_for_parity`
always falls back to the ordinary `.po` resolution -- byte-identical
before and after this feature existed (measured: the full 389-document
answer key changed on exactly the 41 real corpus documents that actually
use `.poe`/`.poo` -- mailing-label/envelope alignment templates and the
REF/booklet trio -- and nothing else).
"""
import re
import zlib

from ctrlkd import core, pdf

HARD = b'\r\n'


def _decoded_streams(pdf_bytes):
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', pdf_bytes, re.S):
        body = m[1]
        try:
            out.append(zlib.decompress(body))
        except zlib.error:
            out.append(body)
    return out


def _word_x(stream, word):
    """The Td x immediately preceding `(word) Tj` in one decoded content
    stream, or None if the word never appears as its own Tj operand."""
    needle = word.encode()
    pat = re.compile(rb'([\d.]+) [\d.]+ Td \(' + re.escape(needle) + rb'\) Tj')
    m = pat.search(stream)
    return float(m[1]) if m else None


def _doc(src):
    doc = core.parse_ws(src)
    doc.meta['variant'] = 'ws4'
    return doc


def test_poe_poo_parsed_and_carried_stateful_per_line():
    doc = _doc(b'.poe 1"\r\n.poo 2"\r\nAA' + HARD + b'.po 3"\r\nBB' + HARD)
    b = doc.blocks[0]
    assert b.lines[0].poe_cols == 10.0    # 1in = 10 print columns
    assert b.lines[0].poo_cols == 20.0    # 2in = 20 print columns
    # `.po` afterward does not clear the parity overrides -- independently
    # stateful, same family as every other dot command here (module
    # docstring point 1; no corpus evidence either way, conservative
    # reading stands).
    assert b.lines[1].poe_cols == 10.0
    assert b.lines[1].poo_cols == 20.0
    assert b.lines[1].po_cols == 30.0


def test_poe_poo_accept_wordstar_arithmetic():
    """WS4.0+'s own documented dot-command math (WSFORMAT.TXT) -- the one
    real corpus document that depends on `.poe`/`.poo`
    (sawyer/REF/-HOW-TO.RJS) writes both as arithmetic expressions, never a
    bare number: `.poe 0.50-0.20"`, `.poo 0.50+4.50+1.00-0.20"`."""
    doc = _doc(b'.poe 0.50-0.20"\r\n.poo 0.50+4.50+1.00-0.20"\r\nAA' + HARD)
    b = doc.blocks[0]
    assert b.lines[0].poe_cols == 3.0     # 0.30in = 3 cols
    assert b.lines[0].poo_cols == 58.0    # 5.80in = 58 cols


def test_odd_pages_use_poo_even_pages_use_poe():
    """Brief's own rule: odd pages use `.poo`, even pages use `.poe`.
    Three forced (`.pa`) one-line pages -- page 1 odd, page 2 even, page 3
    odd again -- confirms the alternation, not just a single override."""
    doc = _doc(b'.po 0"\r\n.poe 1"\r\n.poo 2"\r\n'
              b'PAGE1' + HARD + b'.pa\r\n'
              b'PAGE2' + HARD + b'.pa\r\n'
              b'PAGE3' + HARD)
    out = pdf.emit_pdf(doc, mode='printed')
    streams = _decoded_streams(out)
    assert len(streams) == 3
    assert _word_x(streams[0], 'PAGE1') == 144.0   # odd -> .poo (2in)
    assert _word_x(streams[1], 'PAGE2') == 72.0     # even -> .poe (1in)
    assert _word_x(streams[2], 'PAGE3') == 144.0   # odd -> .poo again


def test_poe_or_poo_alone_falls_back_to_po_for_the_other_parity():
    """Brief's own rule, parenthetical: "odd pages use .poo (OR .po), even
    pages .poe (or .po)" -- only `.poe` set here, so ODD pages (never
    overridden) fall back to the plain `.po` in force, not WordStar's
    hardcoded 8-column default."""
    doc = _doc(b'.po 3"\r\n.poe 1"\r\n'
              b'PAGE1' + HARD + b'.pa\r\n'
              b'PAGE2' + HARD)
    out = pdf.emit_pdf(doc, mode='printed')
    streams = _decoded_streams(out)
    assert _word_x(streams[0], 'PAGE1') == 216.0    # odd, no .poo -> .po (3in)
    assert _word_x(streams[1], 'PAGE2') == 72.0      # even -> .poe (1in)


def test_document_without_poe_poo_is_unaffected():
    """A document that never uses `.poe`/`.poo` costs nothing -- every
    line's own `parity_left` stays None, `_close_page` never touches
    `.left`, byte-identical to before this feature existed."""
    doc = _doc(b'.po 2"\r\nPAGE1' + HARD + b'.pa\r\nPAGE2' + HARD)
    out = pdf.emit_pdf(doc, mode='printed')
    streams = _decoded_streams(out)
    assert _word_x(streams[0], 'PAGE1') == 144.0
    assert _word_x(streams[1], 'PAGE2') == 144.0     # SAME on every page --
                                                      # no alternation triggered


def test_running_head_follows_poe_poo_without_a_geometry_change():
    """#241 follow-up (2026-09-08): the running head/foot's own
    `page_geom_changed` gate (added so a HOLYMAC-style transient `.po`
    excursion -- one with no `.mt`/`.mb`/`.hm`/`.fm` alongside it -- never
    leaks into the header) was ALSO silently catching a live `.poe`/`.poo`
    parity override, which is itself a real page-layout decision and must
    reach the header/footer regardless. Measured: sawyer/MAILLIST/
    PHONE.LST (`.poo .20"`/`.poe .20"`, no plain `.po`, `.mt`/`.mb`/`.hm`/
    `.fm` never touched) -- its own `.h1` running head rendered at the
    document default 57.6pt instead of the declared 14.4pt; body text was
    already correct (`own_parity_left` is per-LINE, never gated). No
    `.mt`/`.mb`/`.hm`/`.fm` anywhere in this fixture -- `page_geom_changed`
    is False on every page, so a header/footer left edge that still
    tracks parity here can only be `Page.po_parity`."""
    doc = _doc(b'.po 8\r\n.poe 1"\r\n.poo 2"\r\n.he TITLE\r\n'
              b'PAGE1' + HARD + b'.pa\r\n'
              b'PAGE2' + HARD)
    out = pdf.emit_pdf(doc, mode='printed')
    streams = _decoded_streams(out)
    assert len(streams) == 2
    assert _word_x(streams[0], 'TITLE') == 144.0    # odd -> .poo (2in)
    assert _word_x(streams[0], 'PAGE1') == 144.0
    assert _word_x(streams[1], 'TITLE') == 72.0      # even -> .poe (1in)
    assert _word_x(streams[1], 'PAGE2') == 72.0


def test_running_head_ignores_a_transient_po_with_no_geometry_change():
    """#241's own oracle (HOLYMAC.WS), preserved: a plain mid-document `.po`
    change with NO `.poe`/`.poo` in force and no `.mt`/`.mb`/`.hm`/`.fm`
    alongside it must NOT move the running head -- only a genuine geometry
    change (this test) or a live parity override (the sibling test above)
    may."""
    doc = _doc(b'.po 1"\r\n.he TITLE\r\n'
              b'PAGE1' + HARD + b'.pa\r\n'
              b'.po 3"\r\n'
              b'PAGE2' + HARD)
    out = pdf.emit_pdf(doc, mode='printed')
    streams = _decoded_streams(out)
    assert _word_x(streams[0], 'TITLE') == 72.0
    # PAGE2's own body line DOES track the new `.po` (per-line override) --
    # only the running head stays put, per HOLYMAC's own confirmed
    # behaviour.
    assert _word_x(streams[1], 'PAGE2') == 216.0
    assert _word_x(streams[1], 'TITLE') == 72.0
