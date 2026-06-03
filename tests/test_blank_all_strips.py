"""Fix A regression: is_ifd_image_blanked must verify EVERY strip, not just the first.

A label/macro whose first strip is blanked but whose later strips still hold
pixel data must NOT be reported as blanked. That single-strip blind spot is what
let in-place de-identification leave the PHI label while the scanner (and the
post-deidentify verify) reported the file clean.
"""

import io

from pathsafe.tiff import (
    _BLANK_JPEG,
    blank_ifd_image_data,
    is_ifd_image_blanked,
    iter_ifds,
    read_header,
)
from tests.conftest import build_tiff_multi_strip


def _first_ifd(content):
    f = io.BytesIO(bytearray(content))
    header = read_header(f)
    _, entries = iter_ifds(f, header)[0]
    return f, header, entries


# A strip that looks like real (un-blanked) JPEG pixel data carrying PHI.
_PHI_STRIP = b"\xff\xd8\xff\xe0" + b"PATIENT JANE DOE MRN 12345 ACCESSION AS-24-999999 " * 4
_TAGS = [(256, 3, 1, 64), (257, 3, 1, 64)]  # ImageWidth / ImageLength


class TestAllStripBlankCheck:
    def test_first_strip_blank_later_strip_phi_is_not_blanked(self):
        """strip0 blanked + strip1 real PHI -> NOT blanked (the exact false-clean bug)."""
        content = build_tiff_multi_strip(_TAGS, [_BLANK_JPEG, _PHI_STRIP])
        f, header, entries = _first_ifd(content)
        assert is_ifd_image_blanked(f, header, entries) is False

    def test_real_multistrip_label_is_not_blanked(self):
        """A real label with PHI in every strip is not blanked."""
        content = build_tiff_multi_strip(_TAGS, [_PHI_STRIP, _PHI_STRIP])
        f, header, entries = _first_ifd(content)
        assert is_ifd_image_blanked(f, header, entries) is False

    def test_fresh_multistrip_blank_is_blanked(self):
        """Blanking every strip via blank_ifd_image_data -> reported blanked (no spurious False).

        Mixes a strip larger than _BLANK_JPEG (gets JPEG marker + zero padding)
        with one smaller (gets all zeros); both must pass the per-strip check.
        """
        big = b"\xab" * (len(_BLANK_JPEG) + 500)
        small = b"\xcd" * 50
        content = build_tiff_multi_strip(_TAGS, [big, small])
        f, header, entries = _first_ifd(content)
        assert is_ifd_image_blanked(f, header, entries) is False  # before
        blank_ifd_image_data(f, header, entries)
        assert is_ifd_image_blanked(f, header, entries) is True  # after, all strips

    def test_legacy_blanked_multistrip_still_recognized(self):
        """Strips blanked by an older version (SOI+EOI + zeros) stay recognized as blanked."""
        from pathsafe.tiff import _LEGACY_BLANK_JPEG

        legacy = _LEGACY_BLANK_JPEG + b"\x00" * 100
        content = build_tiff_multi_strip(_TAGS, [legacy, legacy])
        f, header, entries = _first_ifd(content)
        assert is_ifd_image_blanked(f, header, entries) is True

    def test_many_strips_not_certified_blanked(self, monkeypatch):
        """An IFD with more strips than the cap is never certified blanked (pyramid guard)."""
        monkeypatch.setattr("pathsafe.tiff.blanking.MAX_STRIPS_TO_VERIFY", 2)
        content = build_tiff_multi_strip(_TAGS, [b"\x00" * 100] * 3)
        f, header, entries = _first_ifd(content)
        assert is_ifd_image_blanked(f, header, entries) is False

    def test_blank_marker_prefix_with_phi_tail_is_not_blanked(self):
        """A strip starting with the PATHSAFE blank marker but holding PHI AFTER
        the marker is NOT blanked -- the whole strip past the marker must be zero
        (a head-only check would have wrongly passed this)."""
        crafted = _BLANK_JPEG + b"\x00" * 200 + b"PATIENT JANE DOE AS-24-111111\x01\x02"
        content = build_tiff_multi_strip(_TAGS, [crafted])
        f, header, entries = _first_ifd(content)
        assert is_ifd_image_blanked(f, header, entries) is False

    def test_sub_marker_strip_with_pathsafe_head_is_not_blanked(self):
        """A strip too small to hold the full 426-byte PATHSAFE marker but whose
        head looks like the marker is NOT blanked -- its trailing bytes are
        unverified and could be PHI (the marker requires marker+zero-pad)."""
        crafted = _BLANK_JPEG[:64] + b"RESIDUAL PIXEL/PHI DATA \xde\xad\xbe\xef" * 4  # 176 bytes
        content = build_tiff_multi_strip(_TAGS, [crafted])
        f, header, entries = _first_ifd(content)
        assert is_ifd_image_blanked(f, header, entries) is False

    def test_marker_head_but_phi_in_marker_body_is_not_blanked(self):
        """A >=426-byte strip whose first bytes mimic the PATHSAFE marker head but
        whose marker BODY (bytes 64-425) holds pixel data is NOT blanked: the full
        426-byte marker must equal _BLANK_JPEG, not merely start like it."""
        forged = _BLANK_JPEG[:64] + b"PATIENT AS-24-999999 PHI PIXELS " * 12
        forged = forged[: len(_BLANK_JPEG)] + b"\x00" * 80  # 426 marker region + zero tail
        content = build_tiff_multi_strip(_TAGS, [forged])
        f, header, entries = _first_ifd(content)
        assert is_ifd_image_blanked(f, header, entries) is False

    def test_non_pathsafe_jpeg_head_with_phi_is_not_blanked(self):
        """A JPEG-headed strip that is neither the current PATHSAFE blank nor the
        legacy SOI+EOI form is NOT certified blanked, even with a zero tail -- its
        body is unverifiable, so it must not be trusted (closes the pre-marker gap)."""
        forged = b"\xff\xd8\xff\xe0" + b"PHI AS-24-222222 PATIENT " * 25  # JPEG head, no PATHSAFE
        forged = forged[: len(_BLANK_JPEG)] + b"\x00" * 100  # zero tail past byte 426
        content = build_tiff_multi_strip(_TAGS, [forged])
        f, header, entries = _first_ifd(content)
        assert is_ifd_image_blanked(f, header, entries) is False
