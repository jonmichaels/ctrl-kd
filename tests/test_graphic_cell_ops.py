"""planning #251 follow-up (2026-09-10, app coder job 348):
`graphic_cell_ops` exports drawing-grade geometry (`pdf.py`'s own doc
comment on that function has the full derivation) so a consumer stops
reconstructing an arcCorner join from `graphic_cell_rects`' two bounding
rects -- the change that turned LJ6DTP.WS page 3's real 35 vector ops into
the app's own 51. This file is the promised proof: for every arcCorner
character, `graphic_cell_ops`' `stroke_path` replays into the EXACT same
raw PDF operator KIND sequence (w, m, l, c, l, S) the engine's own
`_graphic_ops` emits for that character -- count and kind, not just visual
similarity. Port of Swift's GraphicCellOpsParityTests.swift.
"""
from ctrlkd import pdf


def _op_kind(line):
    """The trailing PDF operator token(s) of one `_graphic_ops` op line --
    "w"/"m"/"l"/"c"/"S" are single trailing tokens; a filled rect
    ("X Y W H re f") and a filled poly's closing segment ("X Y l" ...
    "h f") are the two-token exceptions, folded to "re f"/"h f" so a
    caller can tell them apart from a bare "f" (a disc's own closing
    fill)."""
    parts = line.split(b' ')
    if not parts:
        return ''
    last = parts[-1]
    if last == b'f' and len(parts) >= 2:
        prev = parts[-2]
        if prev == b're':
            return 're f'
        if prev == b'h':
            return 'h f'
    return last.decode('ascii')


def _op_kinds(ops):
    return [_op_kind(line) for line in ops]


def _replayed_kinds(ops):
    """`graphic_cell_ops`' own `stroke_path` segments, replayed into the
    same op-kind vocabulary `_op_kinds` extracts from a real
    `_graphic_ops` stream."""
    out = []
    for op in ops:
        if op[0] != 'stroke_path':
            continue
        out.append('w')
        for seg in op[1]:
            kind = seg[0]
            if kind == 'm':
                out.append('m')
            elif kind == 'l':
                out.append('l')
            elif kind == 'c':
                out.append('c')
        out.append('S')
    return out


def test_arc_corners_ops_match_engine_op_kind_sequence_exactly():
    for char in pdf.ARC_CORNERS:
        real = pdf._graphic_ops(char, 0.0, 100.0, 12.0, 12)
        real_kinds = _op_kinds(real)
        mine = pdf.graphic_cell_ops(char)
        assert len(mine) == 1, f'expected exactly one op for arcCorner {char!r}'
        mine_kinds = _replayed_kinds(mine)
        assert mine_kinds == real_kinds, (
            f'arcCorner {char!r}: op kinds {mine_kinds} != engine\'s own {real_kinds}')
        # The engine's own real sequence is exactly six tokens -- pin it
        # directly so a future change to `_graphic_ops`' arcCorners branch
        # that silently adds/removes a step fails HERE too.
        assert real_kinds == ['w', 'm', 'l', 'c', 'l', 'S']


def test_box_arms_ops_match_engine_fill_rect_count():
    for char, arms in pdf.BOX_ARMS.items():
        real = pdf._graphic_ops(char, 0.0, 100.0, 12.0, 12)
        real_rect_count = sum(1 for line in real if line.endswith(b' re f'))
        mine = pdf.graphic_cell_ops(char)
        assert len(mine) == real_rect_count, (
            f'boxArms {char!r} ({arms}): {len(mine)} ops vs engine\'s {real_rect_count} rects')
        assert all(op[0] == 'fill_rect' and op[5] is None for op in mine)


def test_full_block_and_shade_gray_ops_are_one_fill_rect_each():
    assert pdf.graphic_cell_ops('█') == [('fill_rect', 0.0, 0.0, 1.0, 1.0, None)]
    for char, gray in pdf.SHADE_GRAY.items():
        assert pdf.graphic_cell_ops(char) == [('fill_rect', 0.0, 0.0, 1.0, 1.0, gray)]


def test_symbol_shapes_ops_skip_white_knockouts_same_as_rects():
    for char, shapes in pdf.SYMBOL_SHAPES.items():
        positive_count = sum(1 for shape in shapes if shape[0] != 'white')
        assert len(pdf.graphic_cell_ops(char)) == positive_count


def test_non_graphic_character_has_no_ops():
    assert pdf.graphic_cell_ops('A') == []
    assert pdf.graphic_cell_ops(' ') == []
