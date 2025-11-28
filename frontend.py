"""Streamlit app for inspecting plan tree + trace timeline from ChromaDB."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional, Set

import chromadb
import plotly.graph_objects as go
import streamlit as st


# Adjust if your DB lives somewhere else
DB_DIR = Path(__file__).resolve().parent / "DB"

STATUS_COLORS = {
    "PENDING": "#fbbf24",
    "IN_PROGRESS": "#38bdf8",
    "COMPLETED": "#22c55e",
    "ERROR": "#ef4444",
    "FAILED": "#ef4444",
}


# --- Basic infra / helpers ----------------------------------------------------


@st.cache_resource(show_spinner=False)
def get_client(db_path: str) -> chromadb.PersistentClient:
    directory = Path(db_path)
    directory.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(directory))


def _date_to_epoch(selected_date: date, *, end_of_day: bool = False) -> int:
    base_time = time.max if end_of_day else time.min
    dt = datetime.combine(selected_date, base_time, tzinfo=timezone.utc)
    return int(dt.timestamp())


def _try_parse_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _list_session_ids(
    client: chromadb.PersistentClient,
    *,
    limit_per_collection: int = 1000,
) -> List[str]:
    session_ids: Set[str] = set()
    for name in ("traces", "plans"):
        try:
            collection = client.get_collection(name)
        except Exception:
            continue

        try:
            records = collection.get(limit=limit_per_collection, include=["metadatas"])
        except Exception:
            continue

        for meta in records.get("metadatas") or []:
            if isinstance(meta, dict):
                session_value = meta.get("session_id")
                if isinstance(session_value, str) and session_value.strip():
                    session_ids.add(session_value.strip())

    return sorted(session_ids)


# --- Data loading from ChromaDB -----------------------------------------------


def _load_trace_for_session(
    client: chromadb.PersistentClient,
    session_id: str,
    max_steps: int = 500,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Fetch and normalize trace steps for a given session."""
    try:
        collection = client.get_collection("traces")
    except Exception as e:
        st.error(f"Could not open 'traces' collection: {e}")
        return []

    where: Dict[str, Any] = {"session_id": session_id}

    # Optional timestamp filter
    if start_date or end_date:
        ts_bounds: Dict[str, Any] = {}
        if start_date:
            ts_bounds["$gte"] = _date_to_epoch(start_date)
        if end_date:
            ts_bounds["$lte"] = _date_to_epoch(end_date, end_of_day=True)
        if ts_bounds:
            where["timestamp_epoch"] = ts_bounds

    results = collection.get(where=where, limit=max_steps)
    docs = results.get("documents") or []
    metas = results.get("metadatas") or []
    ids = results.get("ids") or []

    steps: List[Dict[str, Any]] = []
    for idx, record_id in enumerate(ids):
        meta = metas[idx] if idx < len(metas) else {}
        parsed_doc = _try_parse_json(docs[idx] if idx < len(docs) else None)

        if isinstance(parsed_doc, dict):
            step = dict(parsed_doc)
        else:
            step = {"raw": parsed_doc}

        # Attach metadata fields if missing
        if "step" not in step and isinstance(meta, dict) and "step" in meta:
            step["step"] = meta["step"]
        if "session_id" not in step and "session_id" in meta:
            step["session_id"] = meta["session_id"]

        step["_meta"] = meta
        step["_id"] = record_id
        steps.append(step)

    # Sort by step number if available
    steps.sort(key=lambda s: s.get("step", 0))
    return steps


