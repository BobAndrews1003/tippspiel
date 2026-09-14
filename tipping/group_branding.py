from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

from .group_plans import group_has_entitlement


if TYPE_CHECKING:
    from .models import (
        Group,
        GroupBranding,
    )


HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

DEFAULT_PRIMARY_COLOR = "#438CFF"
DEFAULT_ACCENT_COLOR = "#7257E8"
DEFAULT_BACKGROUND_COLOR = "#183153"
DEFAULT_THEME_MODE = "light"
DEFAULT_BRAND_INTENSITY = "normal"

THEME_MODES = {"dark", "light"}
BRAND_INTENSITIES = {"subtle", "normal", "strong"}

INTENSITY_VALUES = {
    "subtle": {
        "wash": 0.10,
        "accent_wash": 0.04,
        "border": 0.20,
        "highlight": 0.50,
        "button_shadow": 0.12,
    },
    "normal": {
        "wash": 0.20,
        "accent_wash": 0.08,
        "border": 0.30,
        "highlight": 0.72,
        "button_shadow": 0.23,
    },
    "strong": {
        "wash": 0.32,
        "accent_wash": 0.15,
        "border": 0.44,
        "highlight": 0.92,
        "button_shadow": 0.34,
    },
}


@dataclass(frozen=True)
class BrandingStyle:
    primary_color: str = DEFAULT_PRIMARY_COLOR
    accent_color: str = DEFAULT_ACCENT_COLOR
    background_color: str = DEFAULT_BACKGROUND_COLOR
    theme_mode: str = DEFAULT_THEME_MODE
    brand_intensity: str = DEFAULT_BRAND_INTENSITY


def normalize_hex_color(
    value: object,
    default: str,
) -> str:
    candidate = str(value or "").strip()

    if not HEX_COLOR_PATTERN.fullmatch(candidate):
        return default

    return candidate.upper()


def sanitize_choice(
    value: object,
    *,
    choices: set[str],
    default: str,
) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in choices else default


def branding_style_from_object(
    branding: GroupBranding,
) -> BrandingStyle:
    return BrandingStyle(
        primary_color=normalize_hex_color(
            branding.primary_color,
            DEFAULT_PRIMARY_COLOR,
        ),
        accent_color=normalize_hex_color(
            branding.accent_color,
            DEFAULT_ACCENT_COLOR,
        ),
        background_color=normalize_hex_color(
            branding.background_color,
            DEFAULT_BACKGROUND_COLOR,
        ),
        theme_mode=sanitize_choice(
            branding.theme_mode,
            choices=THEME_MODES,
            default=DEFAULT_THEME_MODE,
        ),
        brand_intensity=sanitize_choice(
            branding.brand_intensity,
            choices=BRAND_INTENSITIES,
            default=DEFAULT_BRAND_INTENSITY,
        ),
    )


def branding_style_from_query(
    values: Mapping[str, object],
) -> BrandingStyle:
    """Filtert Vorschauparameter auf dieselben Werte wie das Modell."""

    return BrandingStyle(
        primary_color=normalize_hex_color(
            values.get("primary"),
            DEFAULT_PRIMARY_COLOR,
        ),
        accent_color=normalize_hex_color(
            values.get("accent"),
            DEFAULT_ACCENT_COLOR,
        ),
        background_color=normalize_hex_color(
            values.get("background"),
            DEFAULT_BACKGROUND_COLOR,
        ),
        theme_mode=sanitize_choice(
            values.get("theme"),
            choices=THEME_MODES,
            default=DEFAULT_THEME_MODE,
        ),
        brand_intensity=sanitize_choice(
            values.get("intensity"),
            choices=BRAND_INTENSITIES,
            default=DEFAULT_BRAND_INTENSITY,
        ),
    )


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    return tuple(
        int(value[index:index + 2], 16)
        for index in (1, 3, 5)
    )


def _rgb_css(value: str) -> str:
    return ",".join(str(channel) for channel in _hex_to_rgb(value))


def _mix_colors(
    first: str,
    second: str,
    second_weight: float,
) -> str:
    first_rgb = _hex_to_rgb(first)
    second_rgb = _hex_to_rgb(second)
    mixed = tuple(
        round(
            first_channel * (1 - second_weight)
            + second_channel * second_weight
        )
        for first_channel, second_channel in zip(
            first_rgb,
            second_rgb,
        )
    )
    return "#" + "".join(
        f"{channel:02X}" for channel in mixed
    )


def _relative_luminance(value: str) -> float:
    red, green, blue = (
        channel / 255 for channel in _hex_to_rgb(value)
    )

    def linearize(channel: float) -> float:
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * linearize(red)
        + 0.7152 * linearize(green)
        + 0.0722 * linearize(blue)
    )


