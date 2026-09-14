r"""planning #264, MAIL MERGE SCOPE (Jon, 2026-09-13) and its two addenda.

Verbatim: "the list of name and addresses? Those we should be able to open
and people should be able to get that list out into something useful";
then "a plain list: names (and addresses if present) on lines, one record
per block -- not a table export"; then "we should probably have some code
to detect a file as a MailMerge data file. It should show up listed as
such in Document Info. And yes we should be kind and strip out the codes
on export."; and finally "a .DTA made in document mode carries WordStar's
high-bit marks, control codes, Ctrl-Z padding and cp437 characters; the
reader must decode through the engine ... so the list is clean -- that is
the point of opening it in Soft Return."

NO MERGE IS EVER EXECUTED, here or anywhere (register, "Mail Merge --
scope"; the permanent ruling 2026-08-06). This reads a list.

THE DETECTION IS STRUCTURAL AND ONLY STRUCTURAL, because the
Corpus-And-Filetype-Index says it has to be: `detect()` must be
corroborated by STRUCTURE, never by a usage string -- that is exactly how
`.PDF` false-positived on binaries carrying help text. Nothing in
`core.merge_data_records` looks for a word, a name, a header row or a
field label; the false-positive rows below are what that buys.

Synthetic fixtures only.
"""
import pytest

from ctrlkd import core, emit, info

HARD = b'\x0d\x0a'
SOFT = b'\x8d\x0a'
PAD = b'\x1a' * 8


def _hibit_word(word):
    """A WS4 word: bit 7 on the last letter, WordStar's own wrap mark."""
    return word[:-1].encode() + bytes([word[-1:].encode()[0] | 0x80])


PLAIN = (b'"Sawyer","Robert J.","Toronto"' + HARD
         + b'"Doe","Jane","Ottawa"' + HARD
         + b'"Roe","Richard","Halifax"' + HARD + PAD)


# ------------------------------------------------------------- detection

def test_a_plain_data_file_is_recognised():
    det = core.detect(PLAIN)
    assert det['kind'] == core.MERGE_DATA_KIND
    assert det['merge_records'] == 3 and det['merge_fields'] == 3


def test_the_variant_is_left_exactly_as_the_bytes_found_it():
    """The kind is an ADDITIONAL fact about the same bytes. A
    non-document data file really is plain text and everything downstream
    that branches on `variant` must go on seeing what it always saw."""
    assert core.detect(PLAIN)['variant'] == 'printstream'


def test_document_info_reports_the_kind():
    """"It should show up listed as such in Document Info.\""""
    rep = info.document_info(PLAIN, path='WSLIST.DTA')
    assert rep['kind'] == core.MERGE_DATA_KIND
    assert rep['merge_records'] == 3


# --------------------------------------------------- false positives

def test_ordinary_prose_with_commas_is_not_a_data_file():
    prose = (b'It was a bright, cold day in April, and the clocks' + HARD
             + b'were striking thirteen, as they always do.' + HARD)
    assert 'kind' not in core.detect(prose)


def test_a_merge_LETTER_is_not_its_data():
    """A `.df`/`.rv` line means this is the letter. The corpus's own
    `MAILLIST.DOT` is exactly this shape."""
    letter = (b'.df wslist.dta' + HARD
              + b'.rv name, company, city' + HARD
              + b'"Dear &name&","&company&","&city&"' + HARD
              + b'"Dear &name&","&company&","&city&"' + HARD)
    assert 'kind' not in core.detect(letter)


def test_records_of_different_widths_are_not_a_data_file():
    """Uniform field count is the strongest single signal, and the one
    prose cannot fake."""
    ragged = (b'"a","b","c"' + HARD + b'"d","e"' + HARD)
    assert 'kind' not in core.detect(ragged)


def test_a_single_field_per_line_is_not_a_data_file():
    single = (b'"Sawyer"' + HARD + b'"Doe"' + HARD + b'"Roe"' + HARD)
    assert 'kind' not in core.detect(single)


def test_one_record_is_not_a_list():
    assert 'kind' not in core.detect(b'"Sawyer","Robert J.","Toronto"' + HARD)


def test_mostly_unquoted_records_are_not_a_data_file():
    """Jon's own description of the shape: "already comma-separated quoted
    records (CSV without headers)." A bare comma list could be anything."""
    bare = (b'a,b,c' + HARD + b'd,e,f' + HARD + b'g,h,i' + HARD)
    assert 'kind' not in core.detect(bare)


