import json, struct, sys, collections
for p in sys.argv[1:]:
    try:
        with open(p, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            h = json.loads(f.read(n))
        meta = h.pop("__metadata__", {})
        pre = collections.Counter(".".join(k.split(".")[:2]) for k in h)
        dt = collections.Counter(v.get("dtype") for v in h.values())
        print("==", p)
        print("  tensors:", len(h), "dtypes:", dict(dt))
        print("  prefixes:", dict(pre.most_common(8)))
        print("  meta:", {k: str(v)[:80] for k, v in list(meta.items())[:6]})
    except Exception as e:
        print("ERR", p, e)
