# VQ1015 live_preview

Live preview and JPEG capture for VQ1015 Entry. Note: This has only been tested on macOS.

## Install

Install Python 3 and open a terminal in this folder.

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On Windows, install the WinUSB driver using Zadig for the camera in PCC mode (`2770:9080`).

## Connect your Camera

1. While holding down the Shutter button, connect the USB.
2. The LCD should show "PCC".
3. Release the Shutter button.

## Live preview

With the virtual environment activated:

```bash
python vq1015_live_preview.py --live -n 0 --size 640
```

Shows a continuous 640×480 preview without saving files. Use `--size 320` for 320×240.

Press **Q**, **Esc**, close the window, or press **Ctrl-C** in the terminal to stop.

## Save frames

Save ten JPEG frames at 640×480:

```bash
python vq1015_live_preview.py --size 640 -n 10 --out captures
```

Add `--live` to preview while saving. Change `-n` to set the number of frames.

Use a new output folder for each run to avoid overwriting earlier captures. For all options, run `python vq1015_live_preview.py --help`.
