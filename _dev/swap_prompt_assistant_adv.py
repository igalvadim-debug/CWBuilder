#!/usr/bin/env python3
"""
Swap the LongForge native "Prompt Assistant" (LongForgePromptAssistant + its
Gemma-4 CLIPLoader, ~12.5 GB staged VRAM) out of an H3 LongForge workflow and
wire in the user's own "Promt enchncher ADV" subgraph instead
(llama.cpp GGUF via LlamaServerVisionCaption -> runs on CPU/RAM, server is
unloaded afterwards).

No JavaScript needed: everything is plain JSON graph surgery.

Usage:
    python _dev/swap_prompt_assistant_adv.py <in_workflow.json> [out_workflow.json]
"""

import copy
import json
import re
import sys
from pathlib import Path

ADV_TEMPLATE = Path(__file__).resolve().parent.parent / "assets/JSON_workfow/Promt EnchancerADV.json"

# The system prompt handed to the ADV enhancer (subgraph input `text_a`).
SYSTEM_PROMPT = (
    "You are an expert AI prompt engineer for ComfyUI video generation "
    "(MiniMax H3 / LTX-Video with Prompt-Relay style timeline conditioning).\n"
    "Rewrite the user's idea into ONE production-ready prompt.\n"
    "HARD FORMAT RULES:\n"
    "1. Start with a 'Global System Prompt:' block: art style, lighting, lens and "
    "camera character, continuity rules that must hold across scenes.\n"
    "2. Then a 'Timeline Sequence:' block with explicit ranges 'At frame X-Y:' that "
    "cover the whole clip from frame 0 up to the last frame mentioned below. Put the "
    "camera language at the beginning of the sentence and use chronological "
    "connectors (then, while, as).\n"
    "3. No weights like (word:1.2), no markdown, no bullet lists, no explanations, "
    "no preamble.\n"
    "4. Keep every spoken line verbatim inside quotes; never translate or alter "
    "quoted dialogue.\n"
    "5. End with one short 'Lip-Sync Audio Integration:' line.\n"
    "Output only the finished prompt text."
)

RAW_IDEA_TEXT = (
    "Turn this rough idea into the production format described above:\n\n"
    "A medium shot from chest up frames a night-market chef under a corrugated tin "
    "awning, a carbon-steel wok on a roaring jet burner, a column of orange flame "
    "leaping as he tosses oil and garlic."
)

NOTE_TEXT = (
    "PROMPT ASSISTANT SWAPPED\n\n"
    "Node 16 (LongForgePromptAssistant) and node 16a (Gemma-4 CLIPLoader, the "
    "~12508 MB staged model that caused the cudaMallocAsync retries) are gone. "
    "Their slot is now your own 'Promt enchncher ADV' subgraph, which drives a "
    "llama.cpp GGUF vision model through an external llama-server process "
    "(CPU/RAM, not ComfyUI VRAM) and unloads it right after.\n\n"
    "WIRING\n"
    "- 16e Raw idea (PrimitiveStringMultiline) -> ADV input 'Promt' (text_a)\n"
    "- 16c Clip length (PrimitiveInt, seconds) -> ADV input 'int_'\n"
    "- 19 Reference Media first_frame          -> ADV input 'image'\n"
    "- 16f Enhance ON/OFF                      -> ADV input 'switch'\n"
    "- 16b System Prompt literal (muted)       = format rules to paste into the\n"
    "  subgraph's internal 'Prompt' node if you want the H3 Global/Timeline layout\n"
    "- ADV output 'any'                -> LongForgeProject 'scene_data' AND ShowText preview\n\n"
    "CAVEATS\n"
    "1. scene_data is now produced by the LLM, so the multi-scene JSON editor widget "
    "is bypassed. The enhancer emits ONE scene prompt in Global/Timeline format - "
    "keep run_mode on ONE SCENE (or feed a scene list back through a template).\n"
    "2. If you want the RAW prompt to reach LongForge untouched, set the enable "
    "boolean to false: the switch node then forwards the original text.\n"
    "3. Required custom nodes: comfyui-llama-cpp-vendor (LlamaServer*), "
    "ComfyUI-Custom-Scripts (String Literal / ShowText), Comfyroll (CR Text), "
    "comfyui-easy-use (cleanGpuUsed), plus whatever provides DisTorchPurgeVRAMV2.\n"
    "4. Check the absolute paths inside the subgraph (llama-server.exe, GGUF, mmproj)."
)


