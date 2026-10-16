import json, sys

def fmt_nodes(nodes, links, title):
    print("---", title, "nodes:", len(nodes))
    for n in nodes:
        if n.get("type") in ("Note", "MarkdownNote"):
            continue
        ins = []
        for i in n.get("inputs", []):
            lk = i.get("link")
            if lk is not None and lk in links:
                ins.append(f'{i["name"]}<-{links[lk][0]}:{links[lk][1]}')
        s = json.dumps(n.get("widgets_values"), ensure_ascii=False)
        if len(s) > 150:
            s = s[:150] + "..."
        print(f'{n["id"]:>4} {n["type"]} m={n.get("mode")} W={s} IN={ins}')

p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
print("==", p)
L = {}
for l in d.get("links", []):
    if isinstance(l, list):
        L[l[0]] = (l[1], l[2])
    else:
        L[l["id"]] = (l["origin_id"], l["origin_slot"])
fmt_nodes(d.get("nodes", []), L, "top")
for sg in d.get("definitions", {}).get("subgraphs", []):
    SL = {}
    for l in sg.get("links", []):
        if isinstance(l, list):
            SL[l[0]] = (l[1], l[2])
        else:
            SL[l["id"]] = (l["origin_id"], l["origin_slot"])
    fmt_nodes(sg.get("nodes", []), SL, "subgraph " + str(sg.get("name")) + " " + str(sg.get("id"))[:8])
