"""Tests for the serializer module (file renaming and manifest generation)."""

import csv
from pathlib import Path

import pytest

from pathsafe.serializer import (
    RenameMode,
    SerializerConfig,
    _sanitize_group_id,
    _validate_filename,
    compute_output_name,
    compute_rename_plan,
    load_mapping,
    preview_names,
    write_manifest,
)


class TestAutoMode:
    """Auto-sequential renaming: ANON_0001.ndpi, ANON_0002.svs, ..."""

    def test_basic_numbering(self):
        config = SerializerConfig(mode=RenameMode.AUTO)
        name = compute_output_name(config, Path("slide.ndpi"), 0)
        assert name == "ANON_0001.ndpi"

    def test_sequential(self):
        config = SerializerConfig(mode=RenameMode.AUTO, start=1, digits=4)
        names = [compute_output_name(config, Path(f"s{i}.svs"), i) for i in range(3)]
        assert names == ["ANON_0001.svs", "ANON_0002.svs", "ANON_0003.svs"]

    def test_custom_prefix(self):
        config = SerializerConfig(mode=RenameMode.AUTO, prefix="STUDY")
        assert compute_output_name(config, Path("x.ndpi"), 0) == "STUDY_0001.ndpi"

    def test_custom_start(self):
        config = SerializerConfig(mode=RenameMode.AUTO, start=100)
        assert compute_output_name(config, Path("x.svs"), 0) == "ANON_0100.svs"

    def test_custom_digits(self):
        config = SerializerConfig(mode=RenameMode.AUTO, digits=6)
        assert compute_output_name(config, Path("x.ndpi"), 0) == "ANON_000001.ndpi"

    def test_custom_separator(self):
        config = SerializerConfig(mode=RenameMode.AUTO, separator="-")
        assert compute_output_name(config, Path("x.svs"), 0) == "ANON-0001.svs"

    def test_preserves_extension(self):
        config = SerializerConfig(mode=RenameMode.AUTO)
        assert compute_output_name(config, Path("a.ndpi"), 0).endswith(".ndpi")
        assert compute_output_name(config, Path("b.svs"), 0).endswith(".svs")
        assert compute_output_name(config, Path("c.tiff"), 0).endswith(".tiff")


class TestKeepMode:
    def test_keep_returns_original(self):
        config = SerializerConfig(mode=RenameMode.KEEP)
        assert compute_output_name(config, Path("AS-24-123456.ndpi"), 0) == "AS-24-123456.ndpi"


class TestTemplateMode:
    def test_basic_template(self):
        config = SerializerConfig(
            mode=RenameMode.TEMPLATE,
            template="{prefix}_{index}.{ext}",
            prefix="SLIDE",
        )
        assert compute_output_name(config, Path("x.ndpi"), 0) == "SLIDE_0001.ndpi"

    def test_date_token(self):
        config = SerializerConfig(
            mode=RenameMode.TEMPLATE,
            template="{prefix}_{date}_{index}.{ext}",
        )
        name = compute_output_name(config, Path("x.svs"), 0)
        # Should contain 8-digit date
        parts = name.split("_")
        assert len(parts[1]) == 8
        assert parts[1].isdigit()

    def test_sha8_token(self):
        config = SerializerConfig(
            mode=RenameMode.TEMPLATE,
            template="slide_{sha8}.{ext}",
        )
        name = compute_output_name(config, Path("x.ndpi"), 0, file_hash="abcdef1234567890")
        assert name == "slide_abcdef12.ndpi"

    def test_auto_appends_extension(self):
        """Template without {ext} auto-appends the original extension."""
        config = SerializerConfig(
            mode=RenameMode.TEMPLATE,
            template="{prefix}_{index}",
        )
        name = compute_output_name(config, Path("x.svs"), 0)
        assert name.endswith(".svs")

    def test_no_str_format_injection(self):
        """Template tokens use str.replace, not str.format, so there is no attribute access.
        The injection attempt {prefix.__class__} does NOT match {prefix},
        so it remains as a literal and gets rejected by validation."""
        config = SerializerConfig(
            mode=RenameMode.TEMPLATE,
            template="{prefix.__class__}_{index}.{ext}",
            prefix="EVIL",
        )
        # Should raise because the unresolved token contains invalid chars
        with pytest.raises(ValueError):
            compute_output_name(config, Path("x.ndpi"), 0)


