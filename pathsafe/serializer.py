"""File serialization and renaming for deidentified WSI files.

Provides three rename modes:
- AUTO: Sequential numbering (ANON_0001.ndpi, ANON_0002.svs, ...)
- MAPPING: Lookup-based renaming from a CSV file
- TEMPLATE: Pattern-based naming with restricted token substitution

File filtering:
- --include / --exclude: glob-style filename patterns (fnmatch)
- --filter-file: external file listing which filenames to process
  Accepts plain text (one filename per line), CSV (must have a column whose
  header contains "file"), or JSON (list of filenames, or dict of
  {filename: anything}).  Filtering happens BEFORE rename-plan computation,
  so sequential counters have no gaps.

Design decisions:
- Final names are computed UPFRONT before deidentification, not post-rename
- Template uses str.replace() on allowlisted tokens, NOT str.format()
- Mapping files are validated entirely before any processing begins
- Manifest is embedded in the certificate JSON and also written as standalone CSV
"""

import csv
import fnmatch
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File filtering
# ---------------------------------------------------------------------------


def load_filter_file(path: Path) -> set[str]:
    """Load a filter file and return a set of filenames (basenames) to include.

    Supports three formats, auto-detected by extension and content:

    - **Plain text** (`.txt` or fallback): one filename per line, blank
      lines and ``#`` comments ignored.
    - **CSV** (`.csv`): reads the first column whose header contains the
      substring ``file`` (case-insensitive).  Falls back to the first
      column if no header matches.
    - **JSON** (`.json``): accepts a list of filename strings **or** a dict
      whose keys are filenames (values are ignored — lets you reuse the
      ``{filename: stain}`` format from OCR classification outputs).

    Returns:
        Set of filename basenames (no directory components).
    """
    path = Path(path)
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")

    if suffix == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            return {Path(f).name for f in data if isinstance(f, str) and f.strip()}
        if isinstance(data, dict):
            return {Path(k).name for k in data if isinstance(k, str) and k.strip()}
        raise ValueError(f"Filter JSON must be a list or dict, got {type(data).__name__}")

    if suffix == ".csv":
        reader = csv.DictReader(text.splitlines())
        if reader.fieldnames:
            # Find column with "file" in the header
            col = next(
                (c for c in reader.fieldnames if "file" in c.lower()),
                reader.fieldnames[0],
            )
            return {Path(row[col]).name for row in reader if row.get(col, "").strip()}
        raise ValueError("Filter CSV is empty or has no headers")

    # Plain text fallback
    names: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(Path(line).name)
    return names


def apply_filters(
    files: list[Path],
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    filter_file: Path | None = None,
) -> list[Path]:
    """Filter a list of file paths by include/exclude globs and/or a filter file.

    Filtering order:
    1. ``filter_file`` (if provided): keep only files whose basename is in the set.
    2. ``include`` patterns: keep only files matching at least one pattern.
    3. ``exclude`` patterns: drop files matching any pattern.

    Patterns use :func:`fnmatch.fnmatch` (case-insensitive on Windows,
    case-sensitive on Linux).  Use ``*HE*`` to match any file containing
    "HE" in its name, ``*.ndpi`` to match by extension, etc.

    Args:
        files: Input file paths.
        include: Glob patterns — a file must match at least one to be kept.
        exclude: Glob patterns — any match causes the file to be dropped.
        filter_file: Path to a text/CSV/JSON file listing filenames to include.

    Returns:
        Filtered list, preserving original order.
    """
    result = list(files)

    # Step 1: filter-file (whitelist)
    if filter_file is not None:
        allowed = load_filter_file(filter_file)
        before = len(result)
        result = [f for f in result if f.name in allowed]
        dropped = before - len(result)
        if dropped:
            logger.info(
                "Filter file: kept %d of %d files (%d excluded)", len(result), before, dropped
            )

    # Step 2: include patterns (whitelist — must match at least one)
    if include:
        before = len(result)
        result = [f for f in result if any(fnmatch.fnmatch(f.name, pat) for pat in include)]
        dropped = before - len(result)
        if dropped:
            logger.info(
                "Include filter: kept %d of %d files (%d excluded)", len(result), before, dropped
            )

    # Step 3: exclude patterns (blacklist — any match drops the file)
    if exclude:
        before = len(result)
        result = [f for f in result if not any(fnmatch.fnmatch(f.name, pat) for pat in exclude)]
        dropped = before - len(result)
        if dropped:
            logger.info("Exclude filter: dropped %d of %d files", dropped, before)

    return result


