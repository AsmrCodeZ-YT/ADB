#!/usr/bin/env python3
"""
GTK4 + libadwaita ADB Transfer Tool
Features: Debug Logs, Error Capturing, Speedometer, Progress Bar (using pv).
Fixes: tar compatibility issue by using 'cd' in adb exec-out command.
"""
import os
import subprocess
import threading
import sys
import time
import logging

# تنظیمات سیستم لاگ (نمایش در ترمینال)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk, Adw, Gio, GLib
except Exception as e:
    logger.critical(f"Required GTK4 bindings missing: {e}")
    sys.exit(1)

# مسیر پیش‌فرض در دستگاه اندروید
DEVICE_DIR = "/sdcard/Transfer"
REMOTE_BASE_DIR = "/sdcard"
REMOTE_TARGET_DIR_NAME = "Transfer" # نام پوشه ای که آرشیو می شود

# --- Functional Helpers ---

def format_speed(bytes_per_sec):
    """Converts bytes/sec to human readable string."""
    if bytes_per_sec < 1024:
        return f"{bytes_per_sec:.0f} B/s"
    elif bytes_per_sec < 1024**2:
        return f"{bytes_per_sec/1024:.1f} KB/s"
    else:
        return f"{bytes_per_sec/(1024**2):.1f} MB/s"

