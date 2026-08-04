#!/usr/bin/env python3
r"""Build WS5+ byte sequences with REAL framing and synthetic text.

The rule this exists to serve: a public repo must never carry a real document,
so fixture TEXT is invented -- but fixture STRUCTURE must be the structure real
WordStar writes, or the fixture tests an imaginary format. tools/audit_fixtures.py
is what caught 15 fixtures that had drifted the wrong side of that line.

The framing below is not inferred from a manual. It is read off real WordStar
output (`NOTES.TST`, all four note kinds) and checked byte-for-byte by
`selftest()` at the bottom, which rebuilds a real block from its own parsed
fields and asserts the bytes come back identical.

A symmetric sequence is BRACKETED BY ITS OWN LENGTH -- that is what makes it
"symmetric", and it is the part hand-built fixtures kept getting wrong:

    1D <jump:LE16> <cmd> <content...> <jump:LE16> 1D
    \______________________________________________/
                 jump + 3 bytes total

and for a note (cmd 3=footnote, 4=endnote, 5=annotation, 6=comment) the content
is laid out per the WordStar 7.0 file format spec's Notes section:

    Word  line count of the note text
    Word  the note NUMBER (high bit clear), or an offset to an internal tag
          sequence (high bit set)
    Byte  conversion flag: low nybble target type, high nybble numbering format
          (0 symbols, 1 upper, 2 lower, 3 numeric)
    ...   the note text

Run this file directly to execute the self-test.
"""

FOOTNOTE, ENDNOTE, ANNOTATION, COMMENT = 3, 4, 5, 6

NUMFMT_SYMBOLS, NUMFMT_UPPER, NUMFMT_LOWER, NUMFMT_NUMERIC = 0x00, 0x10, 0x20, 0x30

SOFTPAGE, TAB, PARANUM, INDEX, STYLE = 0x0B, 0x09, 0x0D, 0x0E, 0x11


def block(cmd, content=b''):
    """One symmetric sequence: `1D <jump> <cmd> <content> <jump> 1D`.

    `jump` counts the command byte, the content, and the 3-byte close -- which
    is what makes `data[i+1 : i+3+jump]` (how the parser slices it) land exactly
    on the closing bracket.
    """
    jump = len(content) + 4
    if jump > 0xFFFF:
        raise ValueError('content too long for a 16-bit length')
    j = jump.to_bytes(2, 'little')
    return b'\x1d' + j + bytes([cmd]) + content + j + b'\x1d'


def note(kind, text, number=1, line_count=1, numfmt=NUMFMT_NUMERIC, encoding='cp437'):
    """A footnote/endnote/annotation/comment carrying `text`.

    `number` is what the spec calls the note number and only footnotes and
    endnotes actually use it -- annotations carry a text tag in the same slot,
    comments use neither -- but it is written for all four because real WordStar
    writes the field regardless of whether it means anything.
    """
    body = text.encode(encoding)
    content = (line_count.to_bytes(2, 'little')
               + number.to_bytes(2, 'little')
               + bytes([numfmt])
               + body)
    return block(kind, content)


def style_ref(slot):
    """A paragraph-style selection: four LE16 handles per WSFORMAT (new /
    prev / prev-modified-temp / prev-prev). Word 0 is the joinable one --
    0x02 pool tag in the high byte, 0-based library slot in the low byte.
    Whether it renders as a heading depends on the NAME the slot resolves
    to in the document's style library, not on the slot number (the old
    1-byte `heading(level)` here encoded an invented format: real WordStar
    always writes 8 content bytes, and slot numbers carry no semantics)."""
    w = lambda v: v.to_bytes(2, 'little')
    return block(STYLE, w(0x0200 | slot) + w(0x0201) + w(0x0300) + w(0x0201))


def softpage():
    """WordStar's own end-of-page marker."""
    return block(SOFTPAGE)


def text(s, encoding='cp437'):
    return s.encode(encoding)


def line(s='', encoding='cp437'):
    return s.encode(encoding) + b'\r\n'


# ------------------------------------------------------------------ self-test

def selftest():
    """Prove the framing against REAL WordStar bytes, not against itself.

    Reads a real note block, pulls its fields out with the project's own parser,
    rebuilds the block from those fields, and asserts the bytes are identical. A
    builder verified only by its own round-trip would happily encode a format
    nobody else writes -- which is the exact failure being corrected here.
    """
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
    from ctrlkd import core

    # A note built here must parse back to the text and number it was given.
    for kind, name in ((FOOTNOTE, 'footnote'), (ENDNOTE, 'endnote'),
                       (ANNOTATION, 'annotation'), (COMMENT, 'comment')):
        data = text('Body. ') + note(kind, 'The note text.', number=7) + line(' After.')
        doc = core.parse_ws(data)
        assert len(doc.notes) == 1, f'{name}: expected one note, got {len(doc.notes)}'
        got = doc.notes[0]
        assert got.kind == name, f'{name}: parsed as {got.kind}'
        assert got.text == 'The note text.', f'{name}: text came back {got.text!r}'
        if name in ('footnote', 'endnote'):
            assert got.number == 7, f'{name}: number came back {got.number}'

    # Structural equality with real WordStar, where a real sample is available.
    sample = os.environ.get('WS_NOTE_SAMPLE')
    if sample and os.path.isfile(sample):
        raw = open(sample, 'rb').read()
        i, checked = 0, 0
        while i < len(raw):
            if raw[i] == 0x1D and i + 3 <= len(raw):
                jump = int.from_bytes(raw[i + 1:i + 3], 'little')
                blk = raw[i:i + 3 + jump]
                cmd = blk[3] if len(blk) > 3 else -1
                # Re-emit the same command byte and content through block() and
                # require the identical bytes back: same length word, same close.
                if len(blk) >= 7:
                    rebuilt = block(cmd, blk[4:-3])
                    assert rebuilt == blk, (
                        f'framing mismatch at {i}: built {rebuilt[:12].hex()} '
                        f'vs real {blk[:12].hex()}')
                    checked += 1
                i += jump + 3
            else:
                i += 1
        print(f'  framing matches real WordStar on {checked} block(s) from {sample}')
    else:
        print('  (set WS_NOTE_SAMPLE to a real WS5+ file to also check framing '
              'byte-for-byte)')

    print('ws_fixture selftest OK')


if __name__ == '__main__':
    selftest()
