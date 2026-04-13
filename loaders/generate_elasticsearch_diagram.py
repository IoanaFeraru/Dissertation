from graphviz import Digraph
from loaders.elasticsearch_optimised_loader import MAPPINGS, PRODUCTS_SETTINGS, PREFIX

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def detect_type(field):
    t = field.get("type", "")

    if t == "keyword":
        return "KW", "#F4D03F"
    if t == "text":
        return "TXT", "#AED6F1"
    if t == "date":
        return "DATE", "#A9DFBF"
    if t == "nested":
        return "NESTED", "#E74C3C"
    if t == "object":
        return "OBJ", "#D7BDE2"
    if t in ("float", "integer"):
        return "NUM", "#F5CBA7"

    return "", "#FFFFFF"


def has_keyword_subfield(field):
    return "fields" in field and "keyword" in field["fields"]


# ─────────────────────────────────────────────
# Diagram
# ─────────────────────────────────────────────

def generate():
    dot = Digraph("Elasticsearch")
    dot.attr(rankdir="LR", ranksep="0.6", nodesep="0.3", splines="ortho")
    dot.attr("node", shape="none", margin="0.05,0.02")

    # ── Legend ─────────────────────────────
    dot.node("legend", '''<
    <TABLE BORDER="1" CELLBORDER="1" CELLPADDING="2">
        <TR><TD COLSPAN="2"><B>Legend</B></TD></TR>
        <TR><TD BGCOLOR="#F4D03F"></TD><TD>Keyword</TD></TR>
        <TR><TD BGCOLOR="#AED6F1"></TD><TD>Text</TD></TR>
        <TR><TD BGCOLOR="#A9DFBF"></TD><TD>Date</TD></TR>
        <TR><TD BGCOLOR="#E74C3C"></TD><TD>Nested</TD></TR>
        <TR><TD BGCOLOR="#D7BDE2"></TD><TD>Object</TD></TR>
        <TR><TD BGCOLOR="#F5CBA7"></TD><TD>Numeric</TD></TR>
        <TR><TD>+kw</TD><TD>Has keyword subfield</TD></TR>
        <TR><TD>★</TD><TD>Custom analyzer</TD></TR>
    </TABLE>>''')

    # ─────────────────────────────────────
    # Column layout (same as Timescale)
    # ─────────────────────────────────────

    def column(name, nodes):
        with dot.subgraph(name=f"cluster_{name}") as c:
            c.attr(label=name, style="rounded", color="#CCCCCC")
            for n in nodes:
                c.node(n)

    column("Users", [
        f"{PREFIX}users",
        f"{PREFIX}seller_profiles"
    ])

    column("Subscriptions", [
        f"{PREFIX}subscriptions",
        f"{PREFIX}subscription_tiers",
        f"{PREFIX}subscription_tier_pricing"
    ])

    column("Catalog", [
        f"{PREFIX}products"
    ])

    column("Transactions", [
        f"{PREFIX}invoices",
        f"{PREFIX}invoice_lines",
        f"{PREFIX}orders",
        f"{PREFIX}order_items"
    ])

    column("Events", [
        f"{PREFIX}sessions",
        f"{PREFIX}events"
    ])

    # Force column ordering
    col_order = [
        f"{PREFIX}users",
        f"{PREFIX}subscriptions",
        f"{PREFIX}products",
        f"{PREFIX}invoices",
        f"{PREFIX}sessions"
    ]
    for i in range(len(col_order) - 1):
        dot.edge(col_order[i], col_order[i+1], style="invis", weight="10")

    # ─────────────────────────────────────
    # Nodes
    # ─────────────────────────────────────

    for index, mapping in MAPPINGS.items():
        props = mapping["properties"]

        is_products = index.endswith("products")

        header_color = "#1F618D"
        title = index

        if is_products:
            title += " ★"  # analyzer marker

        label = f'''<
        <TABLE BORDER="2" CELLBORDER="1" CELLPADDING="3">
        <TR><TD COLSPAN="2" BGCOLOR="{header_color}">
        <FONT COLOR="white"><B>{title}</B></FONT></TD></TR>
        '''

        for field_name, field_def in props.items():
            role, color = detect_type(field_def)

            extra = ""
            if has_keyword_subfield(field_def):
                extra += " +kw"

            if field_def.get("norms") is False:
                extra += " (no-norm)"

            label += f"""
            <TR>
                <TD BGCOLOR="{color}">{role}</TD>
                <TD ALIGN="LEFT">{field_name}{extra}</TD>
            </TR>
            """

        label += "</TABLE>>"

        dot.node(index, label=label)

    # ─────────────────────────────────────
    # Relationships (logical, not joins)
    # ─────────────────────────────────────

    def rel(a, b):
        dot.edge(a, b, style="dashed", color="#7F8C8D", arrowsize="0.5")

    rel(f"{PREFIX}subscriptions", f"{PREFIX}users")
    rel(f"{PREFIX}seller_profiles", f"{PREFIX}users")
    rel(f"{PREFIX}products", f"{PREFIX}seller_profiles")

    rel(f"{PREFIX}invoices", f"{PREFIX}users")
    rel(f"{PREFIX}orders", f"{PREFIX}invoices")
    rel(f"{PREFIX}order_items", f"{PREFIX}orders")
    rel(f"{PREFIX}invoice_lines", f"{PREFIX}invoices")

    rel(f"{PREFIX}sessions", f"{PREFIX}users")
    rel(f"{PREFIX}events", f"{PREFIX}sessions")

    # ─────────────────────────────────────
    # Denormalisation (IMPORTANT)
    # ─────────────────────────────────────

    # invoices -> nested lines (using xlabel to avoid warning)
    dot.edge(
        f"{PREFIX}invoices",
        f"{PREFIX}invoice_lines",
        xlabel="embedded",  # Changed from label to xlabel
        color="#E74C3C",
        penwidth="2"
    )

    # sessions -> nested cart (using xlabel to avoid warning)
    dot.edge(
        f"{PREFIX}sessions",
        f"{PREFIX}products",
        xlabel="cart[]",    # Changed from label to xlabel
        color="#E74C3C",
        penwidth="2"
    )

    # events metadata (using xlabel to avoid warning)
    dot.edge(
        f"{PREFIX}events",
        f"{PREFIX}products",
        xlabel="metadata",  # Changed from label to xlabel
        color="#8E44AD",
        style="dotted"
    )

    dot.render("elasticsearch_advanced", format="svg", cleanup=True)
    print("✔ elasticsearch_advanced.svg generated")


if __name__ == "__main__":
    generate()