def props(cnr="comfy-core", ver="0.34.2"):
    return {
        "cnr_id": cnr,
        "ver": ver,
        "ue_properties": {
            "widget_ue_connectable": {},
            "input_ue_unconnectable": {},
            "version": "7.8",
        },
    }


def find_nodes(g, types):
    return [n for n in g["nodes"] if n.get("type") in types]


def drop_node(g, node_id):
    g["links"] = [l for l in g["links"] if isinstance(l, list) and l[1] != node_id and l[3] != node_id]
    g["nodes"] = [n for n in g["nodes"] if n["id"] != node_id]


class Linker:
    def __init__(self, g, byid):
        self.g = g
        self.byid = byid
        ids = [l[0] for l in g["links"] if isinstance(l, list)] + [0]
        self.nxt = max(ids) + 1

    def connect(self, src_id, src_slot, dst_id, dst_name, dtype):
        lid = self.nxt
        self.nxt += 1
        dst = self.byid[dst_id]
        idx = [i for i, x in enumerate(dst["inputs"]) if x.get("name") == dst_name]
        if not idx:
            raise KeyError(f"node {dst_id} ({dst['type']}) has no input '{dst_name}'")
        # ComfyUI lite-graph format: [id, from_node, from_slot, to_node, to_slot, type]
        self.g["links"].append([lid, src_id, src_slot, dst_id, idx[0], dtype])
        dst["inputs"][idx[0]]["link"] = lid
        # a linked widget input must not keep its widget binding
        if "widget" in dst["inputs"][idx[0]]:
            dst["inputs"][idx[0]]["widget"] = None
        out = self.byid[src_id]["outputs"][src_slot]
        if out.get("links") in (None,) or "links" not in out:
            out["links"] = []
        out["links"].append(lid)
        return lid


