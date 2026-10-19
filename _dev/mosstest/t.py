import sys, json
sys.path.insert(0, "src")
from pathlib import Path
import mm_common as C
import mm_images as I

cat = C.Catalog([Path("_dev/mosstest/models")], url=None, prefer_live=False)
p = I.Params(mode="moss_t2i", prompt="test", loras=[("MOSS-Image-SFT-8-steps-dmd", 1.0)])
info = {}
g = I.build_moss_t2i(p, cat, info)
nodes = g.to_dict() if hasattr(g, "to_dict") else None
print(json.dumps(info.get("notes", []), ensure_ascii=False))
print(json.dumps(info.get("models", {}), ensure_ascii=False))
# find VAEDecode input link
d = nodes if isinstance(nodes, dict) else g.nodes if hasattr(g, "nodes") else None
print(type(g), [a for a in dir(g) if not a.startswith('_')])
