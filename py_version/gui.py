#!/usr/bin/env python3
import os
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox

# ====== CONFIG ======
DEVICE_DIR = "/sdcard/Transfer"

# ====== FUNCTIONS ======
def check_device_dir():
    """Check if /sdcard/Transfer exists and has files"""
    try:
        result = subprocess.run(
            ["adb", "shell", "ls", DEVICE_DIR],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        return True
    except Exception:
        return False

def run_pull(local_path):
    """Pull files from device to local_path"""
    if not check_device_dir():
        messagebox.showerror("Error", f"{DEVICE_DIR} does not exist or is empty on device")
        return
    os.makedirs(local_path, exist_ok=True)
    cmd = f'adb exec-out "tar -cf - {DEVICE_DIR}" | pv | tar -xf - -C "{local_path}"'
    subprocess.run(cmd, shell=True)
    messagebox.showinfo("Done", f"Pulled files to {local_path}")

def run_push(local_path):
    """Push files from local_path to device"""
    if not os.path.exists(local_path) or not os.listdir(local_path):
        messagebox.showerror("Error", f"No files found in {local_path}")
        return
    # create folder on device if not exists
    subprocess.run(["adb", "shell", "mkdir", "-p", DEVICE_DIR])
    cmd = f'tar -cf - -C "{local_path}" . | pv | adb shell "tar -xf - -C {DEVICE_DIR}"'
    subprocess.run(cmd, shell=True)
    messagebox.showinfo("Done", f"Pushed files to {DEVICE_DIR} on device")

# ====== GUI ======
root = tk.Tk()
root.title("ADB Transfer Tool")

mode_var = tk.StringVar(value="pull")

tk.Label(root, text="Select mode:").pack(pady=5)
tk.Radiobutton(root, text="Pull (Device -> PC)", variable=mode_var, value="pull").pack(anchor="w")
tk.Radiobutton(root, text="Push (PC -> Device)", variable=mode_var, value="push").pack(anchor="w")

path_frame = tk.Frame(root)
path_frame.pack(pady=10)
tk.Label(path_frame, text="Select local folder:").pack(side="left")
path_var = tk.StringVar()
tk.Entry(path_frame, textvariable=path_var, width=40).pack(side="left", padx=5)
def browse():
    folder = filedialog.askdirectory()
    if folder:
        path_var.set(folder)
tk.Button(path_frame, text="Browse", command=browse).pack(side="left")

def run():
    path = path_var.get().strip()
    if not path:
        messagebox.showerror("Error", "Please select a local folder")
        return
    if mode_var.get() == "pull":
        run_pull(path)
    else:
        run_push(path)

tk.Button(root, text="Start Transfer", command=run, bg="green", fg="white").pack(pady=15)

root.mainloop()
