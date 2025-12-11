"""
ptz_controller.py

Basic ONVIF PTZ control for an IP dome camera using keyboard input.

Assumptions:
- Camera supports ONVIF PTZ.
- Camera IP: 192.168.1.13
- Port: 80
- Username: admin
- Password: 123456

Keyboard controls (in the console window):
  W / Up Arrow    - Tilt up
  S / Down Arrow  - Tilt down
  A / Left Arrow  - Pan left
  D / Right Arrow - Pan right
  Q               - Zoom in
  E               - Zoom out
  SPACE           - Stop motion
  P               - List presets
  G               - Go to preset (prompt for token)
  O               - Save preset at current position
  ESC             - Quit

Usage:
    python ptz_controller.py
"""

from __future__ import annotations
import sys
import time
from dataclasses import dataclass

import msvcrt  # Windows-only keyboard input

try:
    from onvif import ONVIFCamera
except ImportError as e:
    print("Error: onvif package not installed or import failed.")
    print("Try: pip install onvif_zeep or pip install onvif-zeep")
    raise e


@dataclass
class CameraConfig:
    ip: str = "192.168.1.13"
    port: int = 80           # ONVIF/HTTP port
    username: str = "admin"
    password: str = "qazWSX((00"
    wsdl_dir: str | None = None  # If set, points to WSDL directory


class PTZController:
    def __init__(self, config: CameraConfig):
        self.config = config

        # Create ONVIF camera object
        # Only pass wsdl_dir if it's NOT None
        if self.config.wsdl_dir:
            self.camera = ONVIFCamera(
                self.config.ip,
                self.config.port,
                self.config.username,
                self.config.password,
                wsdl_dir=self.config.wsdl_dir,
            )
        else:
            self.camera = ONVIFCamera(
                self.config.ip,
                self.config.port,
                self.config.username,
                self.config.password,
            )

        # Create services
        self.media = self.camera.create_media_service()
        self.ptz = self.camera.create_ptz_service()

        # Get profiles
        profiles = self.media.GetProfiles()
        if not profiles:
            raise RuntimeError("No media profiles found on camera.")
        self.profile = profiles[0]

        # PTZ request objects
        self.request_continuous = self.ptz.create_type("ContinuousMove")
        self.request_continuous.ProfileToken = self.profile.token

        self.request_stop = self.ptz.create_type("Stop")
        self.request_stop.ProfileToken = self.profile.token

        self.request_gotopreset = self.ptz.create_type("GotoPreset")
        self.request_gotopreset.ProfileToken = self.profile.token

        self.request_setpreset = self.ptz.create_type("SetPreset")
        self.request_setpreset.ProfileToken = self.profile.token

        # Try to read configuration options (limits, speeds)
        try:
            cfg = {"ConfigurationToken": self.profile.PTZConfiguration.token}
            self.cfg_opts = self.ptz.GetConfigurationOptions(cfg)

            if (
                self.cfg_opts is not None
                and hasattr(self.cfg_opts, "Spaces")
                and self.cfg_opts.Spaces is not None
                and hasattr(self.cfg_opts.Spaces, "PanTiltVelocitySpace")
                and self.cfg_opts.Spaces.PanTiltVelocitySpace
                and hasattr(self.cfg_opts.Spaces.PanTiltVelocitySpace[0], "XRange")
                and hasattr(self.cfg_opts.Spaces.PanTiltVelocitySpace[0], "YRange")
                and hasattr(self.cfg_opts.Spaces, "ZoomVelocitySpace")
                and self.cfg_opts.Spaces.ZoomVelocitySpace
                and hasattr(self.cfg_opts.Spaces.ZoomVelocitySpace[0], "XRange")
            ):
                self.max_pan_speed = self.cfg_opts.Spaces.PanTiltVelocitySpace[0].XRange.Max
                self.max_tilt_speed = self.cfg_opts.Spaces.PanTiltVelocitySpace[0].YRange.Max
                self.max_zoom_speed = self.cfg_opts.Spaces.ZoomVelocitySpace[0].XRange.Max
            else:
                self.max_pan_speed = 0.5
                self.max_tilt_speed = 0.5
                self.max_zoom_speed = 0.5
        except Exception:
            # fallback to defaults
            self.max_pan_speed = 0.5
            self.max_tilt_speed = 0.5
            self.max_zoom_speed = 0.5

    def _normalized_speed(self, v: float, max_speed: float) -> float:
        """
        Clamp v in [-1, 1] and scale by max_speed.
        """
        v = max(-1.0, min(1.0, v))
        return v * max_speed

    def continuous_move(self, pan: float, tilt: float, zoom: float) -> None:
        """
        Continuous move:
        pan, tilt, zoom in range [-1, 1].

        Positive pan = right, negative = left
        Positive tilt = up, negative = down
        Positive zoom = zoom in, negative = zoom out
        """
        self.request_continuous.Velocity = {
            "PanTilt": {
                "x": self._normalized_speed(pan, self.max_pan_speed),
                "y": self._normalized_speed(tilt, self.max_tilt_speed),
            },
            "Zoom": {
                "x": self._normalized_speed(zoom, self.max_zoom_speed),
            },
        }
        self.ptz.ContinuousMove(self.request_continuous)

    def stop(self, pan_tilt: bool = True, zoom: bool = True) -> None:
        self.request_stop.PanTilt = pan_tilt
        self.request_stop.Zoom = zoom
        self.ptz.Stop(self.request_stop)

    def go_to_preset(self, preset_token: str) -> None:
        self.request_gotopreset.PresetToken = preset_token
        self.ptz.GotoPreset(self.request_gotopreset)

    def set_preset(self, name: str = "") -> str:
        """
        Save a preset at current position. Returns the preset token.
        """
        self.request_setpreset.PresetName = name
        resp = self.ptz.SetPreset(self.request_setpreset)
        if resp is not None and hasattr(resp, "PresetToken"):
            return resp.PresetToken
        else:
            return ""

    def list_presets(self):
        """
        Returns list of presets from the camera.
        """
        presets = self.ptz.GetPresets({"ProfileToken": self.profile.token})
        return presets