def test_an_unterminated_quote_disqualifies_the_file():
    broken = (b'"Sawyer","Robert J.","Toronto' + HARD
              + b'"Doe","Jane","Ottawa"' + HARD)
    assert 'kind' not in core.detect(broken)


def test_a_real_document_is_never_a_data_file():
    """Symmetric blocks past the opening header are WS5+ machinery -- a
    list carries no footnotes, fonts or style library."""
    count = (4 + 8).to_bytes(2, 'little')
    note = b'\x1d' + count + b'\x06' + bytes(7) + count + b'\x1d'
    doc = (b'"a","b","c"' + HARD + note + b'"d","e","f"' + HARD)
    assert 'kind' not in core.detect(doc)


def test_no_usage_string_is_ever_consulted():
    """The index's own rule. A file whose FIELD TEXT is full of merge
    vocabulary is still judged on its shape alone -- this one passes
    because it is shaped like a list, not because of what it says."""
    talky = (b'"mail merge",".df",".rv"' + HARD
             + b'"data file","dta","merge"' + HARD)
    assert core.detect(talky)['kind'] == core.MERGE_DATA_KIND
    # ...and the same words in a shape that is not a list are refused
    assert 'kind' not in core.detect(b'mail merge data file .df .rv' + HARD
                                     + b'a second line of the same' + HARD)


# --------------------------------------------- opening it as records

def test_it_opens_as_one_block_per_record():
    doc = core.parse(PLAIN)
    assert doc.meta['kind'] == core.MERGE_DATA_KIND
    assert len(doc.blocks) == 3
    first = [''.join(sp.text for sp in ln.spans) for ln in doc.blocks[0].lines]
    assert first[:3] == ['Sawyer', 'Robert J.', 'Toronto']


def test_the_ctrl_z_padding_never_reaches_a_field():
    for b in core.parse(PLAIN).blocks:
        for ln in b.lines:
            assert '\x1a' not in ''.join(sp.text for sp in ln.spans)


def test_a_document_mode_file_is_decoded_through_the_engine():
    """The point of opening one at all: bit-7 word marks stripped, a soft
    return joined back into its record, a soft space read as a space, ^Z
    padding dropped. WS4 shape -- that is the era whose files carry the
    mark."""
    rec1 = (b'"' + _hibit_word('Sawyer') + b'","'
            + _hibit_word('Robert') + b'\xa0' + _hibit_word('J') + b'.","'
            + _hibit_word('Toronto') + b'"')
    rec2 = (b'"' + _hibit_word('Doe') + b'","' + _hibit_word('Jane')
            + b'","' + _hibit_word('Ottawa') + b'"')
    data = rec1 + HARD + rec2 + HARD + PAD
    det = core.detect(data)
    assert det['kind'] == core.MERGE_DATA_KIND
    doc = core.parse(data)
    rows = [[''.join(sp.text for sp in ln.spans) for ln in b.lines
             if ''.join(sp.text for sp in ln.spans)]
            for b in doc.blocks]
    assert rows[0] == ['Sawyer', 'Robert J.', 'Toronto']
    assert rows[1] == ['Doe', 'Jane', 'Ottawa']


def test_a_record_long_enough_to_wrap_is_declined_rather_than_half_read():
    """A soft return ends a record line here, because it ends a `Line` in
    the engine too -- WS4 reads a short soft-broken line as a deliberate
    break by its own fit heuristic, and the two halves reach the test
    separately either way. So a wrapped record leaves two malformed halves
    and the file is DECLINED. Conservative on purpose: it keeps `detect`
    and `parse_merge_data` from ever disagreeing about where a record
    ends, and the archive carries no data file at all to argue the other
    way."""
    data = (b'"Sawyer","Robert' + SOFT + b'J.","Toronto"' + HARD
            + b'"Doe","Jane' + SOFT + b'A.","Ottawa"' + HARD + PAD)
    assert 'kind' not in core.detect(data)


