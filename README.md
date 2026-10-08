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

Holding Shutter while connecting toggles between PCC and USb mode. If the LCD shows "USb", disconnect and repeat these steps.

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


## EXPERIMENTAL: Take still photos during live preview

The experimental [PCC still-capture firmware](firmware/YHTMMSF.BIN) lets you press the camera’s **Shutter** button during live preview to save a **1600×1200 JPEG to the SD card**. Preview pauses while the photo is taken, then resumes. Wait for preview to resume before taking another photo.

This build uses the factory image settings. Its only added feature is the ability to take a 1600×1200 still photo in PCC mode. The firmware identifier and capture diagnostics in JPEG metadata are also updated.

The firmware is experimental. Live preview alone does not require it. The firmware has only been tested on a VQ1015 Entry. Improper flashing could brick your device. Use at your own risk.

### Flash the firmware

For the **VQ1015 Entry**:

1. Copy any photos you want to keep to your computer. Turn the camera off, unplug USB, and remove the SD card.
2. Install fresh batteries and leave them in throughout the update.
3. Connect the camera by USB. The LCD must show **USb**, and the camera’s internal storage should appear as **DSC_FATDISK**.
4. Copy [YHTMMSF.BIN](firmware/YHTMMSF.BIN) into **DCIM/100IMAGE** on the camera’s internal storage. Keep the filename unchanged.
5. Wait for the copy to finish, then safely eject **DSC_FATDISK** from your computer.
6. Unplug the USB cable to start the update. Leave the batteries installed and wait for the camera to finish and power off before pressing buttons or reconnecting it.
7. Reinsert the SD card, connect in **PCC** mode, and start live preview using the command above. Press the camera’s Shutter button to take a still photo. The still photo will be saved to the SD card.