def _contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted(
        (
            _relative_luminance(first),
            _relative_luminance(second),
        ),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def _contrast_color(value: str) -> str:
    luminance = _relative_luminance(value)
    return "#08111F" if luminance > 0.46 else "#FFFFFF"


def _readable_brand_color(
    value: str,
    background: str,
    *,
    light_theme: bool,
) -> str:
    """Erhält den Farbton, erhöht aber bei Bedarf den Textkontrast."""

    if _contrast_ratio(value, background) >= 4.5:
        return value

    target = "#000000" if light_theme else "#FFFFFF"

    for percentage in range(10, 91, 10):
        candidate = _mix_colors(
            value,
            target,
            percentage / 100,
        )

        if _contrast_ratio(candidate, background) >= 4.5:
            return candidate

    return target


def render_group_branding_css(
    style: BrandingStyle,
    *,
    preview: bool = False,
) -> str:
    """Erzeugt ausschließlich aus validierten Werten CSS-Variablen."""

    primary = style.primary_color
    accent = style.accent_color
    background_tone = style.background_color
    intensity = INTENSITY_VALUES[style.brand_intensity]

    if style.theme_mode == "light":
        background = _mix_colors(
            "#F4F7FC",
            background_tone,
            0.08,
        )
        card = _mix_colors("#FFFFFF", background_tone, 0.035)
        surface = _mix_colors("#EDF2F9", background_tone, 0.06)
        text = "#17233B"
        muted = "#60708F"
        border = "rgba(23,35,59,.14)"
        input_background = "rgba(23,35,59,.055)"
        nav_background = "rgba(250,252,255,.88)"
        shadow = "0 12px 34px rgba(38,55,86,.12)"
        primary_dark = _mix_colors(primary, "#000000", 0.13)
    else:
        background = _mix_colors(
            "#0B1220",
            background_tone,
            0.26,
        )
        card = _mix_colors("#111A2E", background_tone, 0.18)
        surface = _mix_colors("#17243C", background_tone, 0.15)
        text = "#E8EEFC"
        muted = "#A9B6D6"
        border = "rgba(255,255,255,.10)"
        input_background = "rgba(255,255,255,.06)"
        nav_background = "rgba(11,18,32,.80)"
        shadow = "0 10px 30px rgba(0,0,0,.25)"
        primary_dark = _mix_colors(primary, "#000000", 0.24)

    selector = (
        ".group-brand-preview"
        if preview
        else "body.group-branding-active"
    )

    variables = {
        "--group-brand-primary": primary,
        "--group-brand-primary-dark": primary_dark,
        "--group-brand-primary-rgb": _rgb_css(primary),
        "--group-brand-primary-readable": _readable_brand_color(
            primary,
            background,
            light_theme=style.theme_mode == "light",
        ),
        "--group-brand-accent": accent,
        "--group-brand-accent-rgb": _rgb_css(accent),
        "--group-brand-on-primary": _contrast_color(primary),
        "--group-brand-background": background,
        "--group-brand-card": card,
        "--group-brand-surface": surface,
        "--group-brand-text": text,
        "--group-brand-muted": muted,
        "--group-brand-border": border,
        "--group-brand-input-bg": input_background,
        "--group-brand-nav-bg": nav_background,
        "--group-brand-shadow": shadow,
        "--group-brand-success-text": (
            "#137546"
            if style.theme_mode == "light"
            else "#86DFAE"
        ),
        "--group-brand-warning-text": (
            "#8A5A00"
            if style.theme_mode == "light"
            else "#FFD08C"
        ),
        "--group-brand-danger-text": (
            "#B42338"
            if style.theme_mode == "light"
            else "#FFABAB"
        ),
        "--group-brand-wash": str(intensity["wash"]),
        "--group-brand-accent-wash": str(intensity["accent_wash"]),
        "--group-brand-border-alpha": str(intensity["border"]),
        "--group-brand-highlight-alpha": str(intensity["highlight"]),
        "--group-brand-button-shadow-alpha": str(
            intensity["button_shadow"]
        ),
    }

    declarations = "\n".join(
        f"  {name}:{value};"
        for name, value in variables.items()
    )

    return (
        "/* Puntero: validierte Gruppenfarben */\n"
        f"{selector}{{\n{declarations}\n}}\n"
    )


def get_visible_group_branding(
    group: Group | None,
) -> GroupBranding | None:
    """Liefert Branding nur bei einer wirksamen Club-Berechtigung."""

    if (
        group is None
        or not group_has_entitlement(
            group,
            "branding",
        )
    ):
        return None

    return getattr(
        group,
        "branding",
        None,
    )
