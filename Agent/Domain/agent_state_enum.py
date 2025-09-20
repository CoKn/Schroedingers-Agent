from enum import Enum, auto

class AgentState(Enum):
    PLANNING = auto()
    EXECUTING = auto()
    SUMMARISING = auto()
    DONE = auto()
    ERROR = auto()