def run_keyboard():
    config = CameraConfig()
    print(f"Connecting to camera at {config.ip}:{config.port} as {config.username}...")
    controller = PTZController(config)
    print("Connected.\n")

    print("Keyboard PTZ control")
    print("--------------------")
    print("W / Up Arrow    - Tilt up")
    print("S / Down Arrow  - Tilt down")
    print("A / Left Arrow  - Pan left")
    print("D / Right Arrow - Pan right")
    print("Q               - Zoom in")
    print("E               - Zoom out")
    print("SPACE           - Stop motion")
    print("P               - List presets")
    print("G               - Go to preset (prompt)")
    print("O               - Save preset")
    print("ESC             - Quit")
    print()
    print("Make sure this console window is focused.")
    print("Press keys to control the camera...")

    move_speed = 1.0
    move_duration_sec = .3  # duration of each movement burst

    try:
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getch()

                # Special keys (arrows) start with b'\xe0'
                if ch == b"\xe0":
                    ch2 = msvcrt.getch()
                    # Arrow keys
                    if ch2 == b"H":  # up
                        print("Tilt up (↑)")
                        controller.continuous_move(pan=0.0, tilt=move_speed, zoom=0.0)
                        time.sleep(move_duration_sec)
                        controller.stop()
                    elif ch2 == b"P":  # down
                        print("Tilt down (↓)")
                        controller.continuous_move(pan=0.0, tilt=-move_speed, zoom=0.0)
                        time.sleep(move_duration_sec)
                        controller.stop()
                    elif ch2 == b"K":  # left
                        print("Pan left (←)")
                        controller.continuous_move(pan=-move_speed, tilt=0.0, zoom=0.0)
                        time.sleep(move_duration_sec)
                        controller.stop()
                    elif ch2 == b"M":  # right
                        print("Pan right (→)")
                        controller.continuous_move(pan=move_speed, tilt=0.0, zoom=0.0)
                        time.sleep(move_duration_sec)
                        controller.stop()
                    continue

                # Regular keys
                key = ch.decode(errors="ignore").lower()

                if ch == b"\x1b":  # ESC
                    print("ESC pressed. Exiting...")
                    controller.stop()
                    break

                elif key == "w":
                    print("Tilt up (W)")
                    controller.continuous_move(pan=0.0, tilt=move_speed, zoom=0.0)
                    time.sleep(move_duration_sec)
                    controller.stop()

                elif key == "s":
                    print("Tilt down (S)")
                    controller.continuous_move(pan=0.0, tilt=-move_speed, zoom=0.0)
                    time.sleep(move_duration_sec)
                    controller.stop()

                elif key == "a":
                    print("Pan left (A)")
                    controller.continuous_move(pan=-move_speed, tilt=0.0, zoom=0.0)
                    time.sleep(move_duration_sec)
                    controller.stop()

                elif key == "d":
                    print("Pan right (D)")
                    controller.continuous_move(pan=move_speed, tilt=0.0, zoom=0.0)
                    time.sleep(move_duration_sec)
                    controller.stop()

                elif key == "q":
                    print("Zoom in (Q)")
                    controller.continuous_move(pan=0.0, tilt=0.0, zoom=move_speed)
                    time.sleep(move_duration_sec)
                    controller.stop(zoom=True, pan_tilt=False)

                elif key == "e":
                    print("Zoom out (E)")
                    controller.continuous_move(pan=0.0, tilt=0.0, zoom=-move_speed)
                    time.sleep(move_duration_sec)
                    controller.stop(zoom=True, pan_tilt=False)

                elif ch == b" ":
                    print("Stop (SPACE)")
                    controller.stop()

                elif key == "p":
                    print("Listing presets...")
                    presets = controller.list_presets()
                    if not presets:
                        print("  No presets found.")
                    else:
                        for p in presets:
                            print(f"  Token: {p.token}, Name: {getattr(p, 'Name', '')}")

                elif key == "g":
                    # Go to preset (prompt in console)
                    controller.stop()
                    token = input("\nEnter preset token to go to: ").strip()
                    if token:
                        print(f"Going to preset {token}...")
                        controller.go_to_preset(token)
                    else:
                        print("No token entered.")
                    print("Back to keyboard control...")

                elif key == "o":
                    # Save preset
                    controller.stop()
                    name = input("\nEnter name for new preset (optional): ").strip()
                    token = controller.set_preset(name=name)
                    print(f"Preset saved. Token: {token}")
                    print("Back to keyboard control...")

            # small sleep to avoid busy-waiting
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt. Stopping and exiting...")
    finally:
        controller.stop()


if __name__ == "__main__":
    run_keyboard()
