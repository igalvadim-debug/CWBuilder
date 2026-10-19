# -*- coding: utf-8 -*-
"""Gemeinsame Szenen-Planung fuer alle Video-Modi (Minimax H3, LTX 2.3, LTX 2.5).

Ein Nutzer gibt die Laenge als "Scene-Anzahl x Sekunden" an, z.B.:
    3x6      -> 3 Szenen a 6 s = 18 s
    3*6      -> dito
    3 mal 6  -> dito (auch "drei mal sechs")
    18       -> eine Szene mit 18 s
    3:5,4    -> 3 Szenen: 5 s, dann 4 s ... (Aufzaehlung)
Der Plan wird IMMER vollstaendig erzeugt: jede Scene 1..N bekommt einen Prompt
und eine Dauer - keine Scene wird uebersprungen. Fehlt Text fuer spaetere
Szenen, wird der Hauptprompt wiederholt und eine Warnung ausgegeben.
"""
from __future__ import annotations

import re

_NUM_WORDS_DE = {
    "null": 0, "ein": 1, "eine": 1, "einem": 1, "einen": 1, "zwei": 2, "drei": 3,
    "vier": 4, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9,
    "zehn": 10, "elf": 11, "zwoelf": 12,
}

_MULTIPLY_WORDS = ("mal", "x", "*", ".")


def _num(tok: str) -> float | None:
    """Zahl, deutsches Zahlwort oder Sekundenangabe lesen; sonst None liefern."""
    t = tok.strip().lower().replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        pass
    if t in _NUM_WORDS_DE:
        return float(_NUM_WORDS_DE[t])
    m = re.match(r"^(\d+(?:[.,]\d+)?)\s*(s|sek|secs|sec|seconds|sekunden)$", t)
    return float(m.group(1).replace(",", ".")) if m else None


def parse_length_spec(spec: str | None, *, default_scenes: int = 1,
                      default_seconds: float = 6.0) -> list[float]:
    """Zerlegt eine Laengen-Angabe in eine Liste von Szenendauern in Sekunden.

    Beispiele: "3x6" -> [6, 6, 6];  "18" -> [18];  "2x8+2" -> [8, 8, 2];
    "3 mal 6" -> [6, 6, 6];  "" / None -> Default-Werte.
    """
    s = (spec or "").strip()
    if not s:
        return [float(default_seconds)] * max(1, int(default_scenes))

    # Aufzaehrung mit '+' : 2x8+2  oder  6+6+6
    parts = [p.strip() for p in s.split("+") if p.strip()]
    durations: list[float] = []
    for part in parts:
        # N:A,B -> N Szenen; fehlende Dauern wiederholen den letzten Wert.
        m = re.fullmatch(r"(\d+)\s*:\s*(.+)", part)
        if m:
            count = int(m.group(1))
            secs = [_num(tok) for tok in m.group(2).split(",")]
            if count >= 1 and all(sec is not None and sec > 0 for sec in secs):
                durations += (secs + [secs[-1]] * max(0, count - len(secs)))[:count]
                continue
        # N mal M / NxM / N*M  -> N Szenen mit je M Sekunden
        m = re.match(r"^(\w+(?:[.,]\d+)?)\s*(?:mal|x|\*)\s*(\w+(?:[.,]\d+)?)$", part, re.I)
        if m:
            n, sec = _num(m.group(1)), _num(m.group(2))
            if n and sec and n >= 1 and sec > 0:
                durations += [sec] * int(round(n))
                continue
        v = _num(part)
        if v is not None and v > 0:
            durations.append(v)
            continue
        raise ValueError(f"Laengen-Angabe nicht verstanden: '{part}' (erwartet z.B. '3x6' oder '18')")
    if not durations:
        raise ValueError(f"Laengen-Angabe nicht verstanden: '{spec}'")
    return durations