def _load_plan_for_session(
    client: chromadb.PersistentClient,
    session_id: str,
    desired_revision: int | None = None,
    max_records: int = 100,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Fetch the plan for a session (latest revision by default)."""
    try:
        collection = client.get_collection("plans")
    except Exception as e:
        st.error(f"Could not open 'plans' collection: {e}")
        return None, None

    results = collection.get(where={"session_id": session_id}, limit=max_records)
    docs = results.get("documents") or []
    metas = results.get("metadatas") or []
    ids = results.get("ids") or []

    if not ids:
        return None, None

    # Pick record either by revision or by max revision
    chosen_idx = 0
    best_revision = -1

    for idx, meta in enumerate(metas):
        rev = (meta or {}).get("revision")
        if desired_revision is not None and desired_revision > 0:
            # Exact revision match
            if rev == desired_revision:
                chosen_idx = idx
                best_revision = rev
                break
        else:
            # Take latest revision
            if isinstance(rev, int) and rev > best_revision:
                best_revision = rev
                chosen_idx = idx

    raw_doc = docs[chosen_idx] if chosen_idx < len(docs) else None
    parsed_doc = _try_parse_json(raw_doc)
    if not isinstance(parsed_doc, dict):
        parsed_doc = {"raw": parsed_doc}

    meta = metas[chosen_idx] if chosen_idx < len(metas) else {}
    meta = dict(meta or {})
    meta["_id"] = ids[chosen_idx]

    # Ensure some keys exist to match your React viewer expectations:contentReference[oaicite:1]{index=1}
    plan = dict(parsed_doc)
    plan.setdefault("planning_mode", meta.get("planning_mode", "unknown"))
    plan.setdefault("total_goals", meta.get("total_goals"))
    plan.setdefault("completed_goals", meta.get("completed_goals"))
    plan.setdefault("remaining_goals", meta.get("remaining_goals"))
    plan.setdefault("current_goal", meta.get("current_goal"))

    if not plan.get("tree_structure"):
        tree_candidate = plan.get("tree") or plan.get("root")
        if not tree_candidate and (
            "children" in plan or "value" in plan or "goal" in plan
        ):
            excluded = {
                "planning_mode",
                "total_goals",
                "completed_goals",
                "remaining_goals",
                "current_goal",
                "tree_structure",
            }
            tree_candidate = {
                key: value for key, value in plan.items() if key not in excluded
            }
        if tree_candidate:
            plan["tree_structure"] = tree_candidate

    return plan, meta


# --- UI rendering: Plan Tree --------------------------------------------------


def _node_label(node: Dict[str, Any]) -> str:
    for key in ("value", "goal", "description", "title"):
        if node.get(key):
            return str(node[key])
    return str(node.get("id", "Node"))


def _render_plan_tree_node(node: Any, *, level: int = 0) -> None:
    """Recursive plan tree renderer (roughly inspired by TreeNode.tsx).:contentReference[oaicite:2]{index=2}"""
    if not isinstance(node, dict):
        st.code(str(node))
        return

    label = _node_label(node)
    status = str(node.get("status", "pending")).upper()
    abstraction = node.get("abstraction_score")
    mcp_tool = node.get("mcp_tool")
    is_leaf = bool(node.get("is_leaf"))
    is_executable = bool(node.get("is_executable"))
    preconds = node.get("assumed_preconditions") or []
    effects = node.get("assumed_effects") or []
    tool_args = node.get("tool_args")
    children = node.get("children") or []

    chips: List[str] = []
    if status:
        chips.append(status)
    if abstraction is not None:
        try:
            chips.append(f"α={float(abstraction):.1f}")
        except Exception:
            chips.append(f"α={abstraction}")
    if mcp_tool:
        chips.append(f"🔧 {mcp_tool}")
    if is_leaf:
        chips.append("leaf")
        if is_executable:
            chips.append("executable")

    header = " · ".join(chips + [label]) if chips else label
    expanded = level < 2

    with st.expander(header, expanded=expanded):
        info = {
            k: v
            for k, v in node.items()
            if k
            not in {
                "children",
                "assumed_preconditions",
                "assumed_effects",
                "tool_args",
            }
        }
        if info:
            st.caption("Node details")
            st.json(info)

        if tool_args:
            st.caption("Tool arguments")
            st.code(json.dumps(tool_args, indent=2), language="json")

        if preconds:
            st.caption("Preconditions")
            for p in preconds:
                st.markdown(f"- {p}")

        if effects:
            st.caption("Effects")
            for e in effects:
                st.markdown(f"- {e}")

        for child in children:
            _render_plan_tree_node(child, level=level + 1)


def _assign_positions(
    node: Dict[str, Any],
    *,
    depth: int,
    next_x: List[float],
    nodes: List[Dict[str, Any]],
    edges: List[Tuple[str, str]],
) -> float:
    node_id = str(node.get("id") or f"node-{len(nodes)}")
    children = [c for c in (node.get("children") or []) if isinstance(c, dict)]
    child_xs: List[float] = []
    for child in children:
        child_id = str(child.get("id") or f"node-{len(nodes)+len(child_xs)}")
        edges.append((node_id, child_id))
        child_x = _assign_positions(
            child,
            depth=depth + 1,
            next_x=next_x,
            nodes=nodes,
            edges=edges,
        )
        child_xs.append(child_x)

    if child_xs:
        x = sum(child_xs) / len(child_xs)
    else:
        x = next_x[0]
        next_x[0] += 1.0

    nodes.append(
        {
            "id": node_id,
            "x": x,
            "y": -depth,
            "label": _node_label(node),
            "status": str(node.get("status", "pending")).upper(),
            "tool": node.get("mcp_tool") or "",
            "abstraction": node.get("abstraction_score"),
            "goal_text": node.get("goal") or node.get("value") or "",
        }
    )
    return x


def _build_plan_graph(tree_root: Dict[str, Any]):
    nodes: List[Dict[str, Any]] = []
    edges: List[Tuple[str, str]] = []
    _assign_positions(tree_root, depth=0, next_x=[0.0], nodes=nodes, edges=edges)
    if not nodes:
        return None

    id_to_node = {n["id"]: n for n in nodes}
    edge_x: List[float] = []
    edge_y: List[float] = []
    for src, dst in edges:
        if src in id_to_node and dst in id_to_node:
            edge_x.extend([id_to_node[src]["x"], id_to_node[dst]["x"], None])
            edge_y.extend([id_to_node[src]["y"], id_to_node[dst]["y"], None])

    node_x = [n["x"] for n in nodes]
    node_y = [n["y"] for n in nodes]
    node_colors = [STATUS_COLORS.get(n["status"], "#94a3b8") for n in nodes]
    hover_text = [
        f"<b>{n['label']}</b><br>Status: {n['status']}<br>Tool: {n['tool'] or '—'}"
        f"<br>Abstraction: {n['abstraction'] if n['abstraction'] is not None else '—'}"
        f"<br>Goal: {n['goal_text'] or '—'}"
        for n in nodes
    ]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(color="#cccccc", width=1.5),
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            text=[n["label"] for n in nodes],
            textposition="top center",
            marker=dict(
                size=18,
                color=node_colors,
                showscale=False,
                line=dict(color="#333", width=1),
            ),
            hoverinfo="text",
            hovertext=hover_text,
        )
    )

    fig.update_layout(
        margin=dict(t=10, l=10, r=10, b=10),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        showlegend=False,
        hovermode="closest",
    )
    return fig


def render_plan_tree_section(plan: Dict[str, Any], plan_meta: Dict[str, Any]) -> None:
    st.subheader("Plan Overview")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.caption("Planning mode")
        st.write(plan.get("planning_mode", "unknown"))
    with col2:
        st.caption("Total goals")
        st.write(plan.get("total_goals", "—"))
    with col3:
        st.caption("Completed")
        st.write(plan.get("completed_goals", "—"))
    with col4:
        st.caption("Remaining")
        st.write(plan.get("remaining_goals", "—"))

    if plan.get("current_goal"):
        cur = plan["current_goal"]
        st.markdown("### Current goal")
        goal_text = cur.get("value") or cur.get("goal") or ""
        colg1, colg2 = st.columns([3, 1])
        with colg1:
            st.markdown(f"> {goal_text}")
            if cur.get("mcp_tool"):
                st.caption(f"Tool: `{cur['mcp_tool']}`")
        with colg2:
            if cur.get("abstraction_score") is not None:
                try:
                    st.metric(
                        "Abstraction score",
                        f"{float(cur['abstraction_score']):.1f}",
                    )
                except Exception:
                    st.metric("Abstraction score", str(cur["abstraction_score"]))

    st.markdown("---")
    st.subheader("Hierarchical Plan Structure")

    tree_root = plan.get("tree_structure") or {}
    if not tree_root:
        st.info("No tree structure found on this plan (expected `tree_structure`).")
    else:
        _render_plan_tree_node(tree_root, level=0)

    with st.expander("Raw plan JSON"):
        st.json(plan)

    with st.expander("Plan metadata"):
        st.json(plan_meta)


# --- UI rendering: Timeline / Trace ------------------------------------------


def _render_trace_step_card(step: Dict[str, Any]) -> None:
    """Timeline step card inspired by TraceStepCard.tsx."""
    act = step.get("act")
    act_str = str(act) if act is not None else ""
    has_error = "error" in act_str.lower()
    plan = step.get("plan") or {}
    is_complete = bool(plan.get("goal_reached"))

    # Header line
    step_no = step.get("step", "—")
    goal = step.get("goal") or "(no goal text)"
    remaining_goals = step.get("remaining_goals")
    goal_abstraction = step.get("goal_abstraction")

    # Visual hint for state
    if has_error:
        st.error(f"Step {step_no}: {goal}")
    elif is_complete:
        st.success(f"Step {step_no}: {goal}")
    else:
        st.markdown(f"**Step {step_no}:** {goal}")

    # Badges-ish info
    cols = st.columns(3)
    with cols[0]:
        if remaining_goals is not None:
            st.caption("Goals remaining")
            st.write(remaining_goals)
    with cols[1]:
        if goal_abstraction is not None:
            try:
                st.caption("Goal abstraction")
                st.write(f"{float(goal_abstraction):.1f}")
            except Exception:
                st.caption("Goal abstraction")
                st.write(goal_abstraction)
    with cols[2]:
        meta = step.get("_meta", {})
        ts = meta.get("timestamp_epoch")
        if ts:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            st.caption("Timestamp (UTC)")
            st.write(dt.isoformat())

    # Sections: preconditions, effects, plan, action, observation
    preconds = step.get("assumed_preconditions") or []
    effects = step.get("assumed_effects") or []
    observation = step.get("observation")

    if preconds:
        with st.expander(f"Preconditions ({len(preconds)})", expanded=False):
            for p in preconds:
                st.markdown(f"- {p}")

    if effects:
        with st.expander(f"Expected effects ({len(effects)})", expanded=False):
            for e in effects:
                st.markdown(f"- {e}")

    if plan:
        call_fn = plan.get("call_function")
        label = "Plan" + (f" · `{call_fn}`" if call_fn else "")
        with st.expander(label, expanded=True):
            st.code(json.dumps(plan, indent=2), language="json")

    if act_str:
        label = "Action result"
        if has_error:
            label += " (error detected)"
        with st.expander(label, expanded=has_error):
            if has_error:
                st.error(act_str)
            else:
                st.code(act_str)

    if observation:
        with st.expander("Observation", expanded=True):
            st.write(observation)

    # Raw view
    step_label = f"Step {step_no}: {goal}" if step_no != "—" else goal
    with st.expander(step_label):
        st.json(step)


def render_timeline_section(trace_steps: List[Dict[str, Any]]) -> None:
    if not trace_steps:
        st.info("No trace steps found for this session.")
        return

    st.caption(f"{len(trace_steps)} step(s) loaded.")
    for step in trace_steps:
        st.markdown("---")
        _render_trace_step_card(step)


# --- Main app -----------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title="Trace & Plan Inspector", layout="wide")
    st.title("Trace & Plan Inspector")
    st.caption(f"ChromaDB directory: `{DB_DIR}`")

    client = get_client(str(DB_DIR))
    session_options = _list_session_ids(client)

    if not session_options:
        st.warning(
            "No session IDs found in the 'plans' or 'traces' collections."
            " Run the agent first to populate data."
        )
        return

    # Sidebar controls
    st.sidebar.header("Filters")

    session_id = st.sidebar.selectbox(
        "Session ID",
        options=session_options,
        help="Choose a session present in the Chroma collections.",
    )

    st.sidebar.markdown("**Timeline filters**")
    max_steps = st.sidebar.number_input(
        "Max steps to load",
        min_value=1,
        max_value=1000,
        value=200,
    )
    use_date_filter = st.sidebar.checkbox("Filter by timestamp (UTC)", value=False)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    if use_date_filter:
        start_date = st.sidebar.date_input("Start date", value=date.today())
        end_date = st.sidebar.date_input("End date", value=date.today())

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Plan filters**")
    plan_revision = st.sidebar.number_input(
        "Plan revision (0 = latest)",
        min_value=0,
        value=0,
        step=1,
    )

    with st.spinner("Loading trace & plan from ChromaDB..."):
        trace_steps = _load_trace_for_session(
            client,
            session_id=session_id.strip(),
            max_steps=int(max_steps),
            start_date=start_date,
            end_date=end_date,
        )
        plan, plan_meta = _load_plan_for_session(
            client,
            session_id=session_id.strip(),
            desired_revision=int(plan_revision) or None,
        )

    tab_timeline, tab_plan, tab_graph = st.tabs(["Timeline", "Plan Tree", "Plan Graph"])

    with tab_timeline:
        render_timeline_section(trace_steps)

    with tab_plan:
        if plan is None:
            st.info(
                "No plan found for this session in the 'plans' collection. "
                "Check that the session ID is correct and that plans are being stored."
            )
        else:
            render_plan_tree_section(plan, plan_meta or {})

    with tab_graph:
        if plan is None:
            st.info("No plan data available to render.")
        else:
            tree_root = (plan or {}).get("tree_structure") or {}
            if not tree_root:
                st.info("Plan does not include a tree structure to visualise.")
            else:
                fig = _build_plan_graph(tree_root)
                if fig is None:
                    st.info("Unable to build plan graph from the provided data.")
                else:
                    st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
