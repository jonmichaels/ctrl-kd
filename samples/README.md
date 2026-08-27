# Sample documents

Four public-domain texts, authored/transcribed into real WordStar files by Jon
Michaels, bundled here as fixed fixtures for this repo's tier-1 (public,
always-run) test suite and for `ctrl-kd --samples DIR` (writes these same four
files to a directory of your choosing).

| File | Work | Author | Format |
|---|---|---|---|
| `LYING.WS` | "On the Decay of the Art of Lying" (1882) | Mark Twain | WordStar 7 |
| `OCAPTAIN.WS` | "O Captain! My Captain!" (1865) | Walt Whitman | WordStar 4 |
| `TWAINLET.WS` | Letter to Walt Whitman (Hartford, May 24, 1889) | Mark Twain | WordStar 4 |
| `WARPRAYR.WS` | "The War Prayer" (written 1905, published 1916) | Mark Twain | WordStar 7 |

All four works are in the public domain in the United States (both authors
died before 1928: Whitman in 1892, Twain in 1910). The WordStar files
themselves are original transcriptions, shared under this repo's MIT license
same as the code.

These are the SAME four files bundled with the Soft Return macOS app's own
Help > Open Sample Document menu (`SoftReturn/Resources/SampleDocuments/`) —
copied here as fixed, read-only fixtures so this repo's test suite has
something real and public to convert without depending on any private corpus.
`LYING.WS` also carries a real WordStar footnote ("Did not take the prize."),
giving the note-handling code path public-fixture coverage too.

See `tests/test_samples.py` for the tier-1 tests that convert all four across
every output format and mode, checked against committed SHA-256 oracles in
`tests/samples_oracle.json` (regenerate with
`python3 tools/gen_samples_oracle.py` after a deliberate output change).
