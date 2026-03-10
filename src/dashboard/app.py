"""Brownfield Cartographer — Streamlit visualization dashboard.

Launch via:  cartographer dashboard --cartography-dir .cartography/
Or directly: streamlit run src/dashboard/app.py -- --cartography-dir .cartography/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import streamlit as st

# ── Parse --cartography-dir from Streamlit's extra CLI args ──────────────────
def _get_cartography_dir() -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cartography-dir", default=".cartography")
    # Streamlit passes extra args after '--'
    try:
        idx = sys.argv.index("--")
        extra_args = sys.argv[idx + 1:]
    except ValueError:
        extra_args = []
    args, _ = parser.parse_known_args(extra_args)
    return Path(args.cartography_dir)


_RAW_CARTOGRAPHY_DIR = _get_cartography_dir()


def _discover_repos(root: Path) -> list[str]:
    """Return names of repos that have been analyzed under root."""
    if not root.exists():
        return []
    # A valid repo output dir contains at least a lineage_graph.json
    return sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and (d / "lineage_graph.json").exists()
    )


def _resolve_cartography_dir(raw: Path) -> Path:
    """If raw points at a root .cartography/ folder (not a named sub-dir), return raw.
    The sidebar selector will then narrow it down to a specific repo at runtime."""
    return raw


# ── Data loading (cached) ─────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def load_graph_data(cartography_dir: str):
    """Load and return both graph JSON files as raw dicts."""
    d = Path(cartography_dir)
    module_data, lineage_data = {}, {}

    mp = d / "module_graph.json"
    if mp.exists():
        module_data = json.loads(mp.read_text(encoding="utf-8"))

    lp = d / "lineage_graph.json"
    if lp.exists():
        lineage_data = json.loads(lp.read_text(encoding="utf-8"))

    return module_data, lineage_data


@st.cache_resource(show_spinner=False)
def load_knowledge_graph(cartography_dir: str):
    from src.graph.knowledge_graph import KnowledgeGraph
    return KnowledgeGraph.load(Path(cartography_dir))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_pyvis_module_graph(kg, filter_domain: Optional[str] = None, min_pagerank: float = 0.0):
    from pyvis.network import Network
    net = Network(height="600px", width="100%", directed=True, bgcolor="#0e1117", font_color="white")
    net.set_options("""
    {
      "physics": {"barnesHut": {"gravitationalConstant": -3000, "springLength": 150}},
      "edges": {"arrows": {"to": {"enabled": true, "scaleFactor": 0.5}}, "color": {"color": "#444"}},
      "interaction": {"hover": true, "tooltipDelay": 100}
    }
    """)

    domain_colors = [
        "#e41a1c", "#377eb8", "#4daf4a", "#984ea3",
        "#ff7f00", "#a65628", "#f781bf", "#999999",
    ]
    domain_color_map: dict[str, str] = {}

    nodes = kg.all_modules()
    if filter_domain:
        nodes = [n for n in nodes if n.domain_cluster == filter_domain]
    if min_pagerank > 0:
        nodes = [n for n in nodes if n.pagerank_score >= min_pagerank]

    for module in nodes:
        domain = module.domain_cluster or "uncategorized"
        if domain not in domain_color_map:
            domain_color_map[domain] = domain_colors[len(domain_color_map) % len(domain_colors)]
        color = domain_color_map[domain]

        size = max(10, min(60, int(module.pagerank_score * 5000)))
        tooltip = (
            f"<b>{module.path}</b><br>"
            f"Domain: {domain}<br>"
            f"Complexity: {module.complexity_score}<br>"
            f"Velocity (30d): {module.change_velocity_30d}<br>"
            f"PageRank: {module.pagerank_score:.4f}<br>"
            f"{'⚠ Dead code candidate' if module.is_dead_code_candidate else ''}"
            f"{'🔄 In cycle' if module.in_cycle else ''}<br>"
            f"<i>{(module.purpose_statement or '')[:200]}</i>"
        )
        net.add_node(module.path, label=module.path.split("/")[-1], color=color,
                     size=size, title=tooltip)

    node_ids = {m.path for m in nodes}
    for src, tgt, data in kg.module_graph.edges(data=True):
        if src in node_ids and tgt in node_ids:
            net.add_edge(src, tgt, title=data.get("edge_type", "IMPORTS"))

    return net


def _build_pyvis_lineage_graph(kg):
    from pyvis.network import Network
    net = Network(height="600px", width="100%", directed=True, bgcolor="#0e1117", font_color="white")
    net.set_options("""
    {
      "physics": {"hierarchicalRepulsion": {"centralGravity": 0.0}},
      "layout": {"hierarchical": {"enabled": false}},
      "edges": {"arrows": {"to": {"enabled": true}}, "color": {"color": "#555"}},
      "interaction": {"hover": true}
    }
    """)

    type_colors = {"source": "#2ecc71", "transformation": "#3498db", "sink": "#e74c3c", "dataset": "#95a5a6"}

    sources = {n.name for n in _get_hydro().find_sources(kg)}
    sinks = {n.name for n in _get_hydro().find_sinks(kg)}

    for node_id, attrs in kg.lineage_graph.nodes(data=True):
        if node_id in sources:
            color = type_colors["source"]
            node_type = "source"
        elif node_id in sinks:
            color = type_colors["sink"]
            node_type = "sink"
        elif attrs.get("node_type") == "transformation":
            color = type_colors["transformation"]
            node_type = "transformation"
        else:
            color = type_colors["dataset"]
            node_type = "dataset"

        up = kg.lineage_graph.in_degree(node_id)
        down = kg.lineage_graph.out_degree(node_id)
        tooltip = (
            f"<b>{node_id}</b><br>"
            f"Type: {node_type}<br>"
            f"Upstream: {up} | Downstream: {down}<br>"
            f"Source: {attrs.get('source_file', '?')}"
        )
        net.add_node(node_id, label=node_id[:30], color=color, title=tooltip)

    for src, tgt, data in kg.lineage_graph.edges(data=True):
        edge_type = data.get("edge_type", "")
        source_file = data.get("source_file", "")
        label = edge_type
        title = f"{edge_type}\n{source_file}"
        net.add_edge(src, tgt, label=label, title=title)

    return net


@st.cache_resource
def _get_hydro():
    from src.agents.hydrologist import Hydrologist
    return Hydrologist()


# ── Page renderers ─────────────────────────────────────────────────────────────

def page_system_map(kg) -> None:
    st.header("System Map")
    st.caption("Module dependency graph — nodes sized by PageRank, colored by domain cluster")

    col1, col2 = st.columns([2, 1])
    with col2:
        domains = sorted({m.domain_cluster or "uncategorized" for m in kg.all_modules()})
        selected_domain = st.selectbox("Filter by domain", ["All"] + domains)
        min_pr = st.slider("Min PageRank", 0.0, 0.01, 0.0, step=0.0001, format="%.4f")

    filter_domain = None if selected_domain == "All" else selected_domain

    net = _build_pyvis_module_graph(kg, filter_domain=filter_domain, min_pagerank=min_pr)
    html = net.generate_html()
    with col1:
        st.components.v1.html(html, height=620, scrolling=False)

    with col2:
        st.subheader("Top Modules (PageRank)")
        top = sorted(kg.all_modules(), key=lambda m: m.pagerank_score, reverse=True)[:10]
        for m in top:
            st.markdown(f"**`{m.path.split('/')[-1]}`** — {m.pagerank_score:.4f}")
            if m.purpose_statement:
                st.caption(m.purpose_statement[:100])


def page_lineage_graph(kg) -> None:
    st.header("Data Lineage Graph")
    st.caption("Data flow DAG — green=source, blue=transformation, red=sink")

    hydro = _get_hydro()
    col_graph, col_info = st.columns([3, 1])

    with col_graph:
        net = _build_pyvis_lineage_graph(kg)
        html = net.generate_html()
        st.components.v1.html(html, height=620, scrolling=False)

    with col_info:
        sources = hydro.find_sources(kg)
        sinks = hydro.find_sinks(kg)
        st.subheader(f"Sources ({len(sources)})")
        for s in sources[:15]:
            st.markdown(f"🟢 `{s.name}`")
        st.subheader(f"Sinks ({len(sinks)})")
        for s in sinks[:15]:
            st.markdown(f"🔴 `{s.name}`")


def page_blast_radius(kg) -> None:
    st.header("Blast Radius")
    st.caption("Select a module or dataset to see everything that would break if it changes")

    hydro = _get_hydro()
    all_nodes = sorted(
        list(kg.module_graph.nodes()) + list(kg.lineage_graph.nodes())
    )

    if not all_nodes:
        st.warning("No nodes found. Run analysis first.")
        return

    selected = st.selectbox("Select node", all_nodes)

    if st.button("Compute Blast Radius", type="primary"):
        results = hydro.blast_radius(kg, selected)

        if not results:
            st.info("No downstream dependencies found.")
        else:
            st.success(f"{len(results)} downstream nodes affected")

            # Render subgraph with PyVis
            from pyvis.network import Network
            net = Network(height="400px", width="100%", directed=True,
                         bgcolor="#0e1117", font_color="white")
            net.add_node(selected, color="#f39c12", size=30, label=selected[:30])
            for item in results:
                depth = item["depth"]
                red_intensity = min(255, 100 + depth * 50)
                color = f"#{red_intensity:02x}3030"
                net.add_node(item["node"], color=color, size=20,
                             label=item["node"][:25],
                             title=f"Depth: {depth}\n{item.get('source_file', '')}")
                net.add_edge(selected if depth == 1 else results[depth - 2]["node"],
                             item["node"])
            st.components.v1.html(net.generate_html(), height=420)

            st.subheader("Affected Files")
            for item in results:
                src = item.get("source_file", "")
                lr = item.get("line_range", (0, 0))
                st.markdown(f"- `{item['node']}` (depth {item['depth']}) — `{src}:{lr[0]}`")


def page_domain_map(kg) -> None:
    st.header("Domain Architecture Map")
    st.caption("Modules grouped by inferred business domain — size = lines of code")

    import plotly.express as px
    import pandas as pd

    modules = kg.all_modules()
    if not modules:
        st.warning("No modules analyzed.")
        return

    data = [
        {
            "domain": m.domain_cluster or "uncategorized",
            "module": m.path.split("/")[-1],
            "path": m.path,
            "lines": max(1, m.lines_of_code),
            "velocity": m.change_velocity_30d,
            "purpose": (m.purpose_statement or "")[:150],
        }
        for m in modules
    ]
    df = pd.DataFrame(data)

    fig = px.treemap(
        df,
        path=["domain", "module"],
        values="lines",
        color="velocity",
        color_continuous_scale="RdYlGn_r",
        hover_data=["path", "purpose"],
        title="Domain Architecture — size=LOC, color=change velocity",
    )
    fig.update_layout(margin=dict(t=50, l=25, r=25, b=25), paper_bgcolor="#0e1117",
                      font_color="white")
    st.plotly_chart(fig, use_container_width=True)

    selected_domain = st.selectbox("Inspect domain", sorted(df["domain"].unique()))
    domain_modules = df[df["domain"] == selected_domain].sort_values("lines", ascending=False)
    st.dataframe(domain_modules[["module", "lines", "velocity", "purpose"]], use_container_width=True)


def page_git_heatmap(kg) -> None:
    st.header("Git Velocity Heatmap")
    st.caption("Files by change frequency — surfaces high-churn pain points")

    import plotly.graph_objects as go
    import pandas as pd

    modules = [m for m in kg.all_modules() if m.change_velocity_30d > 0]
    if not modules:
        st.info("No git velocity data available. Make sure the repo has a git history.")
        return

    modules_sorted = sorted(modules, key=lambda m: m.change_velocity_30d, reverse=True)[:30]
    names = [m.path.split("/")[-1] for m in modules_sorted]
    values = [m.change_velocity_30d for m in modules_sorted]
    paths = [m.path for m in modules_sorted]

    fig = go.Figure(go.Bar(
        x=values,
        y=names,
        orientation="h",
        marker=dict(
            color=values,
            colorscale="RdYlGn_r",
            showscale=True,
        ),
        text=[f"{v} commits" for v in values],
        hovertext=paths,
        hoverinfo="text",
    ))
    fig.update_layout(
        title="Top 30 Files by Commit Frequency (last 30 days)",
        xaxis_title="Commit count",
        yaxis=dict(autorange="reversed"),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font_color="white",
        height=700,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Highlight the high-velocity 20%
    top_20pct = max(1, len(modules_sorted) // 5)
    st.info(f"Top {top_20pct} files (top 20%) are the high-churn core — likely pain points.")


def page_navigator_chat(kg, cartography_dir: Path) -> None:
    st.header("Navigator Chat")
    st.caption("Ask questions about the codebase in natural language")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about the codebase…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Querying knowledge graph…"):
                from src.agents.navigator import Navigator
                nav = Navigator(kg, cartography_dir=cartography_dir)
                response = nav.query(prompt)

            # Render tool usage as an expander
            if response.startswith("["):
                method_end = response.find("]")
                method = response[1:method_end]
                body = response[method_end + 1:].strip()
                with st.expander(f"Tool used: {method}"):
                    st.code(method)
                st.markdown(body)
            else:
                st.markdown(response)

            st.session_state.messages.append({"role": "assistant", "content": response})


# ── Main app ───────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Brownfield Cartographer",
        page_icon="🗺️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.sidebar.title("🗺️ Brownfield Cartographer")

    # ── Repo selector ─────────────────────────────────────────────────────────
    root = _RAW_CARTOGRAPHY_DIR
    available_repos = _discover_repos(root)

    # If --cartography-dir already points at a specific named sub-dir, use it directly.
    # Otherwise show a selector so the user can pick from analyzed repos.
    if available_repos and (root / available_repos[0]).resolve() != root.resolve():
        # Root contains named subdirectories → show a picker
        if len(available_repos) == 0:
            st.error(
                f"No analyzed repos found under `{root}`. "
                "Run `cartographer analyze <url>` first."
            )
            st.stop()

        selected_repo = st.sidebar.selectbox(
            "Repository",
            available_repos,
            help="Switch between analyzed repos",
        )
        CARTOGRAPHY_DIR = root / selected_repo
    else:
        # Pointed directly at a repo output dir (e.g. .cartography/jaffle_shop)
        CARTOGRAPHY_DIR = root
        repo_name = root.name
        st.sidebar.markdown(f"**Repo:** `{repo_name}`")

    st.sidebar.caption(f"`{CARTOGRAPHY_DIR}`")

    if not CARTOGRAPHY_DIR.exists():
        st.error(
            f"Cartography directory `{CARTOGRAPHY_DIR}` not found. "
            "Run `cartographer analyze <repo>` first."
        )
        st.stop()

    with st.spinner("Loading knowledge graph…"):
        try:
            kg = load_knowledge_graph(str(CARTOGRAPHY_DIR))
        except Exception as exc:
            st.error(f"Failed to load graph: {exc}")
            st.stop()

    stats = kg.stats()
    st.sidebar.metric("Modules", stats["modules"])
    st.sidebar.metric("Datasets", stats["datasets"])
    st.sidebar.metric("Import edges", stats["module_edges"])
    st.sidebar.metric("Lineage edges", stats["lineage_edges"])

    page = st.sidebar.radio(
        "View",
        [
            "System Map",
            "Data Lineage Graph",
            "Blast Radius",
            "Domain Architecture Map",
            "Git Velocity Heatmap",
            "Navigator Chat",
        ],
    )

    if page == "System Map":
        page_system_map(kg)
    elif page == "Data Lineage Graph":
        page_lineage_graph(kg)
    elif page == "Blast Radius":
        page_blast_radius(kg)
    elif page == "Domain Architecture Map":
        page_domain_map(kg)
    elif page == "Git Velocity Heatmap":
        page_git_heatmap(kg)
    elif page == "Navigator Chat":
        page_navigator_chat(kg, CARTOGRAPHY_DIR)


main()
