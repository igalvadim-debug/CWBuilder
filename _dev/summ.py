import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
nodes = d.get("nodes", [])
links = {l[0]: l for l in d.get("links", [])}
print("==", p, "nodes:", len(nodes))
for n in nodes:
    if n.get("type") in ("Note", "MarkdownNote"):
        continue
    ins = []
    for i in n.get("inputs", []):
        lk = i.get("link")
        if lk is not None and lk in links:
            l = links[lk]
            ins.append(f'{i["name"]}<-{l[1]}:{l[2]}')
    wv = n.get("widgets_values")
    s = json.dumps(wv, ensure_ascii=False)
    if len(s) > 160:
        s = s[:160] + "..."
    print(f'{n["id"]:>4} {n["type"]} m={n.get("mode")} W={s} IN={ins}')