class TestMappingMode:
    def test_load_and_use(self, tmp_path):
        csv_file = tmp_path / "map.csv"
        csv_file.write_text(
            "source_filename,output_name\n"
            "slide1.ndpi,PATIENT_001.ndpi\n"
            "slide2.svs,PATIENT_002.svs\n"
        )

        config = SerializerConfig(
            mode=RenameMode.MAPPING,
            mapping_path=csv_file,
        )
        load_mapping(config)

        assert compute_output_name(config, Path("slide1.ndpi"), 0) == "PATIENT_001.ndpi"
        assert compute_output_name(config, Path("slide2.svs"), 1) == "PATIENT_002.svs"

    def test_missing_source_raises(self, tmp_path):
        csv_file = tmp_path / "map.csv"
        csv_file.write_text("source_filename,output_name\nslide1.ndpi,OUT.ndpi\n")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file, unmatched="skip")
        load_mapping(config)

        with pytest.raises(KeyError):
            compute_output_name(config, Path("not_in_mapping.ndpi"), 0)

    def test_unmatched_auto(self, tmp_path):
        csv_file = tmp_path / "map.csv"
        csv_file.write_text("source_filename,output_name\nslide1.ndpi,OUT.ndpi\n")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file, unmatched="auto")
        load_mapping(config)

        name = compute_output_name(config, Path("missing.svs"), 5)
        assert name == "ANON_0006.svs"

    def test_duplicate_source_rejects(self, tmp_path):
        csv_file = tmp_path / "map.csv"
        csv_file.write_text("source_filename,output_name\nslide.ndpi,A.ndpi\nslide.ndpi,B.ndpi\n")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file)
        with pytest.raises(ValueError, match="duplicate source_filename"):
            load_mapping(config)

    def test_duplicate_output_rejects(self, tmp_path):
        csv_file = tmp_path / "map.csv"
        csv_file.write_text("source_filename,output_name\na.ndpi,SAME.ndpi\nb.ndpi,SAME.ndpi\n")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file)
        with pytest.raises(ValueError, match="duplicate output_name"):
            load_mapping(config)

    def test_bom_handling(self, tmp_path):
        """CSV with UTF-8 BOM is handled correctly."""
        csv_file = tmp_path / "bom.csv"
        csv_file.write_bytes(b"\xef\xbb\xbfsource_filename,output_name\nslide.ndpi,OUT.ndpi\n")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file)
        mapping = load_mapping(config)
        assert "slide.ndpi" in mapping


class TestValidation:
    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError, match="forbidden"):
            _validate_filename("../../etc/passwd")

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            _validate_filename("")

    def test_dot_rejected(self):
        with pytest.raises(ValueError):
            _validate_filename("..")

    def test_reserved_name_rejected(self):
        with pytest.raises(ValueError, match="reserved"):
            _validate_filename("CON.ndpi")

    def test_normal_name_ok(self):
        _validate_filename("ANON_0001.ndpi")  # Should not raise


class TestLoadMappingEdgeCases:
    """Gaps 1-3: load_mapping error paths."""

    def test_missing_file_raises(self, tmp_path):
        """Gap 1: FileNotFoundError for nonexistent mapping file."""
        config = SerializerConfig(
            mode=RenameMode.MAPPING,
            mapping_path=tmp_path / "does_not_exist.csv",
        )
        with pytest.raises(FileNotFoundError):
            load_mapping(config)

    def test_missing_columns_raises(self, tmp_path):
        """Gap 2: CSV with wrong column names."""
        csv_file = tmp_path / "bad_cols.csv"
        csv_file.write_text("filename,new_name\nslide.ndpi,OUT.ndpi\n")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file)
        with pytest.raises(ValueError, match="source_filename"):
            load_mapping(config)

    def test_empty_csv_raises(self, tmp_path):
        """Gap 3a: Completely empty CSV."""
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file)
        with pytest.raises(ValueError, match="Empty"):
            load_mapping(config)

    def test_empty_values_in_row_raises(self, tmp_path):
        """Gap 3b: Row with empty source or output."""
        csv_file = tmp_path / "empty_vals.csv"
        csv_file.write_text("source_filename,output_name\n,OUT.ndpi\n")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file)
        with pytest.raises(ValueError, match="empty source"):
            load_mapping(config)

    def test_no_mapping_path_raises(self):
        """Gap extra: mapping_path=None raises ValueError."""
        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=None)
        with pytest.raises(ValueError, match="No mapping file"):
            load_mapping(config)