class RenameMode(Enum):
    """File renaming mode."""

    KEEP = "keep"  # Preserve original filename
    AUTO = "auto"  # Sequential numbering
    MAPPING = "mapping"  # CSV lookup
    TEMPLATE = "template"  # Pattern-based


@dataclass
class SerializerConfig:
    """Configuration for file serialization."""

    mode: RenameMode = RenameMode.KEEP

    # Auto mode settings
    prefix: str = "ANON"
    start: int = 1
    digits: int = 4
    separator: str = "_"

    # Mapping mode
    mapping_path: Path | None = None
    unmatched: str = "skip"  # "skip" | "auto" | "keep"

    # Template mode
    template: str = "{prefix}_{index}.{ext}"

    # Manifest output
    manifest_path: Path | None = None

    # Grouping: organize output into per-patient/per-group subfolders
    grouping_key: str | None = None  # column name in lookup for folder grouping
    grouping_map: dict[str, str] = field(default_factory=dict, repr=False)
    # {source_filename: group_id} — populated by load_grouping or classify

    # Cached mapping data (populated by load_mapping)
    _mapping: dict[str, str] = field(default_factory=dict, repr=False)


# Allowed tokens for template mode (security: no str.format, no attribute access)
_TEMPLATE_TOKENS = {"prefix", "index", "ext", "sha8", "format", "date"}

# Characters forbidden in output filenames (security: path traversal, OS reserved)
_FORBIDDEN_CHARS = re.compile(r'[/\\<>:"|?*\x00-\x1f]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{n}{i}" for n in ("COM", "LPT") for i in range(1, 10)
}


def _sanitize_group_id(group_id: str) -> str:
    """Make a group ID safe for use as a directory name.

    Strips/replaces forbidden characters (same set as ``_validate_filename``),
    replaces path separators (``/`` and ``\\``), and truncates to 100 chars.

    Raises:
        ValueError: If the sanitized result is empty.
    """
    sanitized = group_id.strip()
    # Replace path separators with underscores
    sanitized = sanitized.replace("/", "_").replace("\\", "_")
    # Strip remaining forbidden characters
    sanitized = _FORBIDDEN_CHARS.sub("_", sanitized)
    # Collapse runs of underscores
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    # Truncate to 100 characters
    sanitized = sanitized[:100]
    if not sanitized or sanitized in (".", ".."):
        raise ValueError(f"Group ID '{group_id}' is empty or unsafe after sanitization")
    return sanitized


