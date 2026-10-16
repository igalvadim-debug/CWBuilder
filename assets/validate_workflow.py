#!/usr/bin/env python3
"""ComfyUI Workflow Validator - проверяет JSON на частые ошибки"""
import json
import sys
from pathlib import Path
from typing import Any

def validate_workflow(filepath: Path) -> list[str]:
    errors = []
    warnings = []

    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            wf = json.load(f)
        except json.JSONDecodeError as e:
            return [f"JSON PARSE ERROR: {e}"]

    nodes = wf.get('nodes', [])
    links = wf.get('links', [])
    last_node_id = wf.get('last_node_id', 0)
    last_link_id = wf.get('last_link_id', 0)

    # 1. Проверка last_node_id
    node_ids = [n.get('_id') for n in nodes if '_id' in n]
    if node_ids:
        max_node_id = max(node_ids)
        if last_node_id != max_node_id:
            errors.append(f"last_node_id={last_node_id} != max(_id)={max_node_id}")

    # 2. Проверка last_link_id
    if links:
        max_link_id = len(links)  # links — массив массивов, ID не явные, но порядок важен
        if last_link_id != len(links):
            warnings.append(f"last_link_id={last_link_id} != len(links)={len(links)}")

    # 3. Дубликаты _id
    seen_ids = set()
    for n in nodes:
        nid = n.get('_id')
        if nid in seen_ids:
            errors.append(f"Duplicate node _id: {nid}")
        seen_ids.add(nid)

    # 4. Проверка каждого узла
    node_outputs_map = {}  # node_id -> {slot_index: type}
    for n in nodes:
        nid = n.get('_id')
        class_type = n.get('class_type', 'UNKNOWN')
        outputs = n.get('outputs', {})

        # 4a. Пустой outputs у не-входных узлов
        if not outputs and class_type not in ('LoadImage', 'LoadAudio', 'LoadVideo', 'CheckpointLoaderSimple'):
            # Допустим для входных, но предупредим
            warnings.append(f"Node {nid} ({class_type}): empty outputs")

        # 4b. Проверка структуры outputs
        for out_name, out_def in outputs.items():
            links_list = out_def.get('links', [])
            slot_index = out_def.get('slot_index')
            out_type = out_def.get('type')

            if slot_index is None:
                errors.append(f"Node {nid} ({class_type}) output '{out_name}': missing slot_index")

            if out_type is None:
                errors.append(f"Node {nid} ({class_type}) output '{out_name}': missing type")

            # Запоминаем доступные выходы
            if nid not in node_outputs_map:
                node_outputs_map[nid] = {}
            if slot_index is not None:
                node_outputs_map[nid][slot_index] = out_type

    # 5. Проверка ссылок (links)
    # link format: [link_id, src_node, src_slot, dst_node, dst_slot, type]
    for i, link in enumerate(links):
        if len(link) != 6:
            errors.append(f"Link {i}: invalid format (len={len(link)}), expected 6: {link}")
            continue

        link_id, src_node, src_slot, dst_node, dst_slot, link_type = link

        # Проверка существования узлов
        if src_node not in node_outputs_map:
            errors.append(f"Link {link_id}: src_node {src_node} does not exist")
        elif src_slot not in node_outputs_map[src_node]:
            errors.append(f"Link {link_id}: src_node {src_node} has no output slot {src_slot} (available: {list(node_outputs_map[src_node].keys())})")
        else:
            src_type = node_outputs_map[src_node][src_slot]
            if src_type != link_type:
                warnings.append(f"Link {link_id}: type mismatch src={src_type} vs link={link_type}")

        # Проверка целевого узла (inputs проверяем по class_type эвристически)
        dst_node_obj = next((n for n in nodes if n.get('_id') == dst_node), None)
        if not dst_node_obj:
            errors.append(f"Link {link_id}: dst_node {dst_node} does not exist")

    # 6. Проверка входов у узлов (inputs ссылаются на существующие выходы)
    for n in nodes:
        nid = n.get('_id')
        inputs = n.get('inputs', {})
        for in_name, in_val in inputs.items():
            if isinstance(in_val, list) and len(in_val) == 3:
                ref_node, ref_slot, ref_type = in_val
                if ref_node not in node_outputs_map:
                    errors.append(f"Node {nid} ({n.get('class_type')}) input '{in_name}': ref_node {ref_node} does not exist")
                elif ref_slot not in node_outputs_map[ref_node]:
                    errors.append(f"Node {nid} input '{in_name}': ref_node {ref_node} has no output slot {ref_slot}")
                else:
                    actual_type = node_outputs_map[ref_node][ref_slot]
                    if actual_type != ref_type:
                        warnings.append(f"Node {nid} input '{in_name}': type mismatch expected={ref_type} actual={actual_type}")

    return errors + warnings

if __name__ == '__main__':
    assets_dir = Path(r"D:\claudeAgent\Coder\projects\Minimax_test\assets")
    json_files = list(assets_dir.glob("*.json"))

    if not json_files:
        print("No JSON files found")
        sys.exit(1)

    print(f"Found {len(json_files)} workflow files\n")

    all_ok = True
    for jf in sorted(json_files):
        print(f"{'='*60}")
        print(f"VALIDATING: {jf.name}")
        print(f"{'='*60}")

        issues = validate_workflow(jf)
        if issues:
            all_ok = False
            for issue in issues:
                level = "ERROR" if issue.startswith(("last_node", "Duplicate", "Link", "Node")) else "WARN"
                print(f"  [{level}] {issue}")
        else:
            print("  [OK] No issues found")
        print()

    print(f"{'='*60}")
    if all_ok:
        print("ALL WORKFLOWS VALID")
        sys.exit(0)
    else:
        print("SOME WORKFLOWS HAVE ERRORS")
        sys.exit(1)