"""Telling a credential screen apart from a chart with a browser toolbar above it.

Study Terminal must never read or keep a password, a card number or a one-time code that happens to be on screen.
That is the whole reason this check exists and it is not negotiable.

But it was blocking working charts. "Sign in" and "log in" are the most ordinary text on the web, and Microsoft
Edge writes them into its own toolbar -- so anyone capturing the whole browser window, which is exactly what
watching a chart means, caught them and lost the chart. The list also had no word boundaries, so it matched
"card number" inside "Discard numbers".

Both directions are tested here, and the first group matters more than the second: a false negative leaks a
password, a false positive only costs a chart.
"""
from __future__ import annotations

from app.screen.vision import Token, detect_auth_screen


def _tok(text: str, x: float = 100.0, y: float = 50.0) -> Token:
    return Token(text=text, conf=0.9, x0=x, y0=y, x1=x + 80, y1=y + 16)


def _price_axis(width: int = 1920) -> list[Token]:
    """What a chart's price scale looks like to the reader: a column of numbers down the right-hand side, evenly
    spaced, fitting a straight line from price to pixel. A login page has nothing of the kind."""
    out = []
    for i in range(8):
        out.append(_tok(f"{27_600 + i * 15:,}.00", x=width - 120, y=700 - i * 80))
    return out


# ---------------------------------------------------------------- credentials must always stop everything

def test_a_password_field_stops_everything_even_on_a_perfect_chart():
    """The strong words are not corroborated and must never be. A chart that also shows a password is a screen
    with a password on it, and nothing on it gets read."""
    toks = _price_axis() + [_tok("Password")]
    assert detect_auth_screen("NQZ26 $27,686.00 - Microsoft Edge", toks, width=1920) == "Password"


def test_every_credential_word_still_blocks_on_its_own():
    for word in ("password", "passcode", "two-factor", "2fa", "verification code", "one-time code",
                 "security question", "social security", "routing number", "card number", "cvv"):
        toks = _price_axis() + [_tok(word)]
        got = detect_auth_screen("chart", toks, width=1920)
        assert got is not None, f"{word!r} no longer blocks, and it must"
        assert got.lower() == word


def test_a_credential_word_in_the_window_title_blocks_too():
    assert detect_auth_screen("Password manager - Microsoft Edge", _price_axis(), width=1920)


def test_a_real_login_page_is_blocked():
    """No price axis, and the page says what it is. Nothing here should be read."""
    page = [_tok("TopstepX"), _tok("Log in"), _tok("Email"), _tok("Remember me")]
    assert detect_auth_screen("TopstepX - Log in - Microsoft Edge", page, width=1920) is not None


def test_a_login_page_is_blocked_even_without_the_word_password():
    page = [_tok("Sign in to continue"), _tok("Email address"), _tok("Continue")]
    assert detect_auth_screen("Sign in", page, width=1920) == "Sign in"


# ---------------------------------------------------------------- a chart must not be mistaken for one

def test_the_browsers_own_sign_in_button_does_not_block_a_chart():
    """THE BUG. Edge puts "Sign in" in its toolbar. Capturing the whole window -- which is how you watch a chart --
    catches it, and the chart was lost to a word that belongs to the browser, not the page."""
    toks = _price_axis() + [_tok("Sign in", x=1700, y=20), _tok("NQZ26"), _tok("Nasdaq")]
    assert detect_auth_screen("NQZ26 $27,686.00 ▼ -2.31% and 3 more pages - Profile 1 - Microsoft Edge",
                              toks, width=1920) is None


def test_edges_sync_prompt_does_not_block_a_chart():
    toks = _price_axis() + [_tok("Log in to sync your data", x=1500, y=70)]
    assert detect_auth_screen("NQZ26 $27,686.00 - Microsoft Edge", toks, width=1920) is None


def test_without_a_price_axis_the_weak_words_still_block():
    """Corroboration cuts both ways. Take the chart away and "sign in" is all there is to go on, so it blocks."""
    assert detect_auth_screen("Microsoft Edge", [_tok("Sign in")], width=1920) == "Sign in"


def test_a_credential_word_is_matched_even_when_the_reader_runs_words_together():
    """The reason the credential words are matched loosely, with no word boundaries.

    OCR does not reliably put spaces between words. A real password prompt came back from the reader as
    "Enteryourpasswordtosign in". A tidier pattern with \\b around each word stops seeing the password in that,
    and a screen with a password on it would be read and kept. This test is the reason that tidying must not
    happen again."""
    glued = [_tok("Enteryourpasswordtosign in")]
    assert detect_auth_screen("Broker", glued, width=1920) is not None
    assert detect_auth_screen("Broker", [_tok("yourcardnumberis")], width=1920) is not None
    assert detect_auth_screen("Broker", [_tok("entercvvcode")], width=1920) is not None


def test_the_price_of_loose_matching_is_accepted_on_purpose():
    """Matching loosely means a word that merely contains a credential word blocks a reading. "Discard numbers"
    contains "card number". That is the deliberate trade: a missed credential is a leak, a false hit costs one
    chart reading and the message names the word so it can be seen for what it is. Written down as a decision
    rather than left as a surprise."""
    assert detect_auth_screen("chart", [_tok("Discard numbers")], width=1920) == "card number"


def test_log_out_was_never_and_is_never_a_login():
    assert detect_auth_screen("chart", _price_axis() + [_tok("Log out")], width=1920) is None
    assert detect_auth_screen("chart", [_tok("Log out")], width=1920) is None


def test_chart_like_can_be_stated_outright():
    toks = [_tok("Sign in")]
    assert detect_auth_screen("x", toks, chart_like=True) is None
    assert detect_auth_screen("x", toks, chart_like=False) == "Sign in"


def test_the_real_topstepx_capture_is_not_blocked():
    """The user's actual Edge window, read for real. It was never blocked by the old rule either -- this pins that
    it stays that way through any future change to the word list."""
    from pathlib import Path

    import numpy as np
    import pytest
    from PIL import Image

    from app.screen.vision import ocr
    p = Path("/mnt/user-data/uploads/4aef9743-image.png")
    if not p.exists():
        pytest.skip("the real capture isn't on this machine")
    img = np.array(Image.open(p).convert("RGB"))
    toks = ocr(img)
    title = "NQZ26 $27,387.75 ▼ -2.31% and 3 more pages - Profile 1 - Microsoft Edge"
    assert detect_auth_screen(title, toks, width=img.shape[1]) is None