def load_mapping(config: SerializerConfig) -> dict[str, str]:
    """Load and validate a CSV mapping file.

    Expected columns: source_filename, output_name

    Raises ValueError on: missing columns, duplicate sources, duplicate outputs,
    empty values, path traversal in output names.
    """
    if config.mapping_path is None:
        raise ValueError("No mapping file specified")

    path = Path(config.mapping_path)
    if not path.exists():
        raise FileNotFoundError(f"Mapping file not found: {path}")

    mapping: dict[str, str] = {}
    output_names_seen: dict[str, str] = {}  # output_name → source for dup check

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("Empty or unreadable CSV file")

        # Normalize column names (strip whitespace, lowercase)
        cols = {c.strip().lower(): c for c in reader.fieldnames}
        src_col = cols.get("source_filename")
        out_col = cols.get("output_name")

        if src_col is None or out_col is None:
            available = ", ".join(reader.fieldnames)
            raise ValueError(
                f"CSV must have columns 'source_filename' and 'output_name'. Found: {available}"
            )

        for row_num, row in enumerate(reader, start=2):
            src = row[src_col].strip()
            out = row[out_col].strip()

            if not src or not out:
                raise ValueError(f"Row {row_num}: empty source or output name")

            if src in mapping:
                raise ValueError(
                    f"Row {row_num}: duplicate source_filename '{src}' "
                    f"(first seen mapping to '{mapping[src]}')"
                )

            if out in output_names_seen:
                raise ValueError(
                    f"Row {row_num}: duplicate output_name '{out}' "
                    f"(already used by '{output_names_seen[out]}')"
                )

            # Security: reject path traversal and forbidden characters
            _validate_filename(out, f"Row {row_num}")

            mapping[src] = out
            output_names_seen[out] = src

    config._mapping = mapping
    return mapping


def compute_output_name(
    config: SerializerConfig,
    source_path: Path,
    index: int,
    file_hash: str | None = None,
    detected_format: str | None = None,
) -> str:
    """Compute the output filename for a given source file and config.

    Args:
        config: Serializer configuration.
        source_path: Original source file path.
        index: Sequential index (0-based internally, displayed as start+offset).
        file_hash: Optional SHA-256 hash of the source file.
        detected_format: Optional detected format name (e.g., "ndpi", "svs").

    Returns:
        The output filename (basename only, no directory).

    Raises:
        ValueError: If the resulting filename is invalid.
        KeyError: If mapping mode and source not found (when unmatched="skip").
    """
    ext = source_path.suffix.lstrip(".")

    if config.mode == RenameMode.KEEP:
        return source_path.name

    elif config.mode == RenameMode.AUTO:
        num = config.start + index
        counter = str(num).zfill(config.digits)
        name = f"{config.prefix}{config.separator}{counter}.{ext}"

    elif config.mode == RenameMode.MAPPING:
        src_name = source_path.name
        if src_name in config._mapping:
            name = config._mapping[src_name]
            # Ensure extension matches or is preserved
            mapped_ext = Path(name).suffix.lstrip(".")
            if not mapped_ext:
                name = f"{name}.{ext}"
        elif config.unmatched == "auto":
            num = config.start + index
            counter = str(num).zfill(config.digits)
            name = f"{config.prefix}{config.separator}{counter}.{ext}"
        elif config.unmatched == "keep":
            name = src_name
        else:
            raise KeyError(f"Source '{src_name}' not found in mapping file")

    elif config.mode == RenameMode.TEMPLATE:
        name = _apply_template(config, source_path, index, ext, file_hash, detected_format)

    else:
        return source_path.name

    _validate_filename(name, f"Generated name for '{source_path.name}'")
    return name


def _apply_template(
    config: SerializerConfig,
    source_path: Path,
    index: int,
    ext: str,
    file_hash: str | None,
    detected_format: str | None,
) -> str:
    """Apply template with restricted token substitution (no str.format)."""
    num = config.start + index
    counter = str(num).zfill(config.digits)
    sha8 = (file_hash or "00000000")[:8]
    fmt = detected_format or ext
    date = datetime.now().strftime("%Y%m%d")

    result = config.template
    result = result.replace("{prefix}", config.prefix)
    result = result.replace("{index}", counter)
    result = result.replace("{ext}", ext)
    result = result.replace("{sha8}", sha8)
    result = result.replace("{format}", fmt)
    result = result.replace("{date}", date)

    # Auto-append extension if result has none
    if "." not in Path(result).name:
        result = f"{result}.{ext}"

    return result