def check_adb_device():
    """Checks ADB connection state."""
    logger.debug("Checking for ADB device...")
    try:
        res = subprocess.run(["adb", "get-state"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            logger.error(f"ADB Connection Failed: {res.stderr.strip()}")
            return False
        return True
    except Exception as e:
        logger.exception("Exception in check_adb_device")
        return False

def get_remote_size(remote_path):
    """Calculate size of the remote folder in bytes."""
    logger.debug(f"Calculating remote size for {remote_path}...")
    try:
        # استفاده از 'du -s -b' (bytes) برای محاسبه دقیق
        cmd = ["adb", "shell", "du", "-s", "-b", remote_path] 
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            output = result.stdout.strip()
            if output:
                # خروجی: 174598144  /sdcard/Transfer
                size_bytes = int(output.split()[0])
                logger.info(f"Remote size: {size_bytes} bytes")
                return size_bytes
        else:
            logger.error(f"Failed to get remote size. Check existence: {result.stderr}")
    except Exception as e:
        logger.error(f"Error calculating remote size: {e}")
    return 0

def get_local_size(path):
    """Calculate size of local directory recursively."""
    logger.debug(f"Calculating local size for: {path}")
    total_size = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
        logger.info(f"Local size: {total_size} bytes")
    except Exception as e:
        logger.error(f"Error calculating local size: {e}")
    return total_size

def run_adb_command_with_progress(cmd_list, update_callback, finished_callback):
    """Runs shell command, captures pv progress and error output."""
    logger.info(f"Executing Command: {cmd_list}")
    
    process = subprocess.Popen(
        cmd_list,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, 
        text=True,
        bufsize=1,
        universal_newlines=True
    )

    captured_errors = []

    def read_stderr():
        while True:
            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break
            if line:
                line_str = line.strip()
                try:
                    # Attempt to parse as progress percentage from pv -n
                    percent = float(line_str)
                    GLib.idle_add(update_callback, percent / 100.0)
                except ValueError:
                    # Not a number, likely an error or debug text
                    if line_str:
                        captured_errors.append(line_str)
                        logger.debug(f"CMD STDERR: {line_str}")
        
        rc = process.poll()
        success = (rc == 0)
        error_msg = "\n".join(captured_errors) if not success else ""
        
        if not success:
            logger.error(f"Process finished with error code {rc}")
            logger.error(f"Error Output: {error_msg}")

        GLib.idle_add(finished_callback, success, error_msg)

    t = threading.Thread(target=read_stderr, daemon=True)
    t.start()

# --- UI Application ---

class ADBTransferApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.example.adbtransfer")
        self.connect("activate", self.on_activate)
        
        self.total_bytes = 0
        self.last_fraction = 0.0
        self.last_time = 0.0

    def on_activate(self, app):
        self.window = Adw.ApplicationWindow(application=self)
        self.window.set_title("ADB Transfer Tool")
        self.window.set_default_size(500, 350)
        
        self.window.connect("notify::default-width", self.on_window_resize)
        self.window.connect("notify::default-height", self.on_window_resize)

        self.toast_overlay = Adw.ToastOverlay()
        self.window.set_content(self.toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main_box.set_margin_top(20)
        main_box.set_margin_bottom(20)
        main_box.set_margin_start(20)
        main_box.set_margin_end(20)
        toolbar_view.set_content(main_box)

        self.status_label = Gtk.Label(label="Ready")
        self.status_label.set_css_classes(["title-2"])
        main_box.append(self.status_label)

        controls_grp = Adw.PreferencesGroup()
        main_box.append(controls_grp)

        mode_row = Adw.ActionRow(title="Transfer Mode")
        self.mode_pull = Gtk.ToggleButton.new_with_label("Pull (Phone → PC)")
        self.mode_push = Gtk.ToggleButton.new_with_label("Push (PC → Phone)")
        self.mode_pull.set_active(True)
        self.mode_pull.set_group(self.mode_push)
        
        mode_box = Gtk.Box(spacing=10)
        mode_box.append(self.mode_pull)
        mode_box.append(self.mode_push)
        mode_box.set_valign(Gtk.Align.CENTER)
        mode_row.add_suffix(mode_box)
        controls_grp.add(mode_row)

        path_row = Adw.ActionRow(title="Local Folder")
        self.path_entry = Gtk.Entry()
        self.path_entry.set_placeholder_text("Select path...")
        self.path_entry.set_hexpand(True)
        
        browse_btn = Gtk.Button(icon_name="folder-open-symbolic")
        browse_btn.connect("clicked", self.on_browse)

        path_box = Gtk.Box(spacing=10)
        path_box.append(self.path_entry)
        path_box.append(browse_btn)
        path_row.add_suffix(path_box)
        controls_grp.add(path_row)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_text("0%")
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_opacity(0.0) 
        main_box.append(self.progress_bar)

        self.speed_label = Gtk.Label(label="")
        self.speed_label.set_css_classes(["caption"])
        self.speed_label.set_opacity(0.0)
        main_box.append(self.speed_label)

        self.start_btn = Gtk.Button(label="Start Transfer")
        self.start_btn.add_css_class("suggested-action")
        self.start_btn.add_css_class("pill")
        self.start_btn.connect("clicked", self.on_start)
        main_box.append(self.start_btn)

        self.window.present()

    def on_window_resize(self, window, param):
        w = window.get_width()
        h = window.get_height()
        # print(f"Resize: {w}x{h}")

    def on_browse(self, button):
        dialog = Gtk.FileChooserNative(
            title="Select folder",
            transient_for=self.window,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.connect("response", self._on_browse_response)
        dialog.show()

    def _on_browse_response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file:
                self.path_entry.set_text(file.get_path())
        dialog.destroy()

    def update_ui_progress(self, fraction):
        current_time = time.time()
        
        if self.total_bytes > 0 and self.last_time > 0:
            time_delta = current_time - self.last_time
            if time_delta > 0.5:
                fraction_delta = fraction - self.last_fraction
                
                if fraction_delta >= 0:
                    bytes_delta = fraction_delta * self.total_bytes
                    speed = bytes_delta / time_delta
                    self.speed_label.set_text(format_speed(speed))
                
                self.last_time = current_time
                self.last_fraction = fraction

        self.progress_bar.set_fraction(fraction)
        self.progress_bar.set_text(f"{int(fraction * 100)}%")

    def on_transfer_finished(self, success, error_msg=""):
        self.start_btn.set_sensitive(True)
        self.progress_bar.set_opacity(0.0)
        self.progress_bar.set_fraction(0)
        self.speed_label.set_opacity(0.0)
        
        if success:
            self.status_label.set_text("Transfer Complete!")
            self._show_toast("Success!")
            logger.info("Transfer finished successfully.")
        else:
            self.status_label.set_text("Transfer Failed")
            logger.error(f"Transfer finished with errors: {error_msg}")
            
            short_err = (error_msg[:40] + '...') if len(error_msg) > 40 else error_msg
            if not short_err: short_err = "Check terminal for details."
            self._show_toast(f"Error: {short_err}")

    def _show_toast(self, message):
        toast = Adw.Toast.new(message)
        self.toast_overlay.add_toast(toast)

    def on_start(self, button):
        local_path = self.path_entry.get_text().strip()
        if not local_path:
            self._show_toast("Please select a local path.")
            return

        is_pull = self.mode_pull.get_active()
        
        logger.info(f"Starting transfer. Mode={'Pull' if is_pull else 'Push'}, Path={local_path}")
        
        self.start_btn.set_sensitive(False)
        self.status_label.set_text("Initializing...")
        self.progress_bar.set_opacity(1.0)
        self.speed_label.set_opacity(1.0)
        self.speed_label.set_text("Calculating...")
        
        self.last_fraction = 0.0
        self.last_time = time.time()
        
        t = threading.Thread(
            target=self._prepare_and_run, 
            args=(is_pull, local_path), 
            daemon=True
        )
        t.start()

    def _prepare_and_run(self, is_pull, local_path):
        if not check_adb_device():
            GLib.idle_add(lambda: self.status_label.set_text("Device Error"))
            GLib.idle_add(self.on_transfer_finished, False, "ADB Device not connected or unauthorized")
            return

        size_bytes = 0
        cmd = ""

        if is_pull:
            # --- اصلاحیه رفع خطای TAR ---
            remote_full_path = os.path.join(REMOTE_BASE_DIR, REMOTE_TARGET_DIR_NAME)
            size_bytes = get_remote_size(remote_full_path)
            
            if size_bytes == 0:
                logger.warning("Remote size returned 0. Access check is mandatory.")
            
            os.makedirs(local_path, exist_ok=True)
            
            cmd = (
                f'adb exec-out "cd {REMOTE_BASE_DIR} && tar -c -f - {REMOTE_TARGET_DIR_NAME}" | '
                f'pv -n -s {size_bytes} | '
                f'tar -xf - -C "{local_path}"'
            )
            logger.info(f"Pulling {REMOTE_TARGET_DIR_NAME} from {REMOTE_BASE_DIR}")

        else:
            if not os.path.exists(local_path):
                GLib.idle_add(self.on_transfer_finished, False, "Local path does not exist")
                return
            
            subprocess.run(["adb", "shell", "mkdir", "-p", DEVICE_DIR])
            size_bytes = get_local_size(local_path)
            
            cmd = (
                f'tar -cf - -C "{local_path}" . | '
                f'pv -n -s {size_bytes} | '
                f'adb shell "tar -xf - -C {DEVICE_DIR}"'
            )
            logger.info(f"Pushing files to {DEVICE_DIR}")

        self.total_bytes = size_bytes
        GLib.idle_add(lambda: self.status_label.set_text("Transferring..."))
        
        run_adb_command_with_progress(
            cmd, 
            self.update_ui_progress, 
            self.on_transfer_finished
        )

def main():
    app = ADBTransferApp()
    app.run(None)

if __name__ == "__main__":
    main()