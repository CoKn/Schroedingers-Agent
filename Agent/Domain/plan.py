from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, computed_field
from uuid import uuid4

from Agent.Domain.goal_state_enum import GoalStatus


class Node(BaseModel):
    """
    Represents a goal in the hierarchical plan.

    Key points:
    - `id` is a stable logical identity for this goal.
    - `version` is the version of this node *for that goal*.
    - `supersedes_node_id` lets you track that this node replaces an older version.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Stable logical identity for this goal
    id: str = Field(default_factory=lambda: str(uuid4()))

    value: str
    abstraction_score: Optional[float] = None

    # Structural links
    parent: Optional['Node'] = Field(default=None, exclude=True, repr=False)
    children: Optional[List['Node']] = Field(default_factory=list)

    # Execution / lifecycle
    status: GoalStatus = GoalStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Versioning
    version: int = 1
    supersedes_node_id: Optional[str] = None 
    
    # MCP tool information for leaf nodes
    mcp_tool: Optional[str] = None
    tool_args: Optional[dict] = None

    # Assumed world model for this goal
    assumed_preconditions: Optional[List[str]] = Field(default_factory=list)
    assumed_effects: Optional[List[str]] = Field(default_factory=list)

    @computed_field
    @property
    def is_leaf(self) -> bool:
        return not self.children

    @computed_field
    @property
    def is_executable(self) -> bool:
        return (
            self.mcp_tool is not None or
            (self.abstraction_score is not None and self.abstraction_score < 0.3)
        )
    
    def to_dict(self, include_children: bool = True) -> dict:
        data = self.model_dump(
            exclude={'parent'}  # avoid upward recursion
        )
        if include_children:
            data['children'] = [c.to_dict(include_children=True) for c in self.children]
        return data

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

    # Plan-level revisioning
    revision: int = 1
    parent_revision: Optional[int] = None
    replanned_from_node_id: Optional[str] = None  # root of subtree that was replanned


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
    

    def find_node(self, node_id: str) -> Optional[Node]:
        """Find a node by its id via DFS."""
        if not self.root:
            return None

        def dfs(node: Node) -> Optional[Node]:
            if node.id == node_id:
                return node
            for child in node.children:
                found = dfs(child)
                if found:
                    return found
            return None

        return dfs(self.root)
    
    def new_revision_with_subtree(self, node_id: str, new_subtree_root: Node) -> "Tree":
        """
        Create a NEW Tree revision where the subtree rooted at `node_id`
        is replaced by `new_subtree_root`.

        - The original tree is unchanged.
        - The new tree has `revision = self.revision + 1`.
        - `parent_revision` points back to this tree's revision.
        - The new subtree root gets `supersedes_node_id` set to the id of
          the old subtree root.
        """
        # Deep-copy the entire tree so we don't mutate the original
        new_tree: Tree = self.model_copy(deep=True)
        new_tree.parent_revision = self.revision
        new_tree.revision = self.revision + 1
        new_tree.replanned_from_node_id = node_id

        target = new_tree.find_node(node_id)
        if target is None:
            raise ValueError(f"Cannot replan subtree: node id {node_id!r} not found")

        # Remember which node we are superseding
        original_id = target.id
        new_subtree_root.supersedes_node_id = original_id

        # Attach the new subtree in place of the old one
        parent = target.parent
        if parent is None:
            # Replacing the root
            new_subtree_root.parent = None
            new_tree.root = new_subtree_root
        else:
            # Replace in parent's children list
            for idx, child in enumerate(parent.children):
                if child.id == target.id:
                    parent.children[idx] = new_subtree_root
                    new_subtree_root.parent = parent
                    break

        return new_tree
    

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
                children=[],
                assumed_effects=json_node.get("assumed_effects", []),
                assumed_preconditions=json_node.get("assumed_preconditions", [])
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