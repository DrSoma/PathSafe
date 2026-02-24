"""Tests for the converter module."""

import struct
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from click.testing import CliRunner

from pathsafe.models import ConversionResult, ConversionBatchResult


def _has_tifffile():
    try:
        import tifffile  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_mock_slide(
    dimensions=(1024, 768),
    level_count=3,
    level_dimensions=None,
    level_downsamples=None,
    properties=None,
    associated_images=None,
):
    """Build a mock OpenSlide object with configurable properties."""
    slide = MagicMock()
    slide.dimensions = dimensions

    if level_dimensions is None:
        w, h = dimensions
        level_dimensions = tuple(
            (w // (2 ** i), h // (2 ** i)) for i in range(level_count)
        )
    slide.level_count = level_count
    slide.level_dimensions = level_dimensions

    if level_downsamples is None:
        level_downsamples = tuple(2.0 ** i for i in range(level_count))
    slide.level_downsamples = level_downsamples

    if properties is None:
        properties = {
            'openslide.vendor': 'hamamatsu',
            'openslide.mpp-x': '0.2274',
            'openslide.mpp-y': '0.2274',
            'openslide.objective-power': '40',
        }
    slide.properties = properties

    # read_region returns a mock PIL Image (RGBA)
    def mock_read_region(location, level, size):
        from PIL import Image
        return Image.new('RGBA', size, (200, 150, 100, 255))

    slide.read_region = mock_read_region

    # Associated images
    if associated_images is None:
        from PIL import Image
        associated_images = {
            'label': Image.new('RGBA', (400, 300), (255, 255, 255, 255)),
            'macro': Image.new('RGBA', (800, 600), (200, 200, 200, 255)),
        }
    slide.associated_images = associated_images
    slide.close = MagicMock()
    slide.__enter__ = MagicMock(return_value=slide)
    slide.__exit__ = MagicMock(return_value=False)

    return slide


def _make_mock_openslide(slide):
    """Build a mock openslide module that returns the given slide."""
    mock_module = MagicMock()
    mock_module.OpenSlide = MagicMock(return_value=slide)
    mock_module.OpenSlide.detect_format = MagicMock(return_value='hamamatsu')
    return mock_module


# ---------------------------------------------------------------------------
# Unit tests -- converter logic with mocked OpenSlide
# ---------------------------------------------------------------------------

class TestConvertFile:
    """Test convert_file with mocked OpenSlide."""

    def test_convert_to_pyramidal_tiff(self, tmp_path):
        """Conversion produces a valid BigTIFF with multiple levels."""
        tifffile = pytest.importorskip("tifffile")

        slide = _make_mock_slide(
            dimensions=(512, 512),
            level_count=2,
            level_dimensions=((512, 512), (256, 256)),
            level_downsamples=(1.0, 2.0),
        )
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'output.tiff'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            # Reset the lazy cache
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, target_format='tiff',
                                       tile_size=256, quality=85)

        assert result.error is None
        assert result.levels_written == 2
        assert result.source_format == 'hamamatsu'
        assert result.target_format == 'tiff'
        assert result.conversion_time_ms > 0
        assert output.exists()

        # Verify output is a valid pyramidal TIFF
        with tifffile.TiffFile(str(output)) as tif:
            assert len(tif.pages) >= 2
            page0 = tif.pages[0]
            assert page0.shape[0] == 512
            assert page0.shape[1] == 512

    def test_convert_to_png(self, tmp_path):
        """Single-image PNG export works."""
        slide = _make_mock_slide(dimensions=(256, 256), level_count=1,
                                 level_dimensions=((256, 256),),
                                 level_downsamples=(1.0,))
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'output.png'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, target_format='png')

        assert result.error is None
        assert result.levels_written == 1
        assert output.exists()

        from PIL import Image
        img = Image.open(str(output))
        assert img.size == (256, 256)

    def test_convert_to_jpeg(self, tmp_path):
        """Single-image JPEG export works."""
        slide = _make_mock_slide(dimensions=(256, 256), level_count=1,
                                 level_dimensions=((256, 256),),
                                 level_downsamples=(1.0,))
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'output.jpg'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, target_format='jpeg')

        assert result.error is None
        assert output.exists()

    def test_extract_label(self, tmp_path):
        """Extract associated label image."""
        slide = _make_mock_slide()
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'label.png'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, extract='label')

        assert result.error is None
        assert output.exists()
        from PIL import Image
        img = Image.open(str(output))
        assert img.size == (400, 300)

    def test_extract_macro(self, tmp_path):
        """Extract associated macro image."""
        slide = _make_mock_slide()
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'macro.png'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, extract='macro')

        assert result.error is None
        assert output.exists()

    def test_extract_missing_image(self, tmp_path):
        """Extracting a nonexistent associated image returns error."""
        slide = _make_mock_slide(associated_images={})
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'thumb.png'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, extract='thumbnail')

        assert result.error is not None
        assert 'not found' in result.error.lower()

    def test_file_not_found(self, tmp_path):
        """Missing source file returns error in result."""
        mock_os = _make_mock_openslide(_make_mock_slide())
        mock_os.OpenSlide.detect_format = MagicMock(return_value=None)

        source = tmp_path / 'nonexistent.ndpi'
        output = tmp_path / 'output.tiff'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, target_format='tiff')

        assert result.error is not None
        assert 'not found' in result.error.lower()

    def test_unsupported_format(self, tmp_path):
        """Unsupported target format returns error."""
        mock_os = _make_mock_openslide(_make_mock_slide())

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'output.xyz'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, target_format='xyz')

        assert result.error is not None
        assert 'unsupported' in result.error.lower()

    def test_creates_output_directory(self, tmp_path):
        """Output directory is created if it doesn't exist."""
        slide = _make_mock_slide(dimensions=(256, 256), level_count=1,
                                 level_dimensions=((256, 256),),
                                 level_downsamples=(1.0,))
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'nested' / 'deep' / 'output.png'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, target_format='png')

        assert result.error is None
        assert output.exists()


