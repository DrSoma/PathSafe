"""Fix B: a label/macro is only unlinked AFTER its blank is durably confirmed.

Unlinking removes the IFD from the chain the scanner/verifier walks, so if the
blank write did not actually land (e.g. a contended/cloud handle on Windows),
unlinking would turn it into a silent false-clean. The handler must instead
raise and leave the IFD linked (still detectable).
"""

import pytest

from pathsafe.formats.svs import SVSHandler
from tests.conftest import build_tiff_multi_ifd_with_strips


def _svs_with_label(tmp_path):
    label_desc = b"label\x00"
    main = ([(256, 3, 1, 512), (257, 3, 1, 512)], None)
    label = (
        [(270, 2, len(label_desc), label_desc), (256, 3, 1, 100), (257, 3, 1, 100)],
        b"\xff\xd8\xff\xe0" + b"PHI-LABEL-AS-24-777777 " * 40,  # real un-blanked JPEG w/ PHI
    )
    fp = tmp_path / "slide.svs"
    fp.write_bytes(build_tiff_multi_ifd_with_strips([main, label]))
    return fp


def test_unconfirmed_blank_raises_and_does_not_unlink(tmp_path, monkeypatch):
    fp = _svs_with_label(tmp_path)
    handler = SVSHandler()
    # The label is detected as PHI before de-identification.
    assert any(f.tag_name == "LabelImage" for f in handler._scan_label_macro(fp))

    # Simulate a blank write that does NOT persist: claim bytes blanked, write nothing.
    import pathsafe.formats.tiff_base as TB

    monkeypatch.setattr(TB, "blank_ifd_image_data", lambda f, h, e: 4096)

    with pytest.raises(RuntimeError, match="could not be confirmed"):
        handler._blank_label_macro(fp)

    # The label IFD must NOT have been unlinked: with the real predicate restored,
    # the scanner still sees the (un-blanked) label -- no silent false-clean.
    monkeypatch.undo()
    assert any(f.tag_name == "LabelImage" for f in handler._scan_label_macro(fp))


def test_real_label_blanks_verifies_and_unlinks(tmp_path):
    """Happy path: a genuine label is blanked, confirmed, unlinked, and gone from scan."""
    fp = _svs_with_label(tmp_path)
    handler = SVSHandler()
    cleared = handler._blank_label_macro(fp)
    assert any(f.tag_name == "LabelImage" for f in cleared)
    # After blanking+unlinking, the scanner no longer reports the label.
    assert handler._scan_label_macro(fp) == []


def test_ndpi_deidentify_propagates_blank_confirmation_failure(tmp_path, monkeypatch):
    """NDPI.deidentify must NOT swallow a label/macro blank-confirmation failure
    (it previously logged-and-continued, masking a potential false-clean on the
    no-staging NDPI-with-sidecar path where this fsync+confirm is the only guard)."""
    from pathsafe.formats.ndpi import NDPIHandler
    from tests.conftest import build_tiff

    ndpi = tmp_path / "slide.ndpi"
    ndpi.write_bytes(build_tiff([(256, 3, 1, 256), (257, 3, 1, 256)]))

    def _raise(self, _fp):
        raise RuntimeError("LabelImage blanking could not be confirmed on disk")

    monkeypatch.setattr(NDPIHandler, "_blank_label_macro", _raise)

    with pytest.raises(RuntimeError, match="could not be confirmed"):
        NDPIHandler().deidentify(ndpi)
