"""WSI format conversion -- OpenSlide reads, tifffile/Pillow writes.

Converts whole-slide images to pyramidal TIFF (BigTIFF), single-level
images (PNG/JPEG), or extracts associated images (label, macro, thumbnail).

Requires optional dependencies:
    pip install pathsafe[convert]
    (openslide-python + tifffile)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

from pathsafe.models import ConversionBatchResult, ConversionResult  # noqa: E402
from pathsafe.utils import _sanitize_error  # noqa: E402


# Single-image formats (PNG/JPEG) use this pixel cap to auto-downscale.
# Pyramidal TIFF uses tile-streaming and has no such limit.
MAX_SINGLE_IMAGE_PIXELS = 5000 * 5000

# Lazy-checked at call time
_openslide = None
_tifffile = None
_numpy = None


def _require_openslide() -> Any:
    global _openslide
    if _openslide is not None:
        return _openslide
    try:
        import openslide

        _openslide = openslide
        return openslide
    except ImportError:
        raise ImportError(
            "openslide-python is required for format conversion. "
            "Install it with: pip install pathsafe[convert]"
        ) from None


def _require_tifffile() -> Any:
    global _tifffile
    if _tifffile is not None:
        return _tifffile
    try:
        import tifffile

        _tifffile = tifffile
        return tifffile
    except ImportError:
        raise ImportError(
            "tifffile is required for pyramidal TIFF output. "
            "Install it with: pip install pathsafe[convert]"
        ) from None


def _require_numpy() -> Any:
    global _numpy
    if _numpy is not None:
        return _numpy
    try:
        import numpy

        _numpy = numpy
        return numpy
    except ImportError:
        raise ImportError(
            "numpy is required for format conversion. "
            "Install it with: pip install pathsafe[convert]"
        ) from None


def convert_file(
    source: Path,
    output_path: Path,
    target_format: str = "tiff",
    tile_size: int = 256,
    quality: int = 90,
    extract: str | None = None,
    deidentify: bool = False,
    reset_timestamps: bool = False,
) -> ConversionResult:
    """Convert a single WSI file to a target format.

    Args:
        source: Path to the source WSI file.
        output_path: Where to write the converted file.
        target_format: Output format -- "tiff", "png", or "jpeg".
        tile_size: Tile size in pixels for pyramidal TIFF (default 256).
        quality: JPEG compression quality 1-100 (default 90).
        extract: If set, extract an associated image instead of converting.
                 One of "label", "macro", "thumbnail".
        deidentify: If True, run PathSafe deidentification on the output.
        reset_timestamps: If True, reset file timestamps to epoch after conversion.

    Returns:
        ConversionResult with details of the conversion.
    """
    source = Path(source)
    output_path = Path(output_path)
    t0 = time.perf_counter()

    openslide = _require_openslide()

    # Detect source format
    source_format = openslide.OpenSlide.detect_format(str(source))
    if source_format is None:
        source_format = source.suffix.lstrip(".").lower() or "unknown"

    result = ConversionResult(
        source_path=source,
        output_path=output_path,
        source_format=source_format,
        target_format=target_format,
    )

    try:
        if not source.exists():
            result.error = f"File not found: {source}"
            return result

        # Create output directory
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if extract:
            _extract_associated_image(source, output_path, extract)
            result.levels_written = 1
        elif target_format == "tiff":
            levels = _convert_to_pyramidal_tiff(source, output_path, tile_size, quality)
            result.levels_written = levels
        elif target_format in ("png", "jpeg"):
            _convert_to_single_image(source, output_path, target_format, quality=quality)
            result.levels_written = 1
        else:
            result.error = f"Unsupported target format: {target_format}"
            return result

        # Optional deidentification
        if deidentify and result.error is None:
            try:
                from pathsafe.deidentifier import deidentify_file

                anon_result = deidentify_file(output_path, verify=True)
                if anon_result.error:
                    result.error = (
                        f"Conversion succeeded but deidentification failed: {anon_result.error}"
                    )
                else:
                    result.deidentified = anon_result.findings_cleared > 0 or anon_result.verified
            except Exception as e:
                result.error = (
                    f"Conversion succeeded but deidentification failed: {_sanitize_error(e)}"
                )

    except ImportError:
        raise
    except Exception as e:
        logger.error("convert_file failed for %s: %s", source.name, _sanitize_error(e))
        result.error = _sanitize_error(e)

    # Reset filesystem timestamps to epoch (removes temporal PHI)
    if reset_timestamps and result.error is None and output_path.exists():
        try:
            os.utime(output_path, (0, 0))
        except OSError as e:
            logger.warning("Failed to reset timestamp for %s: %s", output_path, e)

    result.conversion_time_ms = (time.perf_counter() - t0) * 1000
    return result


def _convert_to_pyramidal_tiff(
    source: Path,
    output_path: Path,
    tile_size: int,
    quality: int,
) -> int:
    """Convert a WSI to a pyramidal BigTIFF.

    Streams tiles one at a time from OpenSlide directly to TiffWriter,
    keeping memory usage proportional to a single tile rather than an
    entire pyramid level.

    Returns the number of pyramid levels written.
    """
    openslide = _require_openslide()
    tifffile = _require_tifffile()
    np = _require_numpy()

    # Determine compression -- JPEG requires imagecodecs, fall back to deflate
    try:
        import imagecodecs  # noqa: F401

        use_jpeg = True
    except ImportError:
        use_jpeg = False

    slide = openslide.OpenSlide(str(source))
    try:
        width, height = slide.dimensions

        # Read slide properties for TIFF metadata
        mpp_x = slide.properties.get("openslide.mpp-x")
        mpp_y = slide.properties.get("openslide.mpp-y")
        objective = slide.properties.get("openslide.objective-power")

        # Compute resolution in pixels per centimeter (for TIFF ResolutionUnit=3)
        resolution = None
        if mpp_x and mpp_y:
            try:
                res_x = 10000.0 / float(mpp_x)  # pixels per cm
                res_y = 10000.0 / float(mpp_y)
                resolution = (res_x, res_y)
            except (ValueError, ZeroDivisionError):
                pass

        # Use OpenSlide's existing pyramid levels
        level_count = slide.level_count
        level_dims = slide.level_dimensions
        level_downsamples = slide.level_downsamples

        with tifffile.TiffWriter(str(output_path), bigtiff=True) as tif:
            for level in range(level_count):
                lw, lh = level_dims[level]
                is_base = level == 0
                subfiletype = 0 if is_base else 1
                downsample = level_downsamples[level]

                # Build metadata dict
                metadata = {}
                if objective:
                    metadata["magnification"] = objective

                # Resolution tag args
                resolution_args = {}
                if resolution and is_base:
                    resolution_args["resolution"] = resolution
                    resolution_args["resolutionunit"] = 3  # centimeter
                elif resolution:
                    resolution_args["resolution"] = (
                        resolution[0] / downsample,
                        resolution[1] / downsample,
                    )
                    resolution_args["resolutionunit"] = 3

                # Compression kwargs shared by every tile
                if use_jpeg:
                    compress_kwargs = dict(
                        compression="jpeg",
                        compressionargs={"level": quality},
                        photometric="ycbcr",
                    )
                else:
                    compress_kwargs = dict(
                        compression="deflate",
                        photometric="rgb",
                    )

                # Stream tiles: iterate row-by-row, column-by-column,
                # reading one tile from OpenSlide and writing it directly
                # to TiffWriter.  Memory stays at O(tile_size^2).
                _stream_level_tiles(
                    tif,
                    slide,
                    level,
                    lw,
                    lh,
                    tile_size,
                    downsample,
                    np,
                    subfiletype=subfiletype,
                    metadata=metadata if metadata else None,
                    resolution_args=resolution_args,
                    compress_kwargs=compress_kwargs,
                )

        return level_count
    finally:
        slide.close()


def _stream_level_tiles(
    tif: Any,
    slide: Any,
    level: int,
    width: int,
    height: int,
    tile_size: int,
    downsample: float,
    np: Any,
    *,
    subfiletype: int,
    metadata: dict | None,
    resolution_args: dict,
    compress_kwargs: dict,
) -> None:
    """Read tiles one at a time from OpenSlide and write each to *tif*.

    Uses an iterator (generator) so that only one tile lives in memory
    at any given time.
    """

    def _tile_iterator():
        """Yield tile_array for every tile in the level."""
        for y in range(0, height, tile_size):
            for x in range(0, width, tile_size):
                tw = min(tile_size, width - x)
                th = min(tile_size, height - y)

                # OpenSlide read_region wants level-0 coordinates
                x0 = int(x * downsample)
                y0 = int(y * downsample)

                tile = slide.read_region((x0, y0), level, (tw, th))
                tile_rgb = tile.convert("RGB")
                tile_arr = np.asarray(tile_rgb)

                # Pad partial edge tiles to full tile_size so TiffWriter
                # gets uniform tile dimensions.
                if th < tile_size or tw < tile_size:
                    padded = np.zeros((tile_size, tile_size, 3), dtype=np.uint8)
                    padded[:th, :tw, :] = tile_arr
                    tile_arr = padded

                yield tile_arr

    # Compute the number of tiles so TiffWriter knows the page shape
    tiles_across = -(-width // tile_size)  # ceiling division
    tiles_down = -(-height // tile_size)

    # shape is the full page size rounded up to tile boundaries
    shape = (tiles_down * tile_size, tiles_across * tile_size, 3)

    tif.write(
        _tile_iterator(),
        shape=shape,
        dtype=np.uint8,
        tile=(tile_size, tile_size),
        subfiletype=subfiletype,
        metadata=metadata,
        **resolution_args,
        **compress_kwargs,
    )


def _convert_to_single_image(
    source: Path,
    output_path: Path,
    fmt: str,
    level: int = 0,
    quality: int = 90,
) -> None:
    """Convert a single level of a WSI to PNG or JPEG using Pillow.

    Automatically selects a lower pyramid level if the requested level
    exceeds 25 megapixels (e.g., 5000x5000), keeping output practical.
    """
    openslide = _require_openslide()

    slide = openslide.OpenSlide(str(source))
    try:
        lw, lh = slide.level_dimensions[level]

        # Auto-downscale: PNG/JPEG shouldn't exceed MAX_SINGLE_IMAGE_PIXELS
        if lw * lh > MAX_SINGLE_IMAGE_PIXELS:
            # Pick the highest-resolution level that fits within the limit
            for lvl in range(slide.level_count):
                w, h = slide.level_dimensions[lvl]
                if w * h <= MAX_SINGLE_IMAGE_PIXELS:
                    level = lvl
                    lw, lh = w, h
                    break
            else:
                # Even the smallest level is too big -- use it anyway
                level = slide.level_count - 1
                lw, lh = slide.level_dimensions[level]

        region = slide.read_region((0, 0), level, (lw, lh))
        img = region.convert("RGB")

        save_kwargs = {}
        if fmt == "jpeg":
            save_kwargs["quality"] = quality
            img.save(str(output_path), format="JPEG", **save_kwargs)
        else:
            img.save(str(output_path), format=fmt.upper())
    finally:
        slide.close()


def _extract_associated_image(
    source: Path,
    output_path: Path,
    image_name: str,
) -> None:
    """Extract an associated image (label, macro, thumbnail) from a WSI."""
    openslide = _require_openslide()

    slide = openslide.OpenSlide(str(source))
    try:
        available = list(slide.associated_images.keys())
        if image_name not in slide.associated_images:
            raise ValueError(f"Associated image '{image_name}' not found. Available: {available}")

        img = slide.associated_images[image_name]
        img = img.convert("RGB")

        # Determine format from output extension
        suffix = output_path.suffix.lower()
        fmt_map = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".tif": "TIFF", ".tiff": "TIFF"}
        fmt = fmt_map.get(suffix, "PNG")

        img.save(str(output_path), format=fmt)
    finally:
        slide.close()


def convert_batch(
    input_path: Path,
    output_dir: Path,
    target_format: str = "tiff",
    tile_size: int = 256,
    quality: int = 90,
    deidentify: bool = False,
    format_filter: str | None = None,
    progress_callback: Callable[[int, int, Path, ConversionResult], None] | None = None,
    workers: int = 1,
    reset_timestamps: bool = False,
    stop_check: Callable[[], bool] | None = None,
) -> ConversionBatchResult:
    """Convert a batch of WSI files.

    Args:
        input_path: File or directory containing WSI files.
        output_dir: Directory for converted output files.
        target_format: Output format -- "tiff", "png", or "jpeg".
        tile_size: Tile size in pixels for pyramidal TIFF.
        quality: JPEG compression quality 1-100.
        deidentify: Run PathSafe deidentification on each converted file.
        format_filter: Only process files of this format.
        progress_callback: Called with (index, total, filepath, result) after each file.
        workers: Number of parallel workers. 1 = sequential (default).
        reset_timestamps: If True, reset file timestamps to epoch after conversion.

    Returns:
        ConversionBatchResult with summary statistics.
    """
    from pathsafe.deidentifier import collect_wsi_files

    input_path = Path(input_path)
    output_dir = Path(output_dir)
    t0 = time.perf_counter()

    files = collect_wsi_files(input_path, format_filter)
    total = len(files)

    batch = ConversionBatchResult(total_files=total)

    # Determine output extension
    ext_map = {"tiff": ".tiff", "png": ".png", "jpeg": ".jpg"}
    out_ext = ext_map.get(target_format, ".tiff")

    # Build (source, output) pairs
    file_pairs = []
    for filepath in files:
        if input_path.is_dir():
            relative = filepath.relative_to(input_path)
            out = output_dir / relative.with_suffix(out_ext)
        else:
            out = output_dir / (filepath.stem + out_ext)
        file_pairs.append((filepath, out))

    def do_one(filepath: Path, out: Path) -> ConversionResult:
        return convert_file(
            filepath,
            out,
            target_format=target_format,
            tile_size=tile_size,
            quality=quality,
            deidentify=deidentify,
            reset_timestamps=reset_timestamps,
        )

    if workers > 1 and total > 1:
        results = _convert_batch_parallel(
            file_pairs,
            do_one,
            workers,
            progress_callback,
            batch,
            stop_check=stop_check,
        )
    else:
        results = _convert_batch_sequential(
            file_pairs,
            do_one,
            progress_callback,
            batch,
            stop_check=stop_check,
        )

    batch.results = results
    batch.total_time_seconds = time.perf_counter() - t0
    return batch


def _convert_batch_sequential(
    file_pairs: list[tuple[Path, Path]],
    do_one: Callable[[Path, Path], ConversionResult],
    progress_callback: Callable[[int, int, Path, ConversionResult], None] | None,
    batch: ConversionBatchResult,
    stop_check: Callable[[], bool] | None = None,
) -> list[ConversionResult]:
    results = []
    total = len(file_pairs)

    for i, (filepath, out) in enumerate(file_pairs):
        if stop_check and stop_check():
            batch.files_errored += total - len(results)
            break

        try:
            result = do_one(filepath, out)
        except Exception as e:
            result = ConversionResult(
                source_path=filepath,
                output_path=out,
                source_format="unknown",
                target_format="unknown",
                error=_sanitize_error(e),
            )

        results.append(result)
        _update_batch_stats(batch, result)

        if progress_callback:
            progress_callback(i + 1, total, filepath, result)

    return results


def _convert_batch_parallel(
    file_pairs: list[tuple[Path, Path]],
    do_one: Callable[[Path, Path], ConversionResult],
    workers: int,
    progress_callback: Callable[[int, int, Path, ConversionResult], None] | None,
    batch: ConversionBatchResult,
    stop_check: Callable[[], bool] | None = None,
) -> list[ConversionResult | None]:
    total = len(file_pairs)
    results = [None] * total
    lock = threading.Lock()
    completed_count = [0]

    def process_one(index: int, filepath: Path, out: Path) -> tuple[int, ConversionResult]:
        if stop_check and stop_check():
            return index, ConversionResult(
                source_path=filepath,
                output_path=out,
                source_format="unknown",
                target_format="unknown",
                error="Stopped by user",
            )
        try:
            return index, do_one(filepath, out)
        except Exception as e:
            return index, ConversionResult(
                source_path=filepath,
                output_path=out,
                source_format="unknown",
                target_format="unknown",
                error=_sanitize_error(e),
            )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for i, (filepath, out) in enumerate(file_pairs):
            future = executor.submit(process_one, i, filepath, out)
            futures[future] = (i, filepath)

        for future in as_completed(futures):
            idx, filepath = futures[future]
            index, result = future.result()
            results[index] = result

            with lock:
                _update_batch_stats(batch, result)
                completed_count[0] += 1
                if progress_callback:
                    progress_callback(completed_count[0], total, filepath, result)

    return results


def _update_batch_stats(batch: ConversionBatchResult, result: ConversionResult) -> None:
    if result.error:
        batch.files_errored += 1
    else:
        batch.files_converted += 1
