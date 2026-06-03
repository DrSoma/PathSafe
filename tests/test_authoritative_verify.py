"""Fix D: post-deidentification verification is AUTHORITATIVE.

When verify is on and residual CONTENT PHI remains (or the re-scan errors), the
file is reported as an ERROR and the staging copy is NOT promoted -- a run never
silently reports success while PHI survives on disk. Filename-only PHI stays a
non-fatal warning. `verified` is tri-state: None=not run, True=clean, False=failed.
"""

from pathsafe.deidentifier import deidentify_file
from tests.conftest import build_tiff


def _svs(tmp_path):
    desc = b"Aperio Image Library v12\n1024x768|Filename = AS-24-9.svs|User = jdoe\x00"
    entries = [(256, 3, 1, 1024), (257, 3, 1, 768), (270, 2, len(desc), desc)]
    fp = tmp_path / "slide.svs"
    fp.write_bytes(build_tiff(entries))
    return fp


class _FakeFinding:
    def __init__(self, source):
        self.source = source


class _FakeScan:
    def __init__(self, findings, error=None):
        self.findings = findings
        self.error = error
        self.is_clean = not findings and not error


def test_residual_content_phi_is_authoritative_error(tmp_path, monkeypatch):
    fp = _svs(tmp_path)
    monkeypatch.setattr(
        "pathsafe.verify.verify_file", lambda p: _FakeScan([_FakeFinding("tiff_tag")])
    )
    result = deidentify_file(fp, output_path=None, verify=True)
    assert result.error is not None and "residual PHI" in result.error
    assert result.verified is False
    # in-place: staging was NOT promoted and left no orphan
    assert list(tmp_path.glob("*pathsafe_pending*")) == []


def test_verify_scan_error_is_authoritative_error(tmp_path, monkeypatch):
    fp = _svs(tmp_path)
    monkeypatch.setattr(
        "pathsafe.verify.verify_file", lambda p: _FakeScan([], error="scan crashed")
    )
    result = deidentify_file(fp, output_path=None, verify=True)
    assert result.error is not None and "could not run" in result.error
    assert result.verified is False


def test_filename_only_phi_does_not_fail_verify(tmp_path, monkeypatch):
    fp = _svs(tmp_path)
    monkeypatch.setattr(
        "pathsafe.verify.verify_file", lambda p: _FakeScan([_FakeFinding("filename")])
    )
    result = deidentify_file(fp, output_path=None, verify=True)
    assert result.error is None
    assert result.verified is True


def test_verify_disabled_leaves_verified_none(tmp_path):
    fp = _svs(tmp_path)
    result = deidentify_file(fp, output_path=None, verify=False)
    assert result.error is None
    assert result.verified is None


def test_verify_pass_sets_verified_true(tmp_path):
    fp = _svs(tmp_path)
    result = deidentify_file(fp, output_path=None, verify=True)  # real verify, content clean
    assert result.error is None
    assert result.verified is True