def main(src, dst):
    adv = json.loads(Path(ADV_TEMPLATE).read_text(encoding="utf-8"))
    sub = adv["definitions"]["subgraphs"][0]

    g = json.loads(Path(src).read_text(encoding="utf-8"))
    byid = {n["id"]: n for n in g["nodes"]}

    # ids of every subgraph definition that looks like the ADV prompt enhancer.
    # The same graph pasted around gets fresh uuids, so match on *content*
    # (the LlamaServerVisionCaption core node plus the input signature), not on id.
    def _sig(sd):
        types = tuple(sorted(n.get("type", "") for n in sd.get("nodes", [])))
        ins = tuple(i.get("name", "") for i in sd.get("inputs", []))
        return types, ins

    def _is_adv(sd):
        types, ins = _sig(sd)
        return ("LlamaServerVisionCaption" in types
                and "text_a" in ins and "int_" in ins and "switch" in ins)

    target_sig = _sig(sub)
    defs = g.setdefault("definitions", {}).setdefault("subgraphs", [])
    adv_sub_ids = {sd["id"] for sd in defs if _sig(sd) == target_sig or _is_adv(sd)}

    # ---- 1. locate the native assistant pair and delete it -------------------
    assistants = find_nodes(g, {"LongForgePromptAssistant"})
    if not assistants:
        print("[warn] no LongForgePromptAssistant found - nothing removed")
    clip_ids = set()
    for a in assistants:
        for inp in a.get("inputs", []):
            if inp.get("type") == "CLIP" and inp.get("link") is not None:
                for l in g["links"]:
                    if isinstance(l, list) and l[0] == inp["link"]:
                        clip_ids.add(l[1])
    for a in assistants:
        drop_node(g, a["id"])
    for cid in clip_ids:
        node = next((n for n in g["nodes"] if n["id"] == cid), None)
        if node is not None and node.get("properties", {}).get("longforge_role") == "assistant_text_model":
            drop_node(g, cid)
    byid = {n["id"]: n for n in g["nodes"]}

    # ---- 1b. drop the leftovers of the native assistant and of the half-wired
    #      ADV attempt (its loose Prompt / Enable / Duration / extra LoadImage
    #      widgets). The tidy 16b..16f nodes below replace them.
    removed_ids = set(clip_ids) | {a["id"] for a in assistants}
    inst_type = next((n["type"] for n in g["nodes"] if n.get("type") in adv_sub_ids), None)
    inst_nodes = [n for n in g["nodes"] if n.get("type") in adv_sub_ids]
    inst_ids = {n["id"] for n in inst_nodes}
    # the instance that already has wired feeders wins, others are leftovers
    def _wired(n):
        return sum(1 for l in g["links"] if l[3] == n["id"])
    inst_id = max(inst_ids, key=lambda i: _wired(next(n for n in inst_nodes if n["id"] == i))) if inst_ids else None
    for n in list(g["nodes"]):
        if n["id"] == inst_id:
            continue                      # keep the chosen subgraph instance
        if n.get("type") == inst_type:
            removed_ids.add(n["id"])      # duplicate/leftover enhancer instance
            drop_node(g, n["id"])
            continue
        # anything still linked to the enhancer instance (its old half-wired
        # feeders) is dropped too - we re-create clean feeders below
        feeds_inst = any(l[3] == inst_id for l in g["links"] if l[0] == n["id"] or l[1] == n["id"])
        linked_in = any(i.get("link") is not None for i in n.get("inputs", []))
        linked_out = any(o.get("links") for o in n.get("outputs", []))
        if (linked_in or linked_out) and not feeds_inst:
            continue                      # still part of a live signal path
        t = n.get("type")
        orphan = (t in ("PrimitiveStringMultiline", "PrimitiveBoolean")
                  or (t == "PrimitiveInt" and not n.get("inputs"))
                  or (t == "LoadImage" and not (n.get("title") or "").lower().startswith("first")))
        if not orphan:
            continue
        # only remove things that belonged to the assistant area
        pa_groups = [gr for gr in g.get("groups", [])
                     if (gr.get("title") or "").strip() == "Prompt Assistant"]
        in_pa = any(n["id"] in gr.get("nodes", []) for gr in pa_groups)
        near_removed = any(abs(n["pos"][0] - byid[rid]["pos"][0]) < 900
                           and abs(n["pos"][1] - byid[rid]["pos"][1]) < 900
                           for rid in removed_ids if rid in byid) if removed_ids else False
        if in_pa or near_removed:
            removed_ids.add(n["id"])
            drop_node(g, n["id"])
    # whatever is now fully orphaned (no input link, no output link) and is one of
    # the enhancer feeder types gets muted instead of deleted - safer for the user.
    byid = {n["id"]: n for n in g["nodes"]}
    for n in g["nodes"]:
        if n["id"] == inst_id or n.get("type") == inst_type:
            continue
        t = n.get("type")
        if t not in ("PrimitiveStringMultiline", "PrimitiveBoolean", "LoadImage"):
            continue
        if any(i.get("link") is not None for i in n.get("inputs", [])):
            continue
        if any(o.get("links") for o in n.get("outputs", [])):
            continue
        n["mode"] = 4          # muted
        n["title"] = "(unused) " + (n.get("title") or t)
    for gr in g.get("groups", []):
        if isinstance(gr.get("nodes"), list):
            gr["nodes"] = [x for x in gr["nodes"] if x in byid]

    # ---- 2. reuse the already-present ADV instance, else create one ----------
    # Any node whose type matches a known "Promt enhancer ADV" subgraph id counts
    # as an existing instance (the same graph copied around gets new uuids).
    inst = next((n for n in g["nodes"] if n.get("type") in adv_sub_ids), None)
    if inst is not None and inst["type"] != sub["id"]:
        # Keep the definition that is already inside this workflow (it is the one
        # the user maintains); just remember its id. Rewriting a subgraph type
        # without fixing inputs[].link_id would break the instance.
        sub = next(sd for sd in defs if sd["id"] == inst["type"])
    if inst is None:
        nid = max(byid) + 1
        inst = {
            "id": nid, "type": sub["id"], "pos": [230, 1180], "size": [230, 140],
            "flags": {}, "order": 4, "mode": 0,
            "title": "16 · Promt Enhancer ADV (llama.cpp)",
            "inputs": [
                {"name": "int_", "type": "INT", "link": None},
                {"label": "Promt", "name": "text_a", "shape": 7, "type": "STRING", "link": None},
                {"label": "First frame (optional)", "name": "image", "shape": 7, "type": "IMAGE", "link": None},
                {"label": "switch", "name": "switch", "type": "BOOLEAN", "widget": {"name": "switch"}, "link": None},
            ],
            "outputs": [{"name": "any", "type": "*", "slot_index": 0, "links": []}],
            "properties": props(),
            "widgets_values": [False, 0],
            "widgets_values_named": {"switch": False, "seed": 0},
        }
        g["nodes"].append(inst)
        byid[nid] = inst
    inst["title"] = "16 · Promt Enhancer ADV (llama.cpp)"
    for inp in inst["inputs"]:
        if inp.get("name") == "image":
            inp["label"] = "First frame (optional)"

    if inst is None and not any(_sig(sd) == target_sig or _is_adv(sd) for sd in defs):
        defs.append(copy.deepcopy(sub))

    # ---- 3. helper nodes -----------------------------------------------------
    base = max(byid)
    lit_id, dur_id, show_id, idea_id = base + 1, base + 2, base + 3, base + 4
    # NOTE: the raw idea goes into the subgraph as `text_a` (the part the LLM has
    # to rewrite); the enhancer's own system prompt stays inside the subgraph.

    node_lit = {
        "id": lit_id, "type": "String Literal", "pos": [-760, 1120], "size": [420, 320],
        "flags": {}, "order": 0, "mode": 0, "inputs": [],
        "title": "16b · System Prompt (format rules)",
        "outputs": [{"name": "STRING", "type": "STRING", "slot_index": 0, "links": [], "label": "System Prompt"}],
        "properties": {**props(ver="0.39.2"), "Node name for S&R": "String Literal"},
        "widgets_values": [SYSTEM_PROMPT],
    }
    node_idea = {
        "id": idea_id, "type": "PrimitiveStringMultiline", "pos": [-760, 1470], "size": [420, 260],
        "flags": {}, "order": 1, "mode": 0,
        "title": "16e · Raw idea (your text)",
        "inputs": [{"label": "value", "name": "value", "type": "STRING",
                    "widget": {"name": "value"}, "link": None}],
        "outputs": [{"name": "STRING", "type": "STRING", "slot_index": 0, "links": []}],
        "properties": {**props(ver="0.16.3"), "Node name for S&R": "PrimitiveStringMultiline"},
        "widgets_values": [RAW_IDEA_TEXT],
    }
    node_dur = {
        "id": dur_id, "type": "PrimitiveInt", "pos": [-760, 1760], "size": [210, 90],
        "flags": {}, "order": 2, "mode": 0,
        "title": "16c · Clip length (seconds)",
        "inputs": [{"label": "value", "name": "value", "type": "INT", "widget": {"name": "value"}, "link": None}],
        "outputs": [{"name": "INT", "type": "INT", "slot_index": 0, "links": []}],
        "properties": {**props(ver="0.42.1"), "Node name for S&R": "PrimitiveInt"},
        "widgets_values": [16, "fixed"],
    }
    node_show = {
        "id": show_id, "type": "ShowText|pysssss", "pos": [620, 1120], "size": [640, 300],
        "flags": {}, "order": 6, "mode": 0,
        "title": "16d · Enhanced prompt (preview)",
        "inputs": [{"name": "text", "shape": 7, "type": "*", "link": None, "label": "Enhanced Prompt"}],
        "outputs": [],
        "properties": {**props("ComfyUI-Custom-Scripts", "1.0.0"), "Node name for S&R": "ShowText|pysssss"},
        "widgets_values": [""],
    }
    g["nodes"] += [node_lit, node_idea, node_dur, node_show]
    byid.update({lit_id: node_lit, idea_id: node_idea, dur_id: node_dur, show_id: node_show})

    # duration hint: prefer the real clip length from LongForgeVideoSettings
    # (frames / fps -> seconds, that is what the ADV enhancer asks the LLM for),
    # fall back to the last "At frame X-Y" marker of scene 1.
    project = next(iter(find_nodes(g, {"LongForgeProject"})), None)
    settings = next(iter(find_nodes(g, {"LongForgeVideoSettings"})), None)
    seconds = None
    if settings is not None and isinstance(settings.get("widgets_values"), list):
        try:
            frames = int(settings["widgets_values"][3])
            new_sec = float(settings["widgets_values"][11] or 0)
            if new_sec > 0:
                seconds = round(new_sec)
            elif frames:
                seconds = max(1, round(frames / 25))
        except Exception:
            seconds = None
    frames_hi = []
    if project is not None and isinstance(project.get("widgets_values"), list) and len(project["widgets_values"]) > 3:
        try:
            scenes = json.loads(project["widgets_values"][3])
            txt = scenes[0].get("prompt", "") if scenes else ""
            pairs = re.findall(r"[Aa]t frame\s+(\d+)\D{1,6}?(\d+)", txt)
            frames_hi = [int(b) for _, b in pairs]
        except Exception:
            frames_hi = []
    node_dur["widgets_values"][0] = seconds or (max(frames_hi) if frames_hi else 16)

    # vision input: the workflow's own "First frame" anchor if present,
    # otherwise the still-image loader that feeds it (LongForgeMediaLoader).
    media = next((n for n in g["nodes"] if n.get("type") == "LongForgeMediaLoader"), None)
    anchor = next((n for n in g["nodes"]
                   if n.get("type") == "LoadImage" and (n.get("title") or "").lower().startswith("first")), None)
    vision_src = media if media is not None else anchor

    # ---- 4. wire it up -------------------------------------------------------
    lk = Linker(g, byid)
    lk.connect(idea_id, 0, inst["id"], "text_a", "STRING")  # raw idea -> subgraph
    # keep the format-rules literal visible but not wired: paste it into the
    # subgraph's internal "Prompt" node if you want the H3 timeline format.
    node_lit["mode"] = 4  # muted
    lk.connect(dur_id, 0, inst["id"], "int_", "INT")        # clip length
    if vision_src is not None:
        slot = 0
        if vision_src.get("type") == "LongForgeMediaLoader":
            named = [i for i, o in enumerate(vision_src["outputs"]) if o.get("name") == "first_frame"]
            slot = named[0] if named else 0
        lk.connect(vision_src["id"], slot, inst["id"], "image", "IMAGE")
    else:
        print("[info] no first-frame source found - ADV runs text-only ('image' left empty)")

    en_id = base + 5
    node_en = {
        "id": en_id, "type": "PrimitiveBoolean", "pos": [-760, 1880], "size": [210, 90],
        "flags": {}, "order": 3, "mode": 0,
        "title": "16f · Enhance ON/OFF",
        "inputs": [{"label": "value", "name": "value", "type": "BOOLEAN",
                    "widget": {"name": "value"}, "link": None}],
        "outputs": [{"name": "BOOLEAN", "type": "BOOLEAN", "slot_index": 0, "links": []}],
        "properties": {**props(ver="0.22.0"), "Node name for S&R": "PrimitiveBoolean"},
        "widgets_values": [True],
    }
    g["nodes"].append(node_en)
    byid[en_id] = node_en
    lk.connect(en_id, 0, inst["id"], "switch", "BOOLEAN")

    if project is not None:
        lk.connect(inst["id"], 0, project["id"], "scene_data", "STRING")
    else:
        print("[warn] LongForgeProject not found - enhanced prompt not connected to scene_data")
    lk.connect(inst["id"], 0, show_id, "text", "*")

    # integrity pass: rebuild links[] from what the slots actually reference
    def _slot_links(lid_map):
        out = []
        for n in g["nodes"]:
            for o in n.get("outputs", []):
                o["links"] = [x for x in (o.get("links") or []) if x in lid_map]
        return out

    kept = []
    for l in g["links"]:
        lid, s_id, s_slot, d_id, d_slot, tp = l
        if s_id not in byid or d_id not in byid:
            continue
        sn, dn = byid[s_id], byid[d_id]
        if s_slot >= len(sn.get("outputs", [])):
            continue
        if not isinstance(d_slot, int) or d_slot >= len(dn.get("inputs", [])):
            continue
        if dn["inputs"][d_slot].get("link") != lid:
            continue
        kept.append(l)
    g["links"] = kept
    _slot_links({l[0] for l in kept})
    # every input.link must have a matching record, otherwise clear it
    present = {(l[3], l[4]): l[0] for l in kept}
    for n in g["nodes"]:
        for i, inp in enumerate(n.get("inputs", [])):
            if inp.get("link") is not None and present.get((n["id"], i)) != inp["link"]:
                inp["link"] = None
    # re-sync output.links with the surviving records
    for n in g["nodes"]:
        for o in n.get("outputs", []):
            pass
    by_slot = {}
    for l in kept:
        by_slot.setdefault((l[1], l[2]), []).append(l[0])
    for n in g["nodes"]:
        for si, o in enumerate(n.get("outputs", [])):
            o["links"] = sorted(by_slot.get((n["id"], si), []), key=lambda x: x)

    g["last_node_id"] = max(n["id"] for n in g["nodes"])
    g["last_link_id"] = max([l[0] for l in g["links"] if isinstance(l, list)] + [0])

    # ---- 5. group + note -----------------------------------------------------
    for gr in g.get("groups", []):
        if (gr.get("title") or "").strip() == "Prompt Assistant":
            gr["nodes"] = sorted(set(gr.get("nodes", [])
                                     + [inst["id"], lit_id, dur_id, show_id, idea_id, en_id]
                                     + ([vision_src["id"]] if vision_src is not None else [])))
            y0, h = gr["bounding"][1], gr["bounding"][3]
            gr["bounding"] = [-800, y0, 2100, max(h, 950)]
    note = next((n for n in g["nodes"] if n.get("type") == "MarkdownNote"), None)
    if note is not None:
        note["title"] = "RU · Инструкция (ADV swap)"
        if isinstance(note.get("widgets_values"), list) and note["widgets_values"]:
            note["widgets_values"][0] = NOTE_TEXT

    Path(dst).write_text(json.dumps(g, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] wrote {dst}")
    print(f"     removed: {[a['id'] for a in assistants]} (+ assistant CLIP loaders {sorted(clip_ids)})")
    print(f"     added:   ADV instance {inst['id']}, String Literal {lit_id}, "
          f"PrimitiveInt {dur_id}, ShowText {show_id}")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "/tmp/target.json"
    b = sys.argv[2] if len(sys.argv) > 2 else str(Path(a).with_name(Path(a).stem + "_ADV.json"))
    main(a, b)
