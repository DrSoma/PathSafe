"""PathSafe GUI — Tkinter interface for hospital staff.

One-click anonymize workflow: browse files, scan, anonymize, verify.
"""

import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

# Use zenity for native GTK file dialogs on Linux (much better drive/directory support)
_HAS_ZENITY = shutil.which('zenity') is not None


def _zenity_open_file(title='Select file', initialdir=None):
    """Open a file using zenity's native GTK dialog."""
    cmd = ['zenity', '--file-selection', f'--title={title}',
           '--file-filter=WSI files | *.ndpi *.svs *.tif *.tiff',
           '--file-filter=All files | *']
    if initialdir:
        cmd.append(f'--filename={initialdir}/')
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _zenity_open_dir(title='Select folder', initialdir=None):
    """Open a directory using zenity's native GTK dialog."""
    cmd = ['zenity', '--file-selection', '--directory', f'--title={title}']
    if initialdir:
        cmd.append(f'--filename={initialdir}/')
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None

import pathsafe
from pathsafe.anonymizer import anonymize_batch, anonymize_file, collect_wsi_files
from pathsafe.formats import detect_format, get_handler
from pathsafe.report import generate_certificate
from pathsafe.verify import verify_batch


class PathSafeGUI:
    """Main GUI application window."""

    def __init__(self, root):
        self.root = root
        self.root.title(f'PathSafe v{pathsafe.__version__} — WSI Anonymizer')
        self.root.geometry('950x720')
        self.root.minsize(750, 550)

        # Fix DPI scaling for crisp text on HiDPI displays
        try:
            self.root.tk.call('tk', 'scaling', self.root.winfo_fpixels('1i') / 72)
        except Exception:
            pass

        # Apply modern theme
        try:
            import sv_ttk
            sv_ttk.set_theme('dark')
        except ImportError:
            try:
                style = ttk.Style()
                style.theme_use('clam')
            except Exception:
                pass

        # Set default font for all widgets
        import tkinter.font as tkfont
        default_font = tkfont.nametofont('TkDefaultFont')
        default_font.configure(family='Ubuntu', size=10)
        text_font = tkfont.nametofont('TkTextFont')
        text_font.configure(family='Ubuntu', size=10)

        # State
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.mode = tk.StringVar(value='copy')
        self.verify_enabled = tk.BooleanVar(value=True)
        self.workers = tk.IntVar(value=4)
        self.running = False
        self._last_dir = str(Path.home())

        self._build_ui()

    def _build_ui(self):
        # --- Top frame: paths ---
        paths_frame = ttk.LabelFrame(self.root, text='File Paths', padding=10)
        paths_frame.pack(fill='x', padx=10, pady=(10, 5))

        # Input path
        ttk.Label(paths_frame, text='Input (file or folder):').grid(
            row=0, column=0, sticky='w')
        ttk.Entry(paths_frame, textvariable=self.input_path, width=60).grid(
            row=0, column=1, padx=5, sticky='ew')
        btn_frame_in = ttk.Frame(paths_frame)
        btn_frame_in.grid(row=0, column=2)
        ttk.Button(btn_frame_in, text='File', width=5,
                   command=self._browse_input_file).pack(side='left', padx=1)
        ttk.Button(btn_frame_in, text='Folder', width=6,
                   command=self._browse_input_dir).pack(side='left', padx=1)

        # Output path
        ttk.Label(paths_frame, text='Output folder:').grid(
            row=1, column=0, sticky='w', pady=(5, 0))
        ttk.Entry(paths_frame, textvariable=self.output_path, width=60).grid(
            row=1, column=1, padx=5, sticky='ew', pady=(5, 0))
        ttk.Button(paths_frame, text='Browse', width=8,
                   command=self._browse_output_dir).grid(
            row=1, column=2, pady=(5, 0))

        paths_frame.columnconfigure(1, weight=1)

        # --- Options frame ---
        opts_frame = ttk.LabelFrame(self.root, text='Options', padding=10)
        opts_frame.pack(fill='x', padx=10, pady=5)

        # Mode
        ttk.Label(opts_frame, text='Mode:').pack(side='left')
        ttk.Radiobutton(opts_frame, text='Copy (safe)', variable=self.mode,
                        value='copy').pack(side='left', padx=(5, 10))
        ttk.Radiobutton(opts_frame, text='In-place', variable=self.mode,
                        value='inplace').pack(side='left', padx=(0, 20))

        # Verify
        ttk.Checkbutton(opts_frame, text='Verify after', variable=self.verify_enabled
                        ).pack(side='left', padx=(0, 20))

        # Workers
        ttk.Label(opts_frame, text='Workers:').pack(side='left')
        ttk.Spinbox(opts_frame, from_=1, to=16, textvariable=self.workers,
                    width=4).pack(side='left', padx=5)

        # --- Action buttons ---
        btn_frame = ttk.Frame(self.root, padding=5)
        btn_frame.pack(fill='x', padx=10)

        self.btn_scan = ttk.Button(btn_frame, text='Scan for PHI',
                                   command=self._run_scan)
        self.btn_scan.pack(side='left', padx=5)

        self.btn_anonymize = ttk.Button(btn_frame, text='Anonymize',
                                        command=self._run_anonymize)
        self.btn_anonymize.pack(side='left', padx=5)

        self.btn_verify = ttk.Button(btn_frame, text='Verify',
                                     command=self._run_verify)
        self.btn_verify.pack(side='left', padx=5)

        self.btn_stop = ttk.Button(btn_frame, text='Stop', state='disabled',
                                   command=self._request_stop)
        self.btn_stop.pack(side='left', padx=5)

        # --- Progress ---
        progress_frame = ttk.Frame(self.root, padding=(10, 5))
        progress_frame.pack(fill='x', padx=10)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill='x')

        self.status_var = tk.StringVar(value='Ready')
        ttk.Label(progress_frame, textvariable=self.status_var).pack(
            anchor='w', pady=(2, 0))

        # --- Log output ---
        log_frame = ttk.LabelFrame(self.root, text='Log', padding=5)
        log_frame.pack(fill='both', expand=True, padx=10, pady=(5, 10))

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=15, font=('Ubuntu Mono', 10), state='disabled',
            wrap='word', bg='#1c1c1c', fg='#e0e0e0', insertbackground='#e0e0e0',
            selectbackground='#3a3a5c', relief='flat', borderwidth=0,
            padx=8, pady=8)
        self.log_text.pack(fill='both', expand=True)

        # Stop flag
        self._stop_requested = False

    # --- Browse dialogs ---

    def _browse_input_file(self):
        if _HAS_ZENITY:
            path = _zenity_open_file('Select WSI file', self._last_dir)
        else:
            path = filedialog.askopenfilename(
                title='Select WSI file',
                initialdir=self._last_dir,
                filetypes=[
                    ('WSI files', '*.ndpi *.svs *.tif *.tiff'),
                    ('All files', '*.*'),
                ])
        if path:
            self.input_path.set(path)
            self._last_dir = str(Path(path).parent)

    def _browse_input_dir(self):
        if _HAS_ZENITY:
            path = _zenity_open_dir('Select folder with WSI files', self._last_dir)
        else:
            path = filedialog.askdirectory(
                title='Select folder with WSI files',
                initialdir=self._last_dir)
        if path:
            self.input_path.set(path)
            self._last_dir = path

    def _browse_output_dir(self):
        if _HAS_ZENITY:
            path = _zenity_open_dir('Select output folder', self._last_dir)
        else:
            path = filedialog.askdirectory(
                title='Select output folder',
                initialdir=self._last_dir)
        if path:
            self.output_path.set(path)
            self._last_dir = path

    # --- Logging ---

    def _log(self, msg):
        """Append message to the log widget (thread-safe)."""
        def _append():
            self.log_text.config(state='normal')
            self.log_text.insert('end', msg + '\n')
            self.log_text.see('end')
            self.log_text.config(state='disabled')
        self.root.after(0, _append)

    def _clear_log(self):
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')

    def _set_status(self, msg):
        self.root.after(0, lambda: self.status_var.set(msg))

    def _set_progress(self, pct):
        self.root.after(0, lambda: self.progress_var.set(pct))

    # --- Run state management ---

    def _set_running(self, running):
        self.running = running
        self._stop_requested = False
        state = 'disabled' if running else 'normal'
        stop_state = 'normal' if running else 'disabled'
        self.root.after(0, lambda: self.btn_scan.config(state=state))
        self.root.after(0, lambda: self.btn_anonymize.config(state=state))
        self.root.after(0, lambda: self.btn_verify.config(state=state))
        self.root.after(0, lambda: self.btn_stop.config(state=stop_state))

    def _request_stop(self):
        self._stop_requested = True
        self._log('Stop requested... finishing current file.')

    def _validate_input(self):
        path = self.input_path.get().strip()
        if not path:
            messagebox.showerror('Error', 'Please select an input file or folder.')
            return None
        p = Path(path)
        if not p.exists():
            messagebox.showerror('Error', f'Input path does not exist:\n{path}')
            return None
        return p

    # --- Scan ---

    def _run_scan(self):
        input_p = self._validate_input()
        if not input_p:
            return
        self._clear_log()
        self._set_running(True)
        threading.Thread(target=self._scan_thread, args=(input_p,),
                         daemon=True).start()

    def _scan_thread(self, input_path):
        try:
            files = collect_wsi_files(input_path)
            total = len(files)
            if total == 0:
                self._log('No WSI files found.')
                return

            self._log(f'Scanning {total} file(s)...\n')
            clean = 0
            phi_count = 0

            for i, filepath in enumerate(files, 1):
                if self._stop_requested:
                    self._log(f'\nStopped at {i-1}/{total}')
                    break

                handler = get_handler(filepath)
                result = handler.scan(filepath)

                pct = i / total * 100
                self._set_progress(pct)
                self._set_status(f'Scanning {i}/{total}: {filepath.name}')

                if result.is_clean:
                    clean += 1
                    self._log(f'  [{i}/{total}] {filepath.name} — CLEAN')
                else:
                    phi_count += len(result.findings)
                    self._log(f'  [{i}/{total}] {filepath.name} — '
                              f'{len(result.findings)} finding(s):')
                    for f in result.findings:
                        self._log(f'      {f.tag_name}: {f.value_preview}')

            self._log(f'\nSummary: {total} files, {clean} clean, '
                      f'{total - clean} with PHI ({phi_count} findings)')
            self._set_status('Scan complete')
        except Exception as e:
            self._log(f'\nERROR: {e}')
            self._set_status(f'Error: {e}')
        finally:
            self._set_running(False)

    # --- Anonymize ---

    def _run_anonymize(self):
        input_p = self._validate_input()
        if not input_p:
            return

        mode = self.mode.get()
        output_dir = None

        if mode == 'copy':
            out = self.output_path.get().strip()
            if not out:
                messagebox.showerror(
                    'Error', 'Copy mode requires an output folder.\n'
                    'Select an output folder or switch to in-place mode.')
                return
            output_dir = Path(out)
        else:
            confirm = messagebox.askyesno(
                'Confirm In-Place',
                'In-place mode will modify your original files!\n\n'
                'Are you sure you want to continue?')
            if not confirm:
                return

        self._clear_log()
        self._set_running(True)
        threading.Thread(
            target=self._anonymize_thread,
            args=(input_p, output_dir),
            daemon=True).start()

    def _anonymize_thread(self, input_path, output_dir):
        try:
            files = collect_wsi_files(input_path)
            total = len(files)
            if total == 0:
                self._log('No WSI files found.')
                return

            mode_str = 'copy' if output_dir else 'in-place'
            workers = self.workers.get()
            self._log(f'PathSafe v{pathsafe.__version__} — {mode_str} anonymization'
                      f'{f", {workers} workers" if workers > 1 else ""}')
            self._log(f'Processing {total} file(s)...\n')

            t0 = time.time()

            def progress(i, total_files, filepath, result):
                if self._stop_requested:
                    return

                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                pct = i / total_files * 100
                self._set_progress(pct)
                self._set_status(
                    f'{i}/{total_files} ({rate:.1f}/s) — {filepath.name}')

                if result.error:
                    status = f'ERROR: {result.error}'
                elif result.findings_cleared > 0:
                    status = f'cleared {result.findings_cleared} finding(s)'
                    if result.verified:
                        status += ' [verified]'
                else:
                    status = 'already clean'

                self._log(f'  [{i}/{total_files}] {filepath.name} | {status}')

            batch_result = anonymize_batch(
                input_path, output_dir=output_dir,
                verify=self.verify_enabled.get(),
                progress_callback=progress,
                workers=workers,
            )

            # Generate certificate
            cert_path = None
            if output_dir:
                cert_path = output_dir / 'pathsafe_certificate.json'
            else:
                cert_path = input_path / 'pathsafe_certificate.json' if input_path.is_dir() else input_path.parent / 'pathsafe_certificate.json'

            cert = generate_certificate(batch_result, output_path=cert_path)

            self._log(f'\nDone in {batch_result.total_time_seconds:.1f}s')
            self._log(f'  Total:         {batch_result.total_files}')
            self._log(f'  Anonymized:    {batch_result.files_anonymized}')
            self._log(f'  Already clean: {batch_result.files_already_clean}')
            self._log(f'  Errors:        {batch_result.files_errored}')
            self._log(f'\nCertificate: {cert_path}')

            if batch_result.files_errored == 0:
                self._set_status('Anonymization complete')
            else:
                self._set_status(
                    f'Done with {batch_result.files_errored} error(s)')

        except Exception as e:
            self._log(f'\nERROR: {e}')
            self._set_status(f'Error: {e}')
        finally:
            self._set_running(False)

    # --- Verify ---

    def _run_verify(self):
        input_p = self._validate_input()
        if not input_p:
            return
        self._clear_log()
        self._set_running(True)
        threading.Thread(target=self._verify_thread, args=(input_p,),
                         daemon=True).start()

    def _verify_thread(self, input_path):
        try:
            files = collect_wsi_files(input_path)
            total = len(files)
            if total == 0:
                self._log('No WSI files found.')
                return

            self._log(f'Verifying {total} file(s)...\n')
            clean = 0
            dirty = 0

            def progress(i, total_files, filepath, result):
                pct = i / total_files * 100
                self._set_progress(pct)
                self._set_status(f'Verifying {i}/{total_files}: {filepath.name}')

            results = verify_batch(input_path, progress_callback=progress)

            for result in results:
                if result.is_clean:
                    clean += 1
                else:
                    dirty += 1
                    findings_str = ', '.join(
                        f.tag_name for f in result.findings)
                    self._log(f'  PHI FOUND: {result.filepath.name} — '
                              f'{findings_str}')

            self._log(f'\nVerification: {clean} clean, {dirty} with remaining PHI')
            if dirty == 0:
                self._log('All files verified clean.')
                self._set_status('Verification passed — all files clean')
            else:
                self._log('WARNING: Some files still contain PHI!')
                self._set_status(f'WARNING: {dirty} file(s) with remaining PHI')

        except Exception as e:
            self._log(f'\nERROR: {e}')
            self._set_status(f'Error: {e}')
        finally:
            self._set_running(False)


def main():
    """Launch the PathSafe GUI."""
    root = tk.Tk()
    app = PathSafeGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
