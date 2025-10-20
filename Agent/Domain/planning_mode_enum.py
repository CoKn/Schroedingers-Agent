from enum import Enum, auto


class PlanningMode(Enum):
    REACT = auto()
    HIERARCHICAL = auto()  # Pre-planning with adaptive refinement  