class TestTimestampReset:
    """Test reset_timestamps on converted files."""

    def test_reset_timestamps_on_convert(self, tmp_path):
        """Converted file has epoch timestamps when reset_timestamps=True."""
        slide = _make_mock_slide(dimensions=(256, 256), level_count=1,
                                 level_dimensions=((256, 256),),
                                 level_downsamples=(1.0,))
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'output.png'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, target_format='png',
                                       reset_timestamps=True)

        assert result.error is None
        assert output.exists()
        stat = output.stat()
        assert stat.st_mtime == 0
        assert stat.st_atime == 0

    def test_no_reset_by_default(self, tmp_path):
        """Converted file keeps normal timestamps by default."""
        slide = _make_mock_slide(dimensions=(256, 256), level_count=1,
                                 level_dimensions=((256, 256),),
                                 level_downsamples=(1.0,))
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'output.png'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, target_format='png')

        assert result.error is None
        assert output.stat().st_mtime > 0

    def test_reset_timestamps_on_error_does_not_crash(self, tmp_path):
        """If conversion fails, reset_timestamps doesn't cause secondary error."""
        mock_os = _make_mock_openslide(_make_mock_slide())
        mock_os.OpenSlide.detect_format = MagicMock(return_value=None)

        source = tmp_path / 'nonexistent.ndpi'
        output = tmp_path / 'output.tiff'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            result = conv.convert_file(source, output, target_format='tiff',
                                       reset_timestamps=True)

        assert result.error is not None


class TestConvertBatch:
    """Test batch conversion."""

    def test_batch_sequential(self, tmp_path):
        """Batch conversion processes multiple files."""
        slide = _make_mock_slide(dimensions=(256, 256), level_count=1,
                                 level_dimensions=((256, 256),),
                                 level_downsamples=(1.0,))
        mock_os = _make_mock_openslide(slide)

        # Create a directory with two fake NDPI files
        input_dir = tmp_path / 'input'
        input_dir.mkdir()
        (input_dir / 'slide1.ndpi').write_bytes(b'\x00' * 100)
        (input_dir / 'slide2.ndpi').write_bytes(b'\x00' * 100)

        output_dir = tmp_path / 'output'
        progress_calls = []

        def on_progress(i, total, filepath, result):
            progress_calls.append((i, total, filepath.name))

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            batch = conv.convert_batch(
                input_dir, output_dir,
                target_format='png',
                progress_callback=on_progress,
            )

        assert batch.total_files == 2
        assert batch.files_converted == 2
        assert batch.files_errored == 0
        assert len(progress_calls) == 2
        assert (output_dir / 'slide1.png').exists()
        assert (output_dir / 'slide2.png').exists()

    def test_batch_parallel(self, tmp_path):
        """Batch conversion works with multiple workers."""
        slide = _make_mock_slide(dimensions=(256, 256), level_count=1,
                                 level_dimensions=((256, 256),),
                                 level_downsamples=(1.0,))
        mock_os = _make_mock_openslide(slide)

        input_dir = tmp_path / 'input'
        input_dir.mkdir()
        (input_dir / 'a.ndpi').write_bytes(b'\x00' * 100)
        (input_dir / 'b.ndpi').write_bytes(b'\x00' * 100)

        output_dir = tmp_path / 'output'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            batch = conv.convert_batch(
                input_dir, output_dir,
                target_format='png',
                workers=2,
            )

        assert batch.total_files == 2
        assert batch.files_converted == 2

    def test_batch_single_file(self, tmp_path):
        """Batch conversion works on a single file path."""
        slide = _make_mock_slide(dimensions=(256, 256), level_count=1,
                                 level_dimensions=((256, 256),),
                                 level_downsamples=(1.0,))
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'single.ndpi'
        source.write_bytes(b'\x00' * 100)
        output_dir = tmp_path / 'output'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            batch = conv.convert_batch(source, output_dir, target_format='png')

        assert batch.total_files == 1
        assert batch.files_converted == 1