def test_a_document_mode_file_with_returns_of_both_kinds_still_reads():
    """What a real one looks like: every record on its own hard-returned
    line, bit-7 word marks throughout, ^Z padding at the end."""
    def rec(*words):
        return b'","'.join(_hibit_word(w) for w in words)
    data = (b'"' + rec('Sawyer', 'Robert', 'Toronto') + b'"' + HARD
            + b'"' + rec('Doe', 'Jane', 'Ottawa') + b'"' + HARD
            + b'"' + rec('Roe', 'Richard', 'Halifax') + b'"' + HARD + PAD)
    assert core.detect(data)['kind'] == core.MERGE_DATA_KIND
    doc = core.parse(data)
    assert len(doc.blocks) == 3
    first = [''.join(sp.text for sp in ln.spans) for ln in doc.blocks[0].lines]
    assert first[:3] == ['Sawyer', 'Robert', 'Toronto']


def test_a_comma_inside_a_quoted_field_is_not_a_separator():
    data = (b'"Sawyer","Toronto, Ontario","Canada"' + HARD
            + b'"Doe","Ottawa, Ontario","Canada"' + HARD)
    rows = [[''.join(sp.text for sp in ln.spans) for ln in b.lines
             if ''.join(sp.text for sp in ln.spans)]
            for b in core.parse(data).blocks]
    assert rows[0] == ['Sawyer', 'Toronto, Ontario', 'Canada']


def test_a_doubled_quote_inside_a_field_is_one_quote():
    data = (b'"Sawyer","the ""Rob"" one","Toronto"' + HARD
            + b'"Doe","the ""Jan"" one","Ottawa"' + HARD)
    rows = [[''.join(sp.text for sp in ln.spans) for ln in b.lines
             if ''.join(sp.text for sp in ln.spans)]
            for b in core.parse(data).blocks]
    assert rows[0][1] == 'the "Rob" one'


# ------------------------------------------------ exporting the list

EXPECTED_LIST = ('Sawyer\nRobert J.\nToronto\n\n'
                 'Doe\nJane\nOttawa\n\n'
                 'Roe\nRichard\nHalifax\n')


@pytest.mark.parametrize('mode', ['printed', 'modern'])
def test_text_is_the_plain_list(mode):
    assert emit.emit_text(core.parse(PLAIN), mode=mode) == EXPECTED_LIST


def test_markdown_mirrors_the_text_list():
    md = emit.emit_markdown(core.parse(PLAIN), mode='modern')
    assert [l.rstrip() for l in md.splitlines()] == EXPECTED_LIST.splitlines()


def test_html_mirrors_the_text_list():
    html = emit.emit_html(core.parse(PLAIN), mode='modern')
    body = html[html.index('<body>'):]
    assert body.count('<p') == 3
    assert 'Sawyer<br>' in body and 'Robert J.<br>' in body
    assert 'Toronto</p>' in body


def test_rtf_mirrors_the_text_list():
    rtf = emit.emit_rtf(core.parse(PLAIN), mode='modern')
    assert rtf.count(r'\par ') >= 3
    for field in ('Sawyer', 'Robert J.', 'Toronto', 'Halifax'):
        assert field in rtf


def test_no_export_ever_carries_a_quote_or_a_comma_separator():
    """"strip out the codes on export" -- the CSV punctuation is the
    file's own machinery, not its content."""
    doc = core.parse(PLAIN)
    for fn in (emit.emit_text, emit.emit_markdown):
        out = fn(doc, mode='modern')
        assert '"' not in out
        assert '","' not in out


# ----------------------------------------------------- the corpus (tier 2)

@pytest.mark.sawyer
def test_no_archive_document_is_taken_for_a_data_file(require_sawyer_doc):
    """The false-positive gate that matters: every document the committed
    manifest names, judged by the real `detect()`. The manifest, never a
    directory sweep -- the 2026-08-26 tier-2 ruling.

    THE ARCHIVE CARRIES NO DATA FILE AT ALL -- swept 2026-09-14 over every
    file in the corpus, allowing for high-bit marks: not one holds so much
    as two comma-separated quoted records. The `.LST` files the corpus
    does have (`HP-ENV.LST`, `PHONE.LST`, `INVNTORY.LST`, `LSRLABL3.LST`)
    are LABEL AND ENVELOPE TEMPLATES -- real WordStar documents full of
    dot commands, which is why the index lists them among the documents
    whose extension lies. So this row asserts the only thing the archive
    can prove: that nothing in it is mistaken for one."""
    from sawyer_fixture import sawyer_classify
    convertible, _nonconvertible, _assets = sawyer_classify()
    for name in convertible:
        with open(require_sawyer_doc(name), 'rb') as fh:
            data = fh.read()
        assert core.detect(data).get('kind') is None, name
    assert len(convertible) > 100
