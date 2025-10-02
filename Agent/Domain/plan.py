from typing import List, Optional, Field
from datetime import datetime
from pydantic import BaseModel

from Agent.Domain.goal_state_enum import GoalStatus


class Node(BaseModel):
    value: str
    abstraction_score: float = None
    parent: Optional['Node']
    children: Optional[List['Node']]
    status: GoalStatus = GoalStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.now())
    completed_at: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True

    
    def get_parent_node(self) -> 'Node':
        return self.parent
    
    def get_children(self) -> List['Node']:
        return self.children



# a tree constitues a hierachical plan for the agent with its decomposed goal
class Tree:
    root: Node = None
    abstraction_score_range: List[float]


    def add_node(self, value, parent=None, children=None):
        new_node = Node(value=value, parent=parent, children=children)
        if self.root == None:
            self.root = new_node
        else:
            new_node.parent.children.append(new_node)
        return new_node
    
    def get_decendants(self, node: Node) -> List[Node]:
        decendats = []
        if node.children:
            for chield in node.children:
                decendats.extend(self.get_decendants(chield)) 
            return decendats
        return None
    
    def remove_node(self, node: Node) -> 'Tree':
        if node.parent:
            node.parent.children.remove(node)

        if self.root == node:
            self.root = None

        decendats = self.get_decendance(node)
        for decendat in decendats[:-1]:
            decendat.parent.children.remove(decendat)

        return self
        

    def get_leaves(self) -> List[Node]:
        if not self.root:
            return []
        leaves = []
    
        def collect_leaves(node: Node):
            if not node.children or len(node.children) == 0:
                leaves.append(node)
            else:
                for child in node.children:
                    collect_leaves(child)
        
            collect_leaves(self.root)
            return leaves

    
    def traverse(self):
        ...

    def _breadth_first_traversal(self):
        ...
    
    def _breadth_first_traversal(self):
        ...