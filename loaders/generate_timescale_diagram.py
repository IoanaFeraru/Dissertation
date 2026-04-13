import re
from graphviz import Digraph

FILE_PATH = "loaders/timescaledb_optimised_loader.py"


# ─────────────────────────────────────────────
# Extraction helpers
# ─────────────────────────────────────────────

def extract_sql_block(path, var_name):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(rf'{var_name}\s*=\s*"""(.*?)"""', content, re.DOTALL)
    return match.group(1) if match else ""


def extract_tables(schema_sql):
    tables = {}
    fks = []

    matches = re.findall(
        r'CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\);',
        schema_sql,
        re.DOTALL | re.IGNORECASE
    )

    for table_name, body in matches:
        cols = re.findall(r'\s*(\w+)\s+([A-Z0-9_()]+)', body, re.IGNORECASE)

        pk_match = re.search(r'PRIMARY KEY\s*\((.*?)\)', body)
        pk_cols = pk_match.group(1).replace(" ", "").split(",") if pk_match else []

        # Extract FKs
        fk_matches = re.findall(
            r'(\w+)\s+[\w()]+\s+REFERENCES\s+(\w+)',
            body,
            re.IGNORECASE
        )
        for col, ref_table in fk_matches:
            fks.append((table_name, ref_table))

        tables[table_name] = {
            "columns": cols,
            "pk": pk_cols
        }

    return tables, fks


def extract_indexes(schema_sql):
    index_map = {}
    matches = re.findall(
        r'CREATE INDEX IF NOT EXISTS \w+ ON (\w+) \((.*?)\)',
        schema_sql,
        re.IGNORECASE
    )
    for table, cols in matches:
        cols = [c.strip().split()[0] for c in cols.split(",")]
        index_map.setdefault(table, []).extend(cols)
    return index_map


def extract_hypertables(sql):
    matches = re.findall(
        r"create_hypertable\(\s*'(\w+)'\s*,\s*'(\w+)'.*?INTERVAL\s*'([^']+)'",
        sql,
        re.IGNORECASE | re.DOTALL
    )
    return {t: {"time": c, "interval": i} for t, c, i in matches}


def extract_compression(sql):
    result = {}
    matches = re.findall(
        r"ALTER TABLE (\w+) SET.*?segmentby\s*=\s*'(\w+)'.*?orderby\s*=\s*'([^']+)'",
        sql,
        re.DOTALL
    )
    for table, segment, order in matches:
        result[table] = {"segment": segment, "order": order}
    return result


def extract_aggregate(sql):
    match = re.search(r'CREATE MATERIALIZED VIEW (\w+)', sql)
    return match.group(1) if match else None


# ─────────────────────────────────────────────
# Diagram
# ─────────────────────────────────────────────

