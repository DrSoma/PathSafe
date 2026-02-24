"""Optional OpenSlide integration for deeper format detection and metadata reading.

This module provides extra capabilities when openslide-python is installed:
- Format detection via OpenSlide's vendor detection
- Reading slide properties (dimensions, magnification, vendor)
- Accessing associated images (label, macro, thumbnail)

All functions gracefully handle the case where OpenSlide is not installed.
"""

from pathlib import Path
from typing import Dict, List, Optional

try:
    import openslide
    HAS_OPENSLIDE = True
except ImportError:
    HAS_OPENSLIDE = False


def is_available() -> bool:
    """Check if OpenSlide is installed and available."""
    return HAS_OPENSLIDE


def detect_vendor(filepath: Path) -> Optional[str]:
    """Detect the slide vendor using OpenSlide.

    Returns vendor string (e.g., "hamamatsu", "aperio", "mirax",
    "ventana", "leica", "generic-tiff") or None.
    """
    if not HAS_OPENSLIDE:
        return None
    try:
        return openslide.OpenSlide.detect_format(str(filepath))
    except Exception:
        return None


def get_properties(filepath: Path) -> Dict[str, str]:
    """Read all slide properties via OpenSlide.

    Returns a dict of property name -> value. Common properties include:
    - openslide.vendor
    - openslide.objective-power
    - openslide.mpp-x, openslide.mpp-y (microns per pixel)
    - openslide.level-count
    - Format-specific properties (e.g., hamamatsu.*, aperio.*)
    """
    if not HAS_OPENSLIDE:
        return {}
    try:
        with openslide.OpenSlide(str(filepath)) as slide:
            return dict(slide.properties)
    except Exception:
        return {}


def get_associated_image_names(filepath: Path) -> List[str]:
    """List available associated images (e.g., 'label', 'macro', 'thumbnail').

    Returns empty list if OpenSlide is not available or file can't be opened.
    """
    if not HAS_OPENSLIDE:
        return []
    try:
        with openslide.OpenSlide(str(filepath)) as slide:
            return list(slide.associated_images.keys())
    except Exception:
        return []


def has_label_image(filepath: Path) -> bool:
    """Check if the slide has a label associated image."""
    return 'label' in get_associated_image_names(filepath)


def has_macro_image(filepath: Path) -> bool:
    """Check if the slide has a macro associated image."""
    return 'macro' in get_associated_image_names(filepath)


def get_slide_info(filepath: Path) -> Dict:
    """Get comprehensive slide information via OpenSlide.

    Returns a dict with vendor, dimensions, magnification, level info,
    associated images, and all properties.
    """
    if not HAS_OPENSLIDE:
        return {'openslide_available': False}

    info = {'openslide_available': True}
    try:
        with openslide.OpenSlide(str(filepath)) as slide:
            info['vendor'] = slide.properties.get(
                'openslide.vendor', 'unknown')
            info['level_count'] = slide.level_count
            info['dimensions'] = slide.dimensions
            info['level_dimensions'] = slide.level_dimensions
            info['objective_power'] = slide.properties.get(
                'openslide.objective-power')
            info['mpp_x'] = slide.properties.get('openslide.mpp-x')
            info['mpp_y'] = slide.properties.get('openslide.mpp-y')
            info['associated_images'] = list(
                slide.associated_images.keys())
            info['property_count'] = len(slide.properties)
    except Exception as e:
        info['error'] = str(e)

    return info