class TestConvertCLI:
    """Test the convert CLI subcommand."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_convert_single_file(self, runner, tmp_path):
        """CLI convert on a single file."""
        slide = _make_mock_slide(dimensions=(256, 256), level_count=1,
                                 level_dimensions=((256, 256),),
                                 level_downsamples=(1.0,))
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'out.png'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            from pathsafe.cli import main
            result = runner.invoke(main, [
                'convert', str(source), '-o', str(output), '-t', 'png'])

        assert result.exit_code == 0
        assert 'converted' in result.output.lower()

    def test_convert_extract_label(self, runner, tmp_path):
        """CLI extract label image."""
        slide = _make_mock_slide()
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'label.png'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            from pathsafe.cli import main
            result = runner.invoke(main, [
                'convert', str(source), '-o', str(output), '--extract', 'label'])

        assert result.exit_code == 0
        assert 'label' in result.output.lower()

    @pytest.mark.skipif(
        not _has_tifffile(),
        reason="tifffile not installed (optional convert dependency)")
    def test_convert_batch_directory(self, runner, tmp_path):
        """CLI batch convert a directory."""
        slide = _make_mock_slide(dimensions=(256, 256), level_count=1,
                                 level_dimensions=((256, 256),),
                                 level_downsamples=(1.0,))
        mock_os = _make_mock_openslide(slide)

        input_dir = tmp_path / 'slides'
        input_dir.mkdir()
        (input_dir / 'a.ndpi').write_bytes(b'\x00' * 100)
        output_dir = tmp_path / 'converted'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            from pathsafe.cli import main
            result = runner.invoke(main, [
                'convert', str(input_dir), '-o', str(output_dir), '-t', 'tiff'])

        assert result.exit_code == 0
        assert 'converted' in result.output.lower()

    def test_convert_with_reset_timestamps(self, runner, tmp_path):
        """CLI convert with --reset-timestamps."""
        slide = _make_mock_slide(dimensions=(256, 256), level_count=1,
                                 level_dimensions=((256, 256),),
                                 level_downsamples=(1.0,))
        mock_os = _make_mock_openslide(slide)

        source = tmp_path / 'test.ndpi'
        source.write_bytes(b'\x00' * 100)
        output = tmp_path / 'out.png'

        with patch.dict('sys.modules', {'openslide': mock_os}):
            import pathsafe.converter as conv
            conv._openslide = None
            from pathsafe.cli import main
            result = runner.invoke(main, [
                'convert', str(source), '-o', str(output), '-t', 'png',
                '--reset-timestamps'])

        assert result.exit_code == 0
        assert output.exists()
        assert output.stat().st_mtime == 0

    def test_extract_requires_file(self, runner, tmp_path):
        """CLI extract rejects directory input."""
        input_dir = tmp_path / 'slides'
        input_dir.mkdir()
        output = tmp_path / 'label.png'

        from pathsafe.cli import main
        result = runner.invoke(main, [
            'convert', str(input_dir), '-o', str(output), '--extract', 'label'])

        assert result.exit_code == 1
        assert 'single file' in result.output.lower()


class TestConversionResult:
    """Test the result dataclasses."""

    def test_conversion_result_defaults(self):
        result = ConversionResult(
            source_path=Path('in.ndpi'),
            output_path=Path('out.tiff'),
            source_format='hamamatsu',
            target_format='tiff',
        )
        assert result.levels_written == 0
        assert result.conversion_time_ms == 0.0
        assert result.anonymized is False
        assert result.error is None

    def test_conversion_batch_result_defaults(self):
        batch = ConversionBatchResult()
        assert batch.total_files == 0
        assert batch.files_converted == 0
        assert batch.files_errored == 0
        assert batch.results == []


class TestMissingDeps:
    """Test clear error messages when optional deps are missing."""

    def test_missing_openslide_message(self):
        """Import error for missing openslide is clear."""
        import pathsafe.converter as conv
        saved = conv._openslide
        conv._openslide = None

        with patch.dict('sys.modules', {'openslide': None}):
            # Force re-import attempt
            with pytest.raises(ImportError, match='openslide-python'):
                conv._openslide = None
                conv._require_openslide()

        conv._openslide = saved

    def test_missing_tifffile_message(self):
        """Import error for missing tifffile is clear."""
        import pathsafe.converter as conv
        saved = conv._tifffile
        conv._tifffile = None

        with patch.dict('sys.modules', {'tifffile': None}):
            with pytest.raises(ImportError, match='tifffile'):
                conv._tifffile = None
                conv._require_tifffile()

        conv._tifffile = saved

    def test_missing_numpy_message(self):
        """Import error for missing numpy is clear."""
        import pathsafe.converter as conv
        saved = conv._numpy
        conv._numpy = None

        with patch.dict('sys.modules', {'numpy': None}):
            with pytest.raises(ImportError, match='numpy'):
                conv._numpy = None
                conv._require_numpy()

        conv._numpy = saved
