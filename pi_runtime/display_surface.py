from __future__ import annotations

from dataclasses import dataclass
import io
import logging
import math
from pathlib import Path
from typing import Dict, Optional

from .config import UiConfig

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageColor, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = None
    ImageColor = None
    ImageDraw = None
    ImageFont = None

try:
    _RESAMPLE_BICUBIC = Image.Resampling.BICUBIC if Image is not None else None
except Exception:  # pragma: no cover
    _RESAMPLE_BICUBIC = Image.BICUBIC if Image is not None else None


@dataclass
class DisplayStatus:
    ready: bool
    driver: str
    detail: str = ""


class BaseDisplaySurface:
    def __init__(self, config: UiConfig) -> None:
        self.config = config

    def get_status(self) -> DisplayStatus:
        return DisplayStatus(ready=False, driver=str(self.config.display_driver), detail="disabled")

    def render(self, payload: Dict[str, object]) -> None:
        _ = payload

    def render_preview_png(self, payload: Dict[str, object]) -> bytes:
        _ = payload
        return b""

    def close(self) -> None:
        return


class NullDisplaySurface(BaseDisplaySurface):
    pass


class St7789DisplaySurface(BaseDisplaySurface):
    BREATH_SPEED = 800.0
    BREATH_AMP_Y = 3.0
    BREATH_AMP_H = 2.4

    def __init__(self, config: UiConfig) -> None:
        super().__init__(config)
        self._device = None
        self._backlight = None
        self._font_regular = None
        self._font_bold = None
        self._error = ""
        self._width = int(config.expression_width or 320)
        self._height = int(config.expression_height or 240)
        if Image is None or ImageDraw is None or ImageFont is None:
            self._error = "pillow unavailable"
            return

        self._load_fonts()

        try:
            from luma.core.interface.serial import spi  # type: ignore
            from luma.lcd.device import st7789  # type: ignore
        except Exception as exc:  # pragma: no cover
            self._error = f"luma unavailable: {exc}"
            return

        try:
            serial = spi(
                port=int(config.spi_port),
                device=int(config.spi_device),
                gpio_DC=int(config.spi_dc_gpio),
                gpio_RST=(None if config.spi_reset_gpio is None else int(config.spi_reset_gpio)),
                bus_speed_hz=int(config.spi_bus_speed_hz),
            )
            self._device = st7789(
                serial,
                width=self._width,
                height=self._height,
                rotate=max(0, min(3, int(config.spi_rotation // 90))),
                h_offset=int(config.spi_offset_x),
                v_offset=int(config.spi_offset_y),
            )
            self._init_backlight()
        except Exception as exc:  # pragma: no cover
            self._error = str(exc)
            self._device = None

    def _init_backlight(self) -> None:
        if self.config.spi_backlight_gpio is None:
            return
        try:
            from gpiozero import LED  # type: ignore

            self._backlight = LED(int(self.config.spi_backlight_gpio))
            self._backlight.on()
        except Exception as exc:  # pragma: no cover
            logger.warning("st7789 backlight init failed: %s", exc)
            self._backlight = None

    def _load_fonts(self) -> None:
        candidates = [
            ("C:/Windows/Fonts/msyh.ttc", 18, 28),
            ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 18, 28),
            ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 18, 28),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18, 28),
        ]
        for path, regular_size, bold_size in candidates:
            try:
                if Path(path).exists():
                    self._font_regular = ImageFont.truetype(path, regular_size)
                    self._font_bold = ImageFont.truetype(path, bold_size)
                    return
            except Exception:
                continue
        self._font_regular = ImageFont.load_default()
        self._font_bold = ImageFont.load_default()

    def get_status(self) -> DisplayStatus:
        return DisplayStatus(
            ready=self._device is not None,
            driver="st7789",
            detail=self._error or "ok",
        )

    def render(self, payload: Dict[str, object]) -> None:
        image = self._compose_frame(payload)
        if image is None or self._device is None:
            return
        self._device.display(image)

    def render_preview_png(self, payload: Dict[str, object]) -> bytes:
        image = self._compose_frame(payload)
        if image is None:
            return b""
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _compose_frame(self, payload: Dict[str, object]):
        if Image is None or ImageDraw is None or ImageFont is None:
            return None
        ui_state = dict(payload.get("ui_state") or {})
        if not bool(ui_state.get("screen_awake", True)):
            return Image.new("RGB", (self._width, self._height), "#000000")
        page = str(ui_state.get("page") or "expression")
        if page == "settings":
            return self._render_settings(payload)
        return self._render_expression(payload)

    def _render_expression(self, payload: Dict[str, object]):
        expr = dict(payload.get("expression_state") or {})
        timestamp_ms = int(payload.get("timestamp_ms") or 0)
        breath_t = timestamp_ms / self.BREATH_SPEED
        breath_y = math.sin(breath_t) * self.BREATH_AMP_Y
        breath_h = math.sin(breath_t + 1.5) * self.BREATH_AMP_H
        blink = bool(expr.get("blinking"))
        gaze_x = float(expr.get("gaze_x", 0.0) or 0.0)
        gaze_y = float(expr.get("gaze_y", 0.0) or 0.0)

        image = Image.new("RGBA", (self._width, self._height), "#040913")
        draw = ImageDraw.Draw(image)
        self._draw_background(draw, image.size)
        self._draw_eye(image, expr.get("left"), blink, gaze_x, gaze_y, breath_y, breath_h)
        self._draw_eye(image, expr.get("right"), blink, gaze_x, gaze_y, breath_y, breath_h)
        self._draw_chip(draw, (16, 16, 142, 42), "Emotion Pi", fill="#0b2434", text_fill="#67e8f9")
        self._draw_text(draw, (18, 176), "Pi expression surface", self._font_bold, "#e6eefb")
        self._draw_text(draw, (18, 206), str(expr.get("expression_id") or "expression"), self._font_regular, "#9fb5d9")
        self._draw_text(draw, (184, 206), str(expr.get("reason") or "ambient"), self._font_regular, "#8fd6e2")
        return image.convert("RGB")

    def _render_settings(self, payload: Dict[str, object]):
        settings = dict(payload.get("settings") or {})
        voice = dict(payload.get("voice_state") or {})
        display = dict(payload.get("display_state") or {})
        image = Image.new("RGBA", (self._width, self._height), "#060b14")
        draw = ImageDraw.Draw(image)
        self._draw_background(draw, image.size, accent="#0e7490")
        self._draw_chip(draw, (16, 14, 126, 42), "Settings", fill="#0f2234", text_fill="#67e8f9")
        self._draw_text(draw, (18, 48), "Pi settings page", self._font_bold, "#f3f7ff")
        media = dict(settings.get("media") or {})
        wake = dict(settings.get("wake") or {})
        behavior = dict(settings.get("behavior") or {})
        cards = [
            ("Mode", str(settings.get("mode") or "normal")),
            ("Wake", "on" if bool(wake.get("enabled", True)) else "off"),
            ("Wake phrase", str(wake.get("wake_phrase") or "robot")),
            ("Audio", "on" if bool(media.get("audio_enabled", True)) else "off"),
            ("Camera", "on" if bool(media.get("camera_enabled", True)) else "off"),
            ("Voice", f"{settings.get('voice', {}).get('robot_tts_provider', 'tts')} + {voice.get('asr_engine', 'stt')}"),
            ("Cooldown", f"{behavior.get('cooldown_min', 30)} min"),
            ("Display", f"{display.get('driver', 'st7789')} / {'ready' if display.get('ready') else 'idle'}"),
        ]
        for idx, (label, value) in enumerate(cards):
            row = idx // 2
            col = idx % 2
            x = 16 + (col * 150)
            y = 86 + (row * 42)
            draw.rounded_rectangle((x, y, x + 138, y + 34), radius=12, fill="#0a1523", outline="#1b3146", width=1)
            self._draw_text(draw, (x + 10, y + 5), label, self._font_regular, "#88a0bc")
            self._draw_text(draw, (x + 10, y + 18), value, self._font_regular, "#eef5ff")
        self._draw_text(draw, (18, 218), "Desktop settings stay the primary control surface.", self._font_regular, "#9fb5d9")
        return image.convert("RGB")

    def _draw_background(self, draw, size, accent: str = "#0b2434") -> None:
        width, height = size
        draw.rectangle((0, 0, width, height), fill="#050913")
        draw.ellipse((-60, -40, width * 0.75, height * 0.8), fill="#0a1626")
        draw.ellipse((width * 0.35, height * 0.1, width + 50, height), fill=accent)

    def _draw_chip(self, draw, box, text: str, fill: str, text_fill: str) -> None:
        draw.rounded_rectangle(box, radius=14, fill=fill, outline="#1b3146", width=1)
        self._draw_text(draw, (box[0] + 12, box[1] + 8), text, self._font_regular, text_fill)

    def _draw_text(self, draw, pos, text: str, font, fill: str) -> None:
        draw.text(pos, str(text or ""), font=font, fill=fill)

    def _draw_eye(
        self,
        image,
        eye_state: Optional[Dict[str, object]],
        blinking: bool,
        gaze_x: float,
        gaze_y: float,
        breath_y: float,
        breath_h: float,
    ) -> None:
        if not eye_state or Image is None or ImageDraw is None:
            return

        width = float(eye_state.get("w", 56.0) or 56.0)
        draw_h = 2.0 if blinking else max(2.0, float(eye_state.get("h", 56.0) or 56.0) + breath_h)
        x = float(eye_state.get("x", self._width / 2.0)) - (width / 2.0) + float(gaze_x)
        y = (
            float(eye_state.get("y", self._height / 2.0))
            - (draw_h / 2.0)
            + float(gaze_y)
            + float(breath_y)
        )
        radius = max(1.0, min(float(eye_state.get("r", draw_h / 2.0) or (draw_h / 2.0)), draw_h / 2.0, width / 2.0))
        rotation = float(eye_state.get("rot", 0.0) or 0.0)
        color = str(eye_state.get("color") or "#7ee7ff")
        fill = ImageColor.getrgb(color) if ImageColor is not None else (126, 231, 255)

        layer_w = int(max(12, round(width + 16)))
        layer_h = int(max(12, round(draw_h + 16)))
        layer = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)
        layer_draw.rounded_rectangle(
            (8, 8, layer_w - 8, layer_h - 8),
            radius=max(2, int(round(radius))),
            fill=fill,
        )

        if abs(rotation) >= 0.1 and _RESAMPLE_BICUBIC is not None:
            layer = layer.rotate(rotation, expand=True, resample=_RESAMPLE_BICUBIC)

        paste_x = int(round(x - ((layer.width - width) / 2.0)))
        paste_y = int(round(y - ((layer.height - draw_h) / 2.0)))
        image.alpha_composite(layer, (paste_x, paste_y))

    def close(self) -> None:
        try:
            if self._device is not None:
                self._device.clear()
        except Exception:
            pass
        try:
            if self._backlight is not None:
                self._backlight.off()
                self._backlight.close()
        except Exception:
            pass


def build_display_surface(config: UiConfig) -> BaseDisplaySurface:
    driver = str(config.display_driver or "web").strip().lower()
    if driver == "st7789":
        surface = St7789DisplaySurface(config)
        if not surface.get_status().ready:
            logger.warning("st7789 display unavailable, preview-only mode: %s", surface.get_status().detail)
        return surface
    return NullDisplaySurface(config)