def split_scene_prompts(prompt: str, count: int) -> list[str]:
    """Verteilt einen Text auf genau ``count`` Szenen-Prompts.

    Trenner: leere Zeilen, 'SZENE n:'/'SCENE n:'/' scene n', nummerierte
    Listen ('1) ', '2. ') sowie einzelne Absaetze, wenn genug vorhanden sind.
    Das Ergebnis hat IMMER exakt ``count`` Eintraege (keine Scene fehlt);
    leer ausgegangene Szenen wiederholen den letzten bzw. Haupttext.
    """
    text = (prompt or "").strip()
    count = max(1, int(count))
    if not text:
        return [""] * count

    # explizite Szenen-Marker: "SZENE 1: ..." / "Scene 2 - ..."
    marks = list(re.finditer(
        r"(?im)^\s*(?:[\-*#>\u00b7]*\s*)(?:s(?:z|c)e(?:ne|na|ene)?|kapitel|shot)\s*(?:nr\.?|no\.?|#)?\s*\d+\s*[:.\-)]?\s*",
        text))
    if len(marks) >= 2:
        segs, prev = [], 0
        head = text[:marks[0].start()].strip()
        for i, mk in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            seg = text[mk.end():end].strip()
            if seg:
                segs.append(seg)
        if segs:
            if head and len(segs) < count:
                segs.insert(0, head)
            return _fit(segs, count, text)

    # nummerierte Liste am Zeilenanfang: "1) ..." "2. ..."
    nums = list(re.finditer(r"(?m)^\s*(\d{1,2})\s*[.)]\s+", text))
    idx = {}
    for mk in nums:
        n = int(mk.group(1))
        if n not in idx:
            idx[n] = mk
    if len(idx) >= 2 and sorted(idx)[:len(idx)] == list(range(1, len(idx) + 1)):
        keys = sorted(idx)
        segs = []
        for j, k in enumerate(keys):
            start = idx[k].end()
            end = idx[keys[j + 1]].start() if j + 1 < len(keys) else len(text)
            seg = text[start:end].strip()
            if seg:
                segs.append(seg)
        if segs:
            return _fit(segs, count, text)

    # Absaetze (leere Zeile als Trenner)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) >= count:
        return _fit(paras, count, text)
    if len(paras) > 1:
        return _fit(paras, count, text)

    # Saetze als letzte Reserven
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sents) > 1:
        return _fit(sents, count, text)
    return [text] * count


def _fit(segs: list[str], count: int, fallback: str) -> list[str]:
    """Erzeugt exakt ``count`` Prompts; Ueberhang bleibt in der letzten Szene."""
    out = list(segs[:count])
    if count > 0 and len(segs) > count:
        out[-1] = "\n\n".join(segs[count - 1:])
    while len(out) < count:
        src = out[-1] if out else fallback
        out.append(src)
    return out


def scene_plan(prompt: str, durations: list[float]) -> list[dict]:
    """Volstaendiger Szenenplan: [{"i": 1..N, "prompt": ..., "duration": ...}].

    Die Anzahl Szenen ergibt sich aus der Laengen-Angabe; der Text wird auf
    genau so viele Szenen verteilt - keine Scene fehlt, auch bei Text-Undeko.
    """
    durs = list(durations) or [6.0]
    texts = split_scene_prompts(prompt, len(durs))
    return [{"i": i + 1, "prompt": texts[i], "duration": float(durs[i])}
            for i in range(len(durs))]


def total_seconds(plan: list[dict]) -> float:
    """Szenendauern summieren und auf drei Nachkommastellen runden."""
    return round(sum(s["duration"] for s in plan), 3)


