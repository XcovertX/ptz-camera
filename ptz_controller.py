"""
ptz_controller.py

Basic ONVIF PTZ control for an IP dome camera.

Assumptions:
- Camera supports ONVIF PTZ.
- Camera IP: 192.168.1.13
- Port: 80
- Username: admin
- Password: 123456

Usage:
    python ptz_controller.py
"""

from __future__ import annotations
import sys
import time
from dataclasses import dataclass

try:
    # for onvif_zeep / onvif-zeep
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
    wsdl_dir: str | None = None  # If None, onvif will use its built-in WSDLs


class PTZController:
    def __init__(self, config: CameraConfig):
        self.config = config
        if config.wsdl_dir:
            # Use a custom WSDL directory if you set one in CameraConfig
            self.camera = ONVIFCamera(
                config.ip,
                config.port,
                config.username,
                config.password,
                wsdl_dir=config.wsdl_dir
            )
        else:
            # Let the library use its built-in/default WSDLs
            self.camera = ONVIFCamera(
                config.ip,
                config.port,
                config.username,
                config.password
            )

        # Services
        self.media = self.camera.create_media_service()
        self.ptz = self.camera.create_ptz_service()

        # Use first profile by default
        profiles = self.media.GetProfiles()
        if not profiles:
            raise RuntimeError("No media profiles found on camera.")
        self.profile = profiles[0]

        # Cache PTZ configuration
        self.request_continuous = self.ptz.create_type("ContinuousMove")
        self.request_continuous.ProfileToken = self.profile.token

        self.request_stop = self.ptz.create_type("Stop")
        self.request_stop.ProfileToken = self.profile.token

        self.request_gotopreset = self.ptz.create_type("GotoPreset")
        self.request_gotopreset.ProfileToken = self.profile.token

        self.request_setpreset = self.ptz.create_type("SetPreset")
        self.request_setpreset.ProfileToken = self.profile.token

        # Get PTZ configuration options (limits, speed ranges)
        self.cfg_opts = self.ptz.GetConfigurationOptions(
            {"ConfigurationToken": self.profile.PTZConfiguration.token}
        )

        # Precompute max speeds if available
        self.max_pan_speed = 0.5
        self.max_tilt_speed = 0.5
        self.max_zoom_speed = 0.5

        try:
            if self.cfg_opts is not None and getattr(self.cfg_opts, "Spaces", None) is not None:
                spaces = self.cfg_opts.Spaces
                if hasattr(spaces, "PanTiltVelocitySpace") and spaces.PanTiltVelocitySpace:
                    self.max_pan_speed = spaces.PanTiltVelocitySpace[0].XRange.Max
                    self.max_tilt_speed = spaces.PanTiltVelocitySpace[0].YRange.Max
                if hasattr(spaces, "ZoomVelocitySpace") and spaces.ZoomVelocitySpace:
                    self.max_zoom_speed = spaces.ZoomVelocitySpace[0].XRange.Max
        except Exception:
            # Use defaults if we can’t read from camera
            pass

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
            print("Warning: No PresetToken returned from camera.")
            return ""

    def list_presets(self):
        """
        Returns list of presets from the camera.
        """
        presets = self.ptz.GetPresets({"ProfileToken": self.profile.token})
        return presets


def run_cli():
    config = CameraConfig()
    print(f"Connecting to camera at {config.ip}:{config.port} as {config.username}...")
    controller = PTZController(config)
    print("Connected.\n")

    menu = """
PTZ Control Menu
----------------
Movement (continuous):
  1) Pan LEFT
  2) Pan RIGHT
  3) Tilt UP
  4) Tilt DOWN
  5) Zoom IN
  6) Zoom OUT
  7) STOP all motion

Presets:
  8) List presets
  9) Go to preset
  10) Save preset

Other:
  0) Quit

Enter choice: """

    # basic speed for all moves (in [-1, 1])
    move_speed = 0.5
    move_duration_sec = 0.5  # how long we move before auto-stop

    while True:
        try:
            choice = input(menu).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            controller.stop()
            sys.exit(0)

        if choice == "0":
            print("Stopping and exiting...")
            controller.stop()
            break

        elif choice == "1":  # left
            print("Panning left...")
            controller.continuous_move(pan=-move_speed, tilt=0.0, zoom=0.0)
            time.sleep(move_duration_sec)
            controller.stop()

        elif choice == "2":  # right
            print("Panning right...")
            controller.continuous_move(pan=move_speed, tilt=0.0, zoom=0.0)
            time.sleep(move_duration_sec)
            controller.stop()

        elif choice == "3":  # up
            print("Tilting up...")
            controller.continuous_move(pan=0.0, tilt=move_speed, zoom=0.0)
            time.sleep(move_duration_sec)
            controller.stop()

        elif choice == "4":  # down
            print("Tilting down...")
            controller.continuous_move(pan=0.0, tilt=-move_speed, zoom=0.0)
            time.sleep(move_duration_sec)
            controller.stop()

        elif choice == "5":  # zoom in
            print("Zooming in...")
            controller.continuous_move(pan=0.0, tilt=0.0, zoom=move_speed)
            time.sleep(move_duration_sec)
            controller.stop(zoom=True, pan_tilt=False)

        elif choice == "6":  # zoom out
            print("Zooming out...")
            controller.continuous_move(pan=0.0, tilt=0.0, zoom=-move_speed)
            time.sleep(move_duration_sec)
            controller.stop(zoom=True, pan_tilt=False)

        elif choice == "7":  # stop
            print("Stopping motion...")
            controller.stop()

        elif choice == "8":  # list presets
            presets = controller.list_presets()
            if not presets:
                print("No presets found.")
            else:
                print("\nPresets:")
                for p in presets:
                    print(f"  Token: {p.token}, Name: {getattr(p, 'Name', '')}")
                print()

        elif choice == "9":  # go to preset
            token = input("Enter preset token: ").strip()
            if not token:
                print("Preset token cannot be empty.")
                continue
            print(f"Going to preset {token}...")
            controller.go_to_preset(token)

        elif choice == "10":  # save preset
            name = input("Enter preset name (optional): ").strip()
            token = controller.set_preset(name=name)
            print(f"Preset saved. Token: {token}")

        else:
            print("Invalid choice. Try again.")

    controller.stop()


if __name__ == "__main__":
    run_cli()