def generate():
    base = extract_sql_block(FILE_PATH, "BASE_SCHEMA_SQL")
    hyper = extract_sql_block(FILE_PATH, "HYPERTABLE_SQL")
    comp = extract_sql_block(FILE_PATH, "COMPRESSION_SQL")
    agg = extract_sql_block(FILE_PATH, "CONTINUOUS_AGGREGATE_SQL")

    tables, fks = extract_tables(base)
    indexes = extract_indexes(base)
    hypertables = extract_hypertables(hyper)
    compression = extract_compression(comp)
    aggregate = extract_aggregate(agg)

    dot = Digraph("Timescale")
    # Compact spacing for horizontal layout
    dot.attr(rankdir="LR", ranksep="0.6", nodesep="0.3", splines="ortho")
    dot.attr("node", shape="none", margin="0.05,0.02")
    dot.attr("edge", fontsize="8")

    # ── Legend ─────────────────────────────
    dot.node("legend", '''<
    <TABLE BORDER="1" CELLBORDER="1" CELLPADDING="2">
        <TR><TD COLSPAN="2"><B>Legend</B></TD></TR>
        <TR><TD BGCOLOR="#E74C3C" WIDTH="20"></TD><TD>Primary Key</TD></TR>
        <TR><TD BGCOLOR="#3498DB"></TD><TD>Time Column</TD></TR>
        <TR><TD BGCOLOR="#2ECC71"></TD><TD>Indexed</TD></TR>
        <TR><TD BGCOLOR="#8E44AD"></TD><TD>Hypertable</TD></TR>
        <TR><TD BGCOLOR="#F4ECF7"></TD><TD>Hypertable Metadata</TD></TR>
        <TR><TD BGCOLOR="#EBF5FB"></TD><TD>Compression Settings</TD></TR>
    </TABLE>>''', margin="0.1")

    # ── COLUMN CLUSTERS WITH COMPACT LAYOUT ──────────────────────

    def add_column_compact(name, nodes, horizontal_limit=2):
        """Smart column layout - horizontal for small groups, vertical for large"""
        with dot.subgraph(name=f"cluster_{name}") as c:
            c.attr(label=name, style="rounded", color="#CCCCCC", margin="8", fontsize="10")

            if len(nodes) <= horizontal_limit:
                # Horizontal arrangement for small groups
                with c.subgraph() as row:
                    row.attr(rank="same")
                    for n in nodes:
                        row.node(n)
                # Invisible horizontal chain to maintain order
                for i in range(len(nodes) - 1):
                    dot.edge(nodes[i], nodes[i + 1], style="invis", weight="100")
            else:
                # Vertical arrangement for larger groups
                for n in nodes:
                    c.node(n)
                # Invisible vertical chain
                for i in range(len(nodes) - 1):
                    dot.edge(nodes[i], nodes[i + 1], style="invis", weight="100")

    # Define columns with smart layout (2 tables max horizontally)
    add_column_compact("Users", ["users", "seller_profiles"], horizontal_limit=2)
    add_column_compact("Subscriptions", ["subscriptions", "subscription_tiers", "subscription_tier_pricing"],
                       horizontal_limit=2)
    add_column_compact("Catalog", ["products"], horizontal_limit=2)
    add_column_compact("Transactions", ["invoices", "invoice_lines", "orders", "order_items"], horizontal_limit=2)
    add_column_compact("Events", ["sessions", "events"], horizontal_limit=2)

    # Force column ordering (keeps columns distinct and horizontal)
    col_order = ["users", "subscriptions", "products", "invoices", "sessions"]
    for i in range(len(col_order) - 1):
        dot.edge(col_order[i], col_order[i + 1], style="invis", weight="10")

    # ── Create nodes ───────────────────────
    for table, data in tables.items():
        cols = data["columns"]
        pk = data["pk"]
        idx = indexes.get(table, [])

        is_hyper = table in hypertables
        time_col = hypertables.get(table, {}).get("time")

        # Improved hypertable styling
        if is_hyper:
            header = "#8E44AD"  # strong purple
            border_color = "#8E44AD"
        else:
            header = "#2C3E50"
            border_color = "#000000"

        label = f'''<
        <TABLE BORDER="2" CELLBORDER="1" COLOR="{border_color}" CELLPADDING="3" CELLSPACING="0">
        <TR><TD COLSPAN="3" BGCOLOR="{header}">
        <FONT COLOR="white" POINT-SIZE="11"><B>{table}</B></FONT></TD></TR>
        '''

        for c, t in cols:
            role, bg, font = "", "#FFFFFF", "#000000"

            if c in pk:
                role, bg, font = "PK", "#E74C3C", "white"
            elif c == time_col:
                role, bg, font = "TIME", "#3498DB", "white"
            elif c in idx:
                role, bg, font = "IDX", "#2ECC71", "white"

            # Compact column display (hide data types for space)
            label += f"<TR><TD WIDTH='25'>{role}</TD><TD COLSPAN='2' ALIGN='LEFT'>{c}</TD></TR>"

        # Enhanced hypertable metadata with compression block
        if is_hyper:
            meta = hypertables[table]
            comp_meta = compression.get(table, {})

            label += f'''
            <TR><TD COLSPAN="3" BGCOLOR="#F4ECF7" ALIGN="CENTER">
            <FONT POINT-SIZE="8"><B>HYPERTABLE</B><BR/>
            chunk: {meta["interval"]}</FONT>
            </TD></TR>
            '''

            if table in compression:
                label += f'''
                <TR><TD COLSPAN="3" BGCOLOR="#EBF5FB" ALIGN="CENTER">
                <FONT POINT-SIZE="8"><B>COMPRESSION</B><BR/>
                segmentby: {comp_meta.get("segment", "-")}<BR/>
                orderby: {comp_meta.get("order", "-")}</FONT>
                </TD></TR>
                '''

        label += "</TABLE>>"
        dot.node(table, label=label)

    # ── Aggregate node (improved placement) ─────────────────────
    if aggregate:
        dot.node(
            aggregate,
            f"{aggregate}\n(continuous aggregate)",
            shape="box",
            style="filled",
            fillcolor="#FDEBD0",
            fontsize="9",
            margin="0.1"
        )
        # Position aggregate below the main flow with dashed edges
        dot.edge("invoices", aggregate, style="dashed", color="#7F8C8D", arrowsize="0.5")
        dot.edge("subscriptions", aggregate, style="dashed", color="#7F8C8D", arrowsize="0.5")

    # ── Relationships (cleaner edges) ──────────────────────
    # Remove duplicate FK relationships
    unique_fks = list(set(fks))
    for src, dst in unique_fks:
        dot.edge(src, dst, color="#7F8C8D", arrowsize="0.5", penwidth="1.0")

    dot.render("timescale_advanced", format="svg", cleanup=True)
    print("✔ timescale_advanced.png generated")


if __name__ == "__main__":
    generate()