from dataclasses import dataclass

@dataclass
class PlotConfig:
    x_col: str
    y_col: str
    z_col: str
    mode: str
    aspect: bool
    show_shadow: bool
    max_points: int = 5000