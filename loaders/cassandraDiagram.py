import re
import os
from graphviz import Digraph

# Path to your loader script
FILE_PATH = "loaders/cassandra_optimised_loader.py"


def extract_ddl_entries(path):
    if not os.path.exists(path): return {}
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    return {name.lower(): ddl.strip() for name, ddl in
            re.findall(r'CREATE_(\w+)\s*=\s*"""(.*?)"""', content, re.DOTALL)}


def parse_pk_robust(ddl):
    """Parses PK and clustering order logic."""
    # Extract PK
    pk_start = ddl.find("PRIMARY KEY")
    if pk_start == -1: return [], [], None
    bracket_start = ddl.find("(", pk_start)
    bracket_level, bracket_end = 0, -1
    for i in range(bracket_start, len(ddl)):
        if ddl[i] == '(':
            bracket_level += 1
        elif ddl[i] == ')':
            bracket_level -= 1
            if bracket_level == 0:
                bracket_end = i
                break

    pk_content = ddl[bracket_start + 1: bracket_end].strip()
    if pk_content.startswith('('):  # Composite ((pk1, pk2), ck1)
        inner_end = pk_content.find(')')
        p_keys = [k.strip() for k in pk_content[1:inner_end].split(',')]
        c_keys_raw = pk_content[inner_end + 1:].strip(', ')
        c_keys = [k.strip() for k in c_keys_raw.split(',')] if c_keys_raw else []
    else:  # Simple (pk, ck1, ck2) or (id)
        parts = [k.strip() for k in pk_content.split(',')]
        p_keys = [parts[0]] if parts else []
        c_keys = parts[1:] if len(parts) > 1 else []

    # Extract Clustering Order
    order_match = re.search(r'WITH CLUSTERING ORDER BY\s*\((.*?)\)', ddl, re.IGNORECASE | re.DOTALL)
    order = order_match.group(1).strip().replace('\n', ' ') if order_match else None

    return p_keys, c_keys, order


def generate_academic_diagram():
    all_ddls = extract_ddl_entries(FILE_PATH)
    dot = Digraph('Cassandra_Academic_Model', comment='Cassandra Physical Schema')
    dot.attr(rankdir='LR', nodesep='0.5', ranksep='1.0', fontname='Helvetica')
    dot.attr('node', shape='none')

    # 1. Create Legend
    legend = '''<
        <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4">
            <TR><TD COLSPAN="2" BGCOLOR="#DCDCDC"><B>Schema Legend</B></TD></TR>
            <TR><TD BGCOLOR="#E74C3C"></TD><TD ALIGN="LEFT">Partition Key (Distribution)</TD></TR>
            <TR><TD BGCOLOR="#F39C12"></TD><TD ALIGN="LEFT">Clustering Column (Sorting)</TD></TR>
            <TR><TD BGCOLOR="#3498DB"></TD><TD ALIGN="LEFT">Secondary/SASI Index</TD></TR>
        </TABLE>>'''
    dot.node('legend', label=legend)

    # 2. Process Tables
    table_vars = {k: v for k, v in all_ddls.items() if "TABLE" in v.upper()}
    index_vars = {k: v for k, v in all_ddls.items() if "INDEX" in v.upper()}

    for var_name, ddl in table_vars.items():
        table_name = var_name.replace("create_", "")
        p_keys, c_keys, order = parse_pk_robust(ddl)
        cols = re.findall(r'^\s*([a-z0-9_]+)\s+([a-z0-9_<>]+)', ddl, re.MULTILINE | re.IGNORECASE)

        # Check for SASI indexes on this table
        indexed_cols = []
        for idx_ddl in index_vars.values():
            if table_name in idx_ddl.lower():
                match = re.search(r'\((.*?)\)', idx_ddl)
                if match: indexed_cols.append(match.group(1).strip())

        label = f'''<
            <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="6">
                <TR><TD COLSPAN="3" BGCOLOR="#2C3E50"><FONT COLOR="white"><B>{table_name.upper()}</B></FONT></TD></TR>
                <TR><TD BGCOLOR="#BDC3C7"><B>Role</B></TD><TD BGCOLOR="#BDC3C7"><B>Column</B></TD><TD BGCOLOR="#BDC3C7"><B>Type</B></TD></TR>
        '''

        for col_name, col_type in cols:
            if col_name.upper() in ["PRIMARY", "CREATE", "WITH"]: continue

            role, bg, font = "&nbsp;", "#FFFFFF", "#000000"
            is_composite = len(p_keys) > 1

            if col_name in p_keys:
                role = "Partition Key" + (" (Comp)" if is_composite else "")
                bg, font = "#E74C3C", "#FFFFFF"
                col_display = f"<B>{col_name}</B>"
            elif col_name in c_keys:
                role = "Clustering Col"
                bg, font = "#F39C12", "#FFFFFF"
                col_display = col_name
            elif col_name in indexed_cols:
                role = "Index (SASI)"
                bg, font = "#3498DB", "#FFFFFF"
                col_display = col_name
            else:
                col_display = col_name

            label += f'''<TR><TD BGCOLOR="{bg}"><FONT COLOR="{font}">{role}</FONT></TD>
                             <TD BGCOLOR="{bg}" ALIGN="LEFT"><FONT COLOR="{font}">{col_display}</FONT></TD>
                             <TD BGCOLOR="{bg}" ALIGN="LEFT"><FONT COLOR="{font}">{col_type}</FONT></TD></TR>'''

        # Add Metadata Footer
        if order:
            label += f'<TR><TD COLSPAN="3" ALIGN="LEFT" BGCOLOR="#FDFEFE"><FONT POINT-SIZE="10"><B>Clustering Order:</B> {order}</FONT></TD></TR>'

        if table_name == "products_search":
            label += f'<TR><TD COLSPAN="3" ALIGN="LEFT" BGCOLOR="#EBF5FB"><FONT POINT-SIZE="10"><I>Denormalised table for substring search via SASI index</I></FONT></TD></TR>'

        label += '</TABLE>>'
        dot.node(table_name, label=label)

    dot.render('cassandra_academic_schema', format='png', cleanup=True)
    print("✔ Generated: cassandra_academic_schema.png")


if __name__ == "__main__":
    generate_academic_diagram()