def _validate_filename(name: str, context: str = "") -> None:
    """Validate that a filename is safe. Raises ValueError if not."""
    if not name or name.strip() in ("", ".", ".."):
        raise ValueError(f"{context}: empty or dangerous filename '{name}'")

    # Reject unresolved template tokens (security: indicates injection attempt)
    if "{" in name or "}" in name:
        raise ValueError(f"{context}: filename '{name}' contains unresolved template tokens")

    if _FORBIDDEN_CHARS.search(name):
        raise ValueError(f"{context}: filename '{name}' contains forbidden characters")

    stem = Path(name).stem.upper()
    if stem in _RESERVED_NAMES:
        raise ValueError(f"{context}: filename '{name}' uses a reserved name")

    if len(name) > 255:
        raise ValueError(f"{context}: filename '{name}' exceeds 255 characters")


def preview_names(
    config: SerializerConfig,
    source_paths: list[Path],
    count: int = 3,
) -> list[tuple[str, str]]:
    """Generate preview of rename results (original → new) for up to `count` files.

    Uses the same sort order as compute_rename_plan() (alphabetical by name)
    so the preview matches the actual output. Only iterates until `count`
    successful previews are found.
    """
    previews = []
    sorted_paths = sorted(source_paths, key=lambda p: p.name.lower())
    idx = 0

    for path in sorted_paths:
        if len(previews) >= count:
            break
        try:
            new_name = compute_output_name(config, path, idx)
            previews.append((path.name, new_name))
            idx += 1
        except (KeyError, ValueError):
            continue  # Skip files that can't be renamed (e.g., not in mapping)

    return previews


def compute_rename_plan(
    config: SerializerConfig,
    source_paths: list[Path],
    output_dir: Path,
) -> list[tuple[Path, Path]]:
    """Compute the full rename plan: list of (source_path, final_output_path).

    Source paths are sorted alphabetically for deterministic index assignment.
    This is called BEFORE deidentification to determine final output paths upfront.

    Returns:
        List of (source_path, final_output_path) tuples.
        Files that can't be renamed (mapping miss with unmatched="skip") are excluded.
    """
    sorted_sources = sorted(source_paths, key=lambda p: p.name.lower())
    plan = []
    idx = 0

    for source in sorted_sources:
        try:
            new_name = compute_output_name(config, source, idx)
            # Insert group subfolder when grouping_map is populated
            if config.grouping_map:
                group_id = config.grouping_map.get(source.name, "")
                if group_id:
                    group_id = _sanitize_group_id(group_id)
                    final_path = output_dir / group_id / new_name
                else:
                    final_path = output_dir / new_name
            else:
                final_path = output_dir / new_name
            plan.append((source, final_path))
            idx += 1
        except KeyError:
            continue  # Mapping miss with unmatched="skip"

    # Check for collisions in the plan
    seen_outputs = {}
    for source, output in plan:
        key = str(output).lower()
        if key in seen_outputs:
            raise ValueError(
                f"Output collision: both '{seen_outputs[key].name}' and "
                f"'{source.name}' would be written to '{output.name}'"
            )
        seen_outputs[key] = source

    return plan


def write_manifest(
    plan: list[tuple[Path, Path]],
    output_path: Path,
    checksums: dict[str, str] | None = None,
) -> Path:
    """Write a manifest CSV mapping source → output filenames.

    Args:
        plan: List of (source_path, final_output_path) tuples.
        output_path: Where to write the manifest CSV.
        checksums: Optional dict of {output_filename: sha256_hex}.

    Returns:
        Path to the written manifest file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    from pathsafe.scanner import scan_filename_for_phi

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "serial_id",
                "original_filename",
                "output_filename",
                "sha256",
            ]
        )
        for source, output in plan:
            serial_id = output.stem
            sha = ""
            if checksums and output.name in checksums:
                sha = checksums[output.name]
            # Emit only the filename stem -- never full directory paths.
            # Mask the original filename if it contains PHI patterns.
            src_label = source.stem
            if scan_filename_for_phi(source):
                src_label = "[PHI_FILENAME]"
            writer.writerow(
                [
                    serial_id,
                    src_label,
                    output.name,
                    sha,
                ]
            )

    return output_path