class TestMappingUnmatchedKeep:
    """Gap 4: unmatched='keep' fallback branch."""

    def test_unmatched_keep_preserves_original(self, tmp_path):
        csv_file = tmp_path / "map.csv"
        csv_file.write_text("source_filename,output_name\nknown.ndpi,MAPPED.ndpi\n")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file, unmatched="keep")
        load_mapping(config)

        # Known file uses mapping
        assert compute_output_name(config, Path("known.ndpi"), 0) == "MAPPED.ndpi"
        # Unknown file keeps original name
        assert compute_output_name(config, Path("unknown.svs"), 1) == "unknown.svs"


class TestMappingExtensionAutoAppend:
    """Gap 5: mapped output_name without extension gets original ext appended."""

    def test_extension_appended_when_missing(self, tmp_path):
        csv_file = tmp_path / "map.csv"
        csv_file.write_text("source_filename,output_name\nslide.ndpi,PATIENT_001\n")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file)
        load_mapping(config)

        name = compute_output_name(config, Path("slide.ndpi"), 0)
        assert name == "PATIENT_001.ndpi"

    def test_extension_preserved_when_present(self, tmp_path):
        csv_file = tmp_path / "map.csv"
        csv_file.write_text("source_filename,output_name\nslide.ndpi,PATIENT_001.ndpi\n")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file)
        load_mapping(config)

        name = compute_output_name(config, Path("slide.ndpi"), 0)
        assert name == "PATIENT_001.ndpi"
        # Must NOT double the extension
        assert not name.endswith(".ndpi.ndpi")


class TestTemplateFormatToken:
    """Gap 6: {format} token and detected_format parameter."""

    def test_format_token_uses_detected_format(self):
        config = SerializerConfig(
            mode=RenameMode.TEMPLATE,
            template="{format}_{index}.{ext}",
        )
        name = compute_output_name(config, Path("file.ndpi"), 0, detected_format="ndpi")
        assert name == "ndpi_0001.ndpi"

    def test_format_token_falls_back_to_extension(self):
        """When detected_format is None, {format} uses the file extension."""
        config = SerializerConfig(
            mode=RenameMode.TEMPLATE,
            template="{format}_{index}.{ext}",
        )
        name = compute_output_name(config, Path("file.svs"), 0)
        assert name == "svs_0001.svs"


class TestTemplateSha8Default:
    """Gap 7: sha8 token when file_hash is None."""

    def test_sha8_default_when_no_hash(self):
        config = SerializerConfig(
            mode=RenameMode.TEMPLATE,
            template="slide_{sha8}.{ext}",
        )
        name = compute_output_name(config, Path("x.ndpi"), 0, file_hash=None)
        assert name == "slide_00000000.ndpi"

    def test_sha8_with_hash(self):
        config = SerializerConfig(
            mode=RenameMode.TEMPLATE,
            template="slide_{sha8}.{ext}",
        )
        name = compute_output_name(config, Path("x.svs"), 0, file_hash="deadbeef12345678")
        assert name == "slide_deadbeef.svs"


class TestPreviewSkipsErrors:
    """Gap 8: preview_names silently skips files that can't be renamed."""

    def test_preview_skips_mapping_misses(self, tmp_path):
        csv_file = tmp_path / "map.csv"
        csv_file.write_text("source_filename,output_name\nknown.ndpi,MAPPED.ndpi\n")

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file, unmatched="skip")
        load_mapping(config)

        paths = [Path("unknown1.ndpi"), Path("known.ndpi"), Path("unknown2.svs")]
        previews = preview_names(config, paths, count=3)

        # Only the known file should appear
        assert len(previews) == 1
        assert previews[0] == ("known.ndpi", "MAPPED.ndpi")

    def test_preview_continues_past_errors(self, tmp_path):
        """Preview doesn't stop at the first error. It keeps looking for valid files."""
        csv_file = tmp_path / "map.csv"
        csv_file.write_text(
            "source_filename,output_name\na_good.ndpi,OUT_A.ndpi\nz_good.svs,OUT_Z.svs\n"
        )

        config = SerializerConfig(mode=RenameMode.MAPPING, mapping_path=csv_file, unmatched="skip")
        load_mapping(config)

        # Mix of known and unknown files
        paths = [
            Path("a_good.ndpi"),
            Path("bad1.ndpi"),
            Path("bad2.ndpi"),
            Path("z_good.svs"),
        ]
        previews = preview_names(config, paths, count=3)
        assert len(previews) == 2
        original_names = [orig for orig, _ in previews]
        assert "a_good.ndpi" in original_names
        assert "z_good.svs" in original_names


class TestPreviewNames:
    def test_preview_3_files(self):
        config = SerializerConfig(mode=RenameMode.AUTO, prefix="SLIDE")
        paths = [Path(f"file_{i}.ndpi") for i in range(10)]
        previews = preview_names(config, paths, count=3)
        assert len(previews) == 3
        assert all(orig.startswith("file_") for orig, _ in previews)
        assert all(new.startswith("SLIDE_") for _, new in previews)

    def test_preview_fewer_than_count(self):
        config = SerializerConfig(mode=RenameMode.AUTO)
        paths = [Path("only_one.svs")]
        previews = preview_names(config, paths, count=3)
        assert len(previews) == 1


class TestRenamePlan:
    def test_plan_sorted_deterministic(self, tmp_path):
        config = SerializerConfig(mode=RenameMode.AUTO, prefix="S")
        sources = [Path("z_slide.ndpi"), Path("a_slide.svs"), Path("m_slide.ndpi")]
        plan = compute_rename_plan(config, sources, tmp_path)

        assert len(plan) == 3
        # First in plan should be alphabetically first
        assert plan[0][0] == Path("a_slide.svs")
        assert plan[0][1] == tmp_path / "S_0001.svs"
        assert plan[1][0] == Path("m_slide.ndpi")
        assert plan[2][0] == Path("z_slide.ndpi")

    def test_plan_detects_collision(self, tmp_path):
        """Two files mapping to the same output name raises ValueError."""
        config = SerializerConfig(
            mode=RenameMode.TEMPLATE,
            template="same_name.{ext}",
        )
        sources = [Path("a.ndpi"), Path("b.ndpi")]
        with pytest.raises(ValueError, match="collision"):
            compute_rename_plan(config, sources, tmp_path)