def ltx_frames(duration_s: float, fps: float) -> int:
    """LTX verlangt frame_count = 8k+1; hier die passende Gueltigkeit (min. 9)."""
    f = max(9, round(float(duration_s) * float(fps)))
    f = ((f - 1 + 7) // 8) * 8 + 1
    return f


def minimax_frames(duration_s: float, fps: float) -> int:
    """Minimax H3 verlangt 17k+5 Frames (wie der HTML-Generator)."""
    r = max(5, round(float(duration_s) * float(fps)))
    return 17 * ((r - 5 + 16) // 17) + 5


def describe_trigger_name(name: str) -> str:
    """LoRA-Dateiname -> wahrscheinliches Triggerwort (best-effort).

    Viele LoRAs tragen das Triggerwort im Dateinamen, z.B.
    'epic_cumshots-V1-LTX_2_3-CUMSH0T.safetensors' -> 'CUMSH0T' oder
    'ltx2-squish_trigger word_squish it.safetensors' -> 'squish it'.
    Bei mehreren Kandidaten wird der ERSTE genommen.
    """
    base = name.replace("\\", "/").split("/")[-1]
    base = re.sub(r"\.(safetensors|ckpt|pt|bin)$", "", base, flags=re.I)
    # 1) explizit: "... trigger word <TW>" / "..._trigger_<TW>"
    m = re.search(r"trigger[\s_-]+(?:word[\s_-]+)?([A-Za-z0-9][\w A-Za-z0-9-]{1,40}?)"
                  r"(?=[\s_.-]*(?:$|rank\d+|\d{3,}|v\d|comfy|steps?$))", base, re.I)
    if m:
        return m.group(1).strip(" -_")
    # 2) CamelCase-Kuerel wie '...-CUMSH0T' / '_D4S1W4_NSFWSME' am Ende
    m = re.search(r"[-_]([A-Z][A-Za-z0-9]*(?:[_-][A-Z0-9][A-Za-z0-9]*)*)$", base)
    if m:
        cand = m.group(1)
        letters = re.sub(r"[^A-Za-z]", "", cand)
        upper_ratio = sum(c.isupper() for c in letters) / max(1, len(letters))
        has_digit = any(c.isdigit() for c in letters)
        if len(letters) >= 4 and (upper_ratio >= 0.5 or has_digit) and \
                not re.fullmatch(r"(?i)v?\d+(\.\d+)?|bf16|fp16|fp8|int8|rank\d+|comfy|steps?|lora|final|full", cand):
            return cand
    # 3) Schreibung wie im Namen: Grossbuchstaben-Kuerel mitten im String
    m = re.search(r"(?<![A-Za-z])([A-Z][A-Z0-9]{3,}(?:_[A-Z0-9]+)*)(?![A-Za-z0-9])", base)
    if m:
        return m.group(1)
    return ""


def apply_trigger(prompt: str, trigger: str) -> str:
    """Triggerwort voranstellen, wenn noch nicht vorhanden."""
    if not trigger:
        return prompt
    if trigger.lower() in (prompt or "").lower():
        return prompt
    return f"{trigger} {prompt}".strip()


VL_SYSTEM_PROMPT = (
    "You are a meticulous vision assistant for a multi-shot video pipeline. "
    "Describe the supplied image (the LAST FRAME of the previous shot) precisely: "
    "subjects and their appearance/clothing/pose, camera angle and framing, lens look, "
    "lighting, color grade, environment, mood. Then extend the draft prompt for the NEXT "
    "shot so it continues seamlessly from this frame while advancing the story. "
    "Output one single flowing paragraph in English: first what the incoming frame shows, "
    "then how the next shot continues it. No lists, no headings, no preamble."
)


def vl_prompt(draft: str, max_chars: int = 400) -> str:
    """User-Auftrag an das VL-LLM im Workflow: Bild beschreiben + Prompt erweitern."""
    draft = (draft or "").strip() or "continue the scene naturally"
    return (
        "Describe this image (last frame of the previous shot) in detail: subjects, "
        "their look and pose, camera angle, framing, lighting, colors, environment. "
        f"Then expand this draft for the NEXT shot into a rich prompt (max ~{max_chars} words total) "
        f"that continues seamlessly from the frame and follows the draft: \"{draft}\". "
        "Answer with ONE flowing English paragraph only."
    )
