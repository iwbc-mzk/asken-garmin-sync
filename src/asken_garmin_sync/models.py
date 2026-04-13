from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BodyComposition:
    date: date
    weight_kg: float
    body_fat_percent: float | None = None


@dataclass(frozen=True)
class ActivityCalories:
    date: date
    calories_burned: int
