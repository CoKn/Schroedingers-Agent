from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from Agent.Domain.goal_state_enum import GoalStatus


class Node(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    value: str
    abstraction_score: Optional[float] = None
    parent: Optional['Node'] = None
    children: Optional[List['Node']] = Field(default_factory=list)
    status: GoalStatus = GoalStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    # MCP tool information for leaf nodes
    mcp_tool: Optional[str] = None
    tool_args: Optional[dict] = None

    def model_post_init(self, __context) -> None:
        """Validate abstraction score is within valid range."""
        if self.abstraction_score is not None and not (0.0 <= self.abstraction_score <= 1.0):
            raise ValueError(f"Abstraction score must be between 0.0 and 1.0, got {self.abstraction_score}")

    def is_leaf(self) -> bool:
        """Check if this node is a leaf (no children)."""
        return not self.children or len(self.children) == 0

    def is_executable(self) -> bool:
        """Check if this node is executable (has MCP tool or low abstraction)."""
        return self.mcp_tool is not None or (self.abstraction_score is not None and self.abstraction_score < 0.3)

    
    def get_parent_node(self) -> 'Node':
        return self.parent
    
    def get_children(self) -> List['Node']:
        return self.children



# a tree constitues a hierarchical plan for the agent with its decomposed goal
class Tree(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    root: Optional[Node] = None
    abstraction_score_range: List[float] = Field(default_factory=list)


    def add_node(self, value, parent=None, children=None):
        new_node = Node(value=value, parent=parent, children=children)
        if self.root is None:
            self.root = new_node
        else:
            if new_node.parent:
                new_node.parent.children.append(new_node)
        return new_node
    
    def get_descendants(self, node: Node) -> List[Node]:
        descendants = []
        if node.children:
            for child in node.children:
                descendants.append(child)
                descendants.extend(self.get_descendants(child))
        return descendants
    
    def remove_node(self, node: Node) -> 'Tree':
        if node.parent:
            node.parent.children.remove(node)

        if self.root == node:
            self.root = None

        descendants = self.get_descendants(node)
        for descendant in descendants:
            if descendant.parent:
                descendant.parent.children.remove(descendant)

        return self
        

    def get_leaves(self) -> List[Node]:
        """Get all leaf nodes in the tree (nodes with no children)."""
        if not self.root:
            return []
        leaves = []
    
        def collect_leaves(node: Node):
            if node.is_leaf():
                leaves.append(node)
            else:
                for child in node.children or []:
                    collect_leaves(child)
        
        collect_leaves(self.root)
        return leaves

    
    def traverse(self):
        ...

    def _breadth_first_traversal(self):
        ...
    
    def _breadth_first_traversal(self):
        ...


    @staticmethod
    def _parse_json_to_tree(json_data: dict) -> 'Tree':
        """Parse JSON response into Tree structure with Node objects."""
        tree = Tree()
        
        def create_node_from_json(json_node: dict, parent: Node = None) -> Node:
            # Create Node from JSON data
            node = Node(
                value=json_node.get("value", ""),
                abstraction_score=json_node.get("abstraction_score", 0.0),
                parent=parent,
                children=[]
            )
            
            # Add MCP tool information if present (for leaf nodes)
            if "mcp_tool" in json_node:
                node.mcp_tool = json_node["mcp_tool"]
                node.tool_args = json_node.get("tool_args", {})
            
            # Recursively create children
            if "children" in json_node and json_node["children"]:
                for child_json in json_node["children"]:
                    child_node = create_node_from_json(child_json, parent=node)
                    node.children.append(child_node)
            
            return node
        
        # Start with root_goal from JSON
        if "root_goal" in json_data:
            tree.root = create_node_from_json(json_data["root_goal"])
        else:
            raise ValueError("JSON response missing 'root_goal' field")
        
        return tree