"""About dialog and per-operation summary dialog for the main window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

import pathsafe


class DialogsMixin:
    """Modal dialogs shown from the main window."""

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About PathSafe",
            f"<h3>PathSafe v{pathsafe.__version__}</h3>"
            "<p>WSI de-identifier for pathology slide files.</p>"
            "<p>Removes patient-identifying information (PHI) from "
            "NDPI, SVS, MRXS, DICOM, and other whole-slide image formats.</p>"
            "<p>Includes label/macro image blanking, post-deidentification "
            "verification, and PDF compliance certificates.</p>"
            "<hr>"
            "<p style='font-size:small; color:gray;'>"
            "<b>Disclaimer:</b> PathSafe is not a medical device and is not "
            "intended for clinical diagnosis. De-identification completeness "
            "should be verified per institutional requirements.</p>",
        )

    def _show_summary(self, data: dict[str, object]) -> None:
        """Show a summary popup dialog when an operation completes."""
        op = data.get("type", "operation")

        if op == "scan":
            total = data.get("total", 0)
            clean = data.get("clean", 0)
            phi_files = data.get("phi_files", 0)
            phi_findings = data.get("phi_findings", 0)
            errors = data.get("errors", 0)

            if phi_files == 0 and errors == 0:
                icon = QMessageBox.Information
                title = "Scan Complete: All Clean"
                scan_report = data.get("scan_report", "")
                report_line = (
                    f"<p>Scan report:<br><code>{Path(scan_report).name}</code></p>"
                    if scan_report
                    else ""
                )
                msg = (
                    f"<h3>All {total} files are clean</h3>"
                    f"<p>No patient information (PHI) was detected.</p>"
                    f"{report_line}"
                )
            else:
                icon = QMessageBox.Warning
                title = "Scan Complete: PHI Detected"
                lines = ['<h3>Scan Results</h3><table cellpadding="4">']
                lines.append(f"<tr><td>Total scanned:</td><td><b>{total}</b></td></tr>")
                if clean:
                    lines.append(
                        f'<tr><td>Clean:</td><td style="color:#2e8b3e"><b>{clean}</b></td></tr>'
                    )
                if phi_files:
                    lines.append(
                        f"<tr><td>PHI detected:</td>"
                        f'<td style="color:#b45300"><b>{phi_files} files '
                        f"({phi_findings} findings)</b></td></tr>"
                    )
                if errors:
                    lines.append(
                        f'<tr><td>Errors:</td><td style="color:#c03030"><b>{errors}</b></td></tr>'
                    )
                lines.append("</table>")
                if phi_files:
                    lines.append("<p>Run <b>Deidentify</b> to remove detected PHI.</p>")
                scan_report = data.get("scan_report", "")
                if scan_report:
                    lines.append(f"<p>Scan report:<br><code>{Path(scan_report).name}</code></p>")
                msg = "".join(lines)

        elif op == "deidentify":
            total = data.get("total", 0)
            deidentified = data.get("deidentified", 0)
            already_clean = data.get("already_clean", 0)
            errors = data.get("errors", 0)
            elapsed = data.get("time", "?")
            cert = data.get("certificate", "")
            dry_run = data.get("dry_run", False)

            output_paths = data.get("output_paths", [])
            if output_paths:
                self._last_deidentified_paths = output_paths

            if dry_run:
                icon = QMessageBox.Information
                title = "Deidentification DRY RUN Complete"
            elif errors == 0:
                icon = QMessageBox.Information
                title = "Deidentification Complete"
            else:
                icon = QMessageBox.Warning
                title = "Deidentification Complete (with errors)"

            lines = ['<h3>Deidentification Results</h3><table cellpadding="4">']
            lines.append(f"<tr><td>Total files:</td><td><b>{total}</b></td></tr>")
            if deidentified:
                lines.append(
                    f'<tr><td>Deidentified:</td><td style="color:#b45300"><b>{deidentified}</b></td></tr>'
                )
            if already_clean:
                lines.append(
                    f'<tr><td>Already clean:</td><td style="color:#2e8b3e"><b>{already_clean}</b></td></tr>'
                )
            if errors:
                lines.append(
                    f'<tr><td>Errors:</td><td style="color:#c03030"><b>{errors}</b></td></tr>'
                )
            integrity_verified = data.get("integrity_verified", 0)
            integrity_failed = data.get("integrity_failed", 0)
            if integrity_verified or integrity_failed:
                if integrity_failed:
                    lines.append(
                        f"<tr><td>Image integrity:</td>"
                        f'<td style="color:#c03030"><b>{integrity_failed} FAILED</b>, '
                        f"{integrity_verified} verified</td></tr>"
                    )
                else:
                    lines.append(
                        f"<tr><td>Image integrity:</td>"
                        f'<td style="color:#2e8b3e"><b>{integrity_verified} verified</b></td></tr>'
                    )
            phi_filenames = data.get("phi_filenames", 0)
            if phi_filenames:
                lines.append(
                    f"<tr><td>Filename PHI:</td>"
                    f'<td style="color:#c03030"><b>{phi_filenames} file(s) '
                    f"need renaming</b></td></tr>"
                )
            lines.append(f"<tr><td>Time:</td><td>{elapsed}</td></tr>")
            lines.append("</table>")

            if phi_filenames:
                lines.append(
                    '<p style="color:#c03030"><b>WARNING:</b> Some output files '
                    "have patient information in their filename. Rename them "
                    "manually before sharing.</p>"
                )
            if dry_run:
                lines.append("<p><b>DRY RUN</b> - No files were modified.</p>")
            else:
                output_dir = data.get("output_dir", "")
                if output_dir:
                    lines.append(f"<p>Output folder:<br><code>{output_dir}</code></p>")
                if cert:
                    pdf_cert = data.get("pdf_certificate", "")
                    lines.append(f"<p>Certificate:<br><code>{Path(cert).name}</code>")
                    if pdf_cert:
                        lines.append(f"<br><code>{Path(pdf_cert).name}</code>")
                    lines.append("</p>")

            msg = "".join(lines)

        elif op == "verify":
            total = data.get("total", 0)
            clean = data.get("clean", 0)
            dirty = data.get("dirty", 0)

            if dirty == 0:
                icon = QMessageBox.Information
                title = "Verification Passed"
                msg = (
                    f"<h3>All {total} files verified clean</h3>"
                    f"<p>No patient information remains in any file.</p>"
                )
            else:
                icon = QMessageBox.Warning
                title = "Verification Failed"
                msg = (
                    f"<h3>Verification Results</h3>"
                    f'<table cellpadding="4">'
                    f'<tr><td>Clean:</td><td style="color:#2e8b3e"><b>{clean}</b></td></tr>'
                    f'<tr><td>PHI remaining:</td><td style="color:#c03030"><b>{dirty}</b></td></tr>'
                    f"</table>"
                    f"<p><b>WARNING:</b> Some files still contain PHI!</p>"
                )

        elif op == "info":
            fmt = data.get("format", "Unknown")
            size = data.get("size", "?")
            metadata_count = data.get("metadata_count", 0)
            phi_status = data.get("phi_status", "Unknown")

            icon = QMessageBox.Information
            title = "File Information"
            lines = ['<h3>File Information</h3><table cellpadding="4">']
            lines.append(f"<tr><td>Format:</td><td><b>{fmt}</b></td></tr>")
            lines.append(f"<tr><td>File size:</td><td><b>{size}</b></td></tr>")
            lines.append(f"<tr><td>Metadata entries:</td><td><b>{metadata_count}</b></td></tr>")
            lines.append(f"<tr><td>PHI status:</td><td><b>{phi_status}</b></td></tr>")
            lines.append("</table>")
            msg = "".join(lines)

        elif op == "convert":
            total = data.get("total", 0)
            converted = data.get("converted", 0)
            errors = data.get("errors", 0)
            elapsed = data.get("time", "?")

            if errors == 0:
                icon = QMessageBox.Information
                title = "Conversion Complete"
            else:
                icon = QMessageBox.Warning
                title = "Conversion Complete (with errors)"

            lines = ['<h3>Conversion Results</h3><table cellpadding="4">']
            lines.append(f"<tr><td>Total files:</td><td><b>{total}</b></td></tr>")
            if converted:
                lines.append(
                    f'<tr><td>Converted:</td><td style="color:#2e8b3e"><b>{converted}</b></td></tr>'
                )
            if errors:
                lines.append(
                    f'<tr><td>Errors:</td><td style="color:#c03030"><b>{errors}</b></td></tr>'
                )
            lines.append(f"<tr><td>Time:</td><td>{elapsed}</td></tr>")
            lines.append("</table>")
            msg = "".join(lines)

        else:
            return

        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(msg)
        box.exec()