class TestWriteManifest:
    def test_writes_csv(self, tmp_path):
        plan = [
            (Path("/src/slide1.ndpi"), Path("/out/ANON_0001.ndpi")),
            (Path("/src/slide2.svs"), Path("/out/ANON_0002.svs")),
        ]
        manifest_path = tmp_path / "manifest.csv"
        write_manifest(plan, manifest_path)

        assert manifest_path.exists()
        with open(manifest_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["original_filename"] == "slide1"
        assert rows[0]["output_filename"] == "ANON_0001.ndpi"
        assert rows[1]["serial_id"] == "ANON_0002"
        # Directory paths must NOT appear in the manifest (PHI risk)
        assert "original_path" not in rows[0]
        assert "output_path" not in rows[0]

    def test_includes_checksums(self, tmp_path):
        plan = [(Path("/src/s.ndpi"), Path("/out/A_0001.ndpi"))]
        checksums = {"A_0001.ndpi": "abc123"}
        manifest_path = tmp_path / "manifest.csv"
        write_manifest(plan, manifest_path, checksums)

        with open(manifest_path) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["sha256"] == "abc123"


class TestSanitizeGroupId:
    """_sanitize_group_id: filesystem-safe group folder names."""

    def test_clean_id_unchanged(self):
        assert _sanitize_group_id("PAT-001") == "PAT-001"

    def test_strips_whitespace(self):
        assert _sanitize_group_id("  PAT-002  ") == "PAT-002"

    def test_replaces_forward_slash(self):
        result = _sanitize_group_id("group/subgroup")
        assert "/" not in result
        assert result == "group_subgroup"

    def test_replaces_backslash(self):
        result = _sanitize_group_id("group\\sub")
        assert "\\" not in result
        assert result == "group_sub"

    def test_replaces_forbidden_chars(self):
        result = _sanitize_group_id("name<with>bad:chars")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result

    def test_truncates_to_100_chars(self):
        long_id = "A" * 200
        result = _sanitize_group_id(long_id)
        assert len(result) <= 100

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty or unsafe"):
            _sanitize_group_id("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty or unsafe"):
            _sanitize_group_id("   ")

    def test_dots_only_raises(self):
        with pytest.raises(ValueError, match="empty or unsafe"):
            _sanitize_group_id("..")

    def test_collapses_multiple_underscores(self):
        result = _sanitize_group_id("a///b")
        assert "___" not in result
        assert result == "a_b"


class TestGroupingInRenamePlan:
    """compute_rename_plan: per-patient subfolder grouping."""

    def test_grouping_creates_subdirectories(self, tmp_path):
        config = SerializerConfig(
            mode=RenameMode.AUTO,
            prefix="S",
            grouping_map={
                "a_slide.svs": "Patient-A",
                "m_slide.ndpi": "Patient-B",
                "z_slide.ndpi": "Patient-A",
            },
        )
        sources = [Path("z_slide.ndpi"), Path("a_slide.svs"), Path("m_slide.ndpi")]
        plan = compute_rename_plan(config, sources, tmp_path)

        assert len(plan) == 3
        # a_slide -> Patient-A subfolder
        assert plan[0][1] == tmp_path / "Patient-A" / "S_0001.svs"
        # m_slide -> Patient-B subfolder
        assert plan[1][1] == tmp_path / "Patient-B" / "S_0002.ndpi"
        # z_slide -> Patient-A subfolder
        assert plan[2][1] == tmp_path / "Patient-A" / "S_0003.ndpi"

    def test_empty_group_skips_subfolder(self, tmp_path):
        """Files with no matching group_id go directly into the output dir."""
        config = SerializerConfig(
            mode=RenameMode.AUTO,
            prefix="S",
            grouping_map={
                "a_slide.svs": "Patient-A",
                # m_slide.ndpi has no grouping entry
            },
        )
        sources = [Path("a_slide.svs"), Path("m_slide.ndpi")]
        plan = compute_rename_plan(config, sources, tmp_path)

        assert len(plan) == 2
        # a_slide -> grouped into Patient-A
        assert plan[0][1] == tmp_path / "Patient-A" / "S_0001.svs"
        # m_slide -> no group, goes to output root
        assert plan[1][1] == tmp_path / "S_0002.ndpi"

    def test_no_grouping_map_skips_grouping(self, tmp_path):
        """When grouping_map is empty, behaviour matches the original."""
        config = SerializerConfig(mode=RenameMode.AUTO, prefix="S")
        sources = [Path("slide.ndpi")]
        plan = compute_rename_plan(config, sources, tmp_path)

        assert plan[0][1] == tmp_path / "S_0001.ndpi"

    def test_grouping_with_forbidden_chars(self, tmp_path):
        """Group IDs with forbidden characters are sanitized automatically."""
        config = SerializerConfig(
            mode=RenameMode.AUTO,
            prefix="S",
            grouping_map={
                "slide.ndpi": "patient/with:bad<chars",
            },
        )
        sources = [Path("slide.ndpi")]
        plan = compute_rename_plan(config, sources, tmp_path)

        # The group_id should be sanitized (no forbidden chars)
        output_path = plan[0][1]
        group_dir = output_path.parent.name
        assert "/" not in group_dir
        assert ":" not in group_dir
        assert "<" not in group_dir
