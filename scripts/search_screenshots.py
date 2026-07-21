#!/usr/bin/env python3
"""Rank screenshot evidence entries for Nihaisha course notes."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
QUERY_SPLIT_RE = re.compile(r"[\s,，、;；:：|/\\+]+")
QUERY_FILLER_RE = re.compile(
    r"(?:给我|帮我|请|把|找出来|找出|找|查一下|查询|搜索|检索|相关|有关|里面|其中|"
    r"课程|板书|截图|证据|图片|图|讲到|讲|有没有|是否|一下|这个|那个)"
)
QUERY_RELATION_RE = re.compile(r"(?:以及|还有|并且|同时)")

DOMAIN_TERMS = [
    "太阳中风",
    "太阳伤寒",
    "热结旁流",
    "阳中有阴",
    "阴中有阳",
    "性味归经",
    "君臣佐使",
    "小便自利",
    "小便不利",
    "心下悸",
    "胁下痞",
    "胸胁苦满",
    "手足温",
    "手足厥冷",
    "少阴",
    "太阴",
    "厥阴",
    "太阳",
    "阳明",
    "少阳",
    "下利",
    "黄疸",
    "胸痹",
    "水气",
    "痰饮",
    "虚劳",
    "腹痛",
    "恶寒",
    "发热",
    "无汗",
    "有汗",
    "命宫",
    "四化",
    "阳宅",
    "风水",
    "八卦",
    "足三里",
    "三阴交",
    "关元",
    "照海",
    "任脉",
    "督脉",
    "加减",
]
COURSE_QUERY_TERMS = [
    "黄帝内经",
    "神农本草",
    "伤寒论",
    "金匮要略",
    "仲景心法",
    "临床案例",
    "八纲辨证",
    "扶阳论坛",
    "易筋经",
    "天纪",
    "针灸",
    "内经",
    "本草",
    "金匮",
    "伤寒",
]
SCREENSHOT_ENTITY_TERMS = [
    "内关穴",
    "内关",
    "五行",
    "五脏",
    "附子",
]
FORMULA_RE = re.compile(
    r"(?:小|大|桂枝|麻黄|葛根|柴胡|四逆|承气|白虎|真武|五苓|半夏|甘草|黄连|"
    r"黄芩|附子|茯苓|当归|吴茱萸|白通|建中|乌梅|苓桂|桃核|抵当|陷胸)"
    r"[\u4e00-\u9fff]{0,8}?[汤散丸饮膏丹方]"
)
EVIDENCE_FILES = [
    ROOT / "references" / "screenshot-evidence.md",
    ROOT / "references" / "jingui-screenshot-evidence.md",
    ROOT / "references" / "zhongjing-xinfa-screenshot-evidence.md",
    ROOT / "references" / "clinical-cases-screenshot-evidence.md",
    ROOT / "references" / "bagang-screenshot-evidence.md",
    ROOT / "references" / "fuyang-screenshot-evidence.md",
    ROOT / "references" / "yijinjing-screenshot-evidence.md",
    ROOT / "references" / "huangdi-screenshot-evidence.md",
    ROOT / "references" / "bencao-screenshot-evidence.md",
    ROOT / "references" / "acupuncture-screenshot-evidence.md",
    ROOT / "references" / "tianji-screenshot-evidence.md",
]
SAFETY_NOTICE = (
    "安全提示：以下仅为课程证据定位。涉及剂量、煎服、针灸、放血、外敷、"
    "急症或毒烈药内容时，不得作为个人医疗建议或自行操作依据。"
)


def parse_entries(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    lesson = ""
    current: dict[str, str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            lesson = line.removeprefix("## ").strip()
        elif line.startswith("- `"):
            match = re.match(r"- `([^`]+)` \[([^\]]+)\] (.*)", line)
            if match:
                current = {
                    "lesson": lesson,
                    "time": match.group(1),
                    "category": match.group(2),
                    "desc": match.group(3),
                    "path": "",
                }
                entries.append(current)
        elif current and line.strip().startswith("- 截图路径："):
            current["path"] = line.split("截图路径：", 1)[1].strip()
    return entries


def add_unique(items: list[str], value: str) -> None:
    value = value.strip(" \t\r\n\"'`“”‘’（）()[]【】")
    if value and value not in items:
        items.append(value)


def expand_compound_term(term: str) -> list[str]:
    term = term.strip()
    if not term:
        return []

    expanded: list[str] = []

    if "加减" in term and term != "加减":
        before, after = term.split("加减", 1)
        for value in expand_compound_term(before):
            add_unique(expanded, value)
        add_unique(expanded, "加减")
        for value in expand_compound_term(after):
            add_unique(expanded, value)
        return expanded

    matches: list[tuple[int, int, str]] = []
    for match in FORMULA_RE.finditer(term):
        matches.append((match.start(), match.end(), match.group(0)))
    for known in DOMAIN_TERMS:
        if known in term:
            start = term.index(known)
            matches.append((start, start + len(known), known))

    if matches and any(value != term for _, _, value in matches):
        selected: list[tuple[int, int, str]] = []
        for start, end, value in sorted(matches, key=lambda item: (item[0], -(item[1] - item[0]))):
            if any(start >= kept_start and end <= kept_end for kept_start, kept_end, _ in selected):
                continue
            selected.append((start, end, value))
        for _, _, value in selected:
            add_unique(expanded, value)
        return expanded

    add_unique(expanded, term)
    return expanded


def normalize_terms(raw_terms: list[str]) -> list[str]:
    raw_text = " ".join(raw_terms)
    strong_terms: list[str] = []
    for match in FORMULA_RE.finditer(raw_text):
        add_unique(strong_terms, match.group(0))
    for term in [*COURSE_QUERY_TERMS, *SCREENSHOT_ENTITY_TERMS, *DOMAIN_TERMS]:
        if term in raw_text:
            add_unique(strong_terms, term)
    if strong_terms:
        return strong_terms

    parts: list[str] = []
    for raw in raw_terms:
        text = raw.strip()
        if not text:
            continue
        text = QUERY_FILLER_RE.sub(" ", text)
        text = QUERY_RELATION_RE.sub(" ", text)
        for part in QUERY_SPLIT_RE.split(text):
            add_unique(parts, part)

    normalized: list[str] = []
    for part in parts:
        for term in expand_compound_term(part):
            add_unique(normalized, term)
    return normalized


def score_entry(entry: dict[str, str], terms: list[str]) -> int:
    hay = f"{entry['lesson']} {entry['time']} {entry['category']} {entry['desc']} {entry['path']}"
    active_terms = [term for term in terms if term]
    score = 0
    matched_terms = 0
    for term in active_terms:
        term_score = 0
        if term in entry["desc"]:
            term_score += 10
        if term in entry["category"]:
            term_score += 4
        if term in entry["lesson"] or term in entry["path"]:
            term_score += 3
        if term in hay:
            term_score += 1
        if term_score:
            matched_terms += 1
            score += term_score
    if matched_terms == 0:
        return 0
    if matched_terms > 1:
        score += matched_terms * 3
    if matched_terms == len(active_terms):
        score += 20
    if resolve_path(entry["path"]).exists():
        score += 2
    return score


def resolve_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def path_status(path: str) -> str:
    if path.startswith("未上传"):
        return "not-uploaded"
    return "exists" if resolve_path(path).exists() else "missing"


def main() -> int:
    parser = argparse.ArgumentParser(description="Search ranked screenshot evidence.")
    parser.add_argument("terms", nargs="+", help="Search terms, e.g. 小柴胡汤 加减")
    parser.add_argument("-n", "--limit", type=int, default=8)
    parser.add_argument("--show-terms", action="store_true", help="Print normalized search terms.")
    args = parser.parse_args()

    entries = []
    for evidence in EVIDENCE_FILES:
        if evidence.exists():
            entries.extend(parse_entries(evidence.read_text(encoding="utf-8")))
    terms = normalize_terms(args.terms)
    if args.show_terms:
        print("检索词：" + " ".join(terms))
    print(SAFETY_NOTICE)
    ranked = []
    for entry in entries:
        score = score_entry(entry, terms)
        if score > 0:
            ranked.append((score, entry))
    ranked.sort(key=lambda item: (-item[0], item[1]["lesson"], item[1]["time"]))
    if not ranked:
        print("未找到匹配结果。")
        return 0

    for score, entry in ranked[: args.limit]:
        print(f"- {entry['lesson']} {entry['time']} [{entry['category']}] score={score} path={path_status(entry['path'])}")
        print(f"  {entry['desc']}")
        print(f"  截图路径：{entry['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
