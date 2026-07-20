from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Integral
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from .fusion import fuse_ranked_channels, merge_unique
from .faiss_artifacts import (
    MAX_MAPPING_FILE_BYTES,
    MAX_MAPPING_LINE_BYTES,
    MAX_MAPPING_RECORDS,
    resolve_faiss_artifacts,
)
from .normalization import lexical_query_terms, normalize_query_text


SENTENCE_RE = re.compile(r"[^。！？!?；;]+[。！？!?；;]?")
ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_+-]{2,}")
CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
TERM_SPLIT_RE = re.compile(r"[，,。！？!?；;、\s]+")
MEASURE_TERM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:克|钱|兩|两|分|升|斗|斤|铢)")
FORMULA_SUFFIXES = ("汤", "丸", "散", "饮", "膏", "丹")
FORMULA_MAX_CHARS = 8
FORMULA_MIN_CHARS = 2
FORMULA_PREFIX_NOISE = (
    "可以讨论",
    "可以用",
    "考虑",
    "所以",
    "这个",
    "记得",
    "同样是",
    "就用",
    "这就是",
    "就是",
    "讨论",
    "使用",
    "解表用",
    "攻痞用",
    "治疗用",
    "这时",
    "就是用",
    "那就是",
    "这时候",
    "和",
    "与",
    "及",
    "用",
    "的",
)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


FORMULA_SIGNAL_CHARS = set(
    "黄芩连桂枝麻葛根柴胡半夏生姜甘草芍药枣参附子茯苓白术干吴茱萸当归枳实栀豉杏仁牡蛎龙骨苇苓泽泻滑石石膏中气梅乌薯蓣肾"
)
FORMULA_NUMERAL_PREFIXES = tuple("一二三四五六七八九十百千万大小")
FORMULA_SIGNAL_REQUIRED_SUFFIXES = {"丸", "散", "饮", "膏", "丹"}
FORMULA_NON_FORMULA_ENDINGS = (
    "睾丸",
    "扩散",
    "去散",
    "消散",
    "分散",
    "发散",
    "吹散",
    "悬饮",
)
SIX_CHANNEL_TERMS = ("太阳", "阳明", "少阳", "太阴", "少阴", "厥阴")
SYMPTOM_TERMS = (
    "汗出",
    "有汗",
    "无汗",
    "恶风",
    "恶寒",
    "发热",
    "咽痛",
    "喘",
    "烦躁",
    "口渴",
    "下利",
    "便秘",
    "腹痛",
    "头痛",
    "身痛",
    "脉浮",
    "脉沉",
)
CAUTION_TERMS = ("不可", "不可以", "勿", "误", "禁忌", "忌")
QUERY_EXPANSION_STOP_TERMS = {
    "这个",
    "那个",
    "什么",
    "怎么",
    "多少",
    "现代",
    "古时",
    "古时候",
    "时候",
    "我们",
    "他们",
    "有人",
    "因为",
    "所以",
    "如果",
    "可以",
    "就是",
    "不是",
    "一样",
    "一个",
    "没有",
    "里面",
    "现在",
    "过去",
}
QUERY_REWRITE_BACKGROUND_TERMS = {
    "病人",
    "患者",
    "男性",
    "女性",
    "亚裔",
    "三天",
    "昨天",
    "上午",
    "下午",
    "开始",
    "感觉",
    "建议",
    "中药",
    "什么方",
    "摄氏度",
}
CLINICAL_REWRITE_TERMS = (
    "下利",
    "拉肚子",
    "腹泻",
    "黄臭",
    "黃臭",
    "恶心",
    "噁心",
    "干呕",
    "呕吐",
    "腹痛",
    "肠鸣",
    "心下痞",
    "食欲差",
    "胃口差",
    "发烧",
    "發燒",
    "退烧",
    "怕冷",
    "有汗",
    "无汗",
    "恶寒",
    "咳嗽",
    "白痰",
    "咽喉疼痛",
    "咽痛",
    "头痛",
    "肩颈酸痛",
)
CLINICAL_EVIDENCE_CLUE_TERMS = tuple(
    dict.fromkeys(
        [
            *SYMPTOM_TERMS,
            *CLINICAL_REWRITE_TERMS,
            "热利",
            "寒利",
            "表证",
            "里证",
            "方证",
            "心下",
            "心下痞满",
            "痞满",
            "腹满",
            "口苦",
            "口干",
            "便脓血",
            "肛门灼热",
            "食欲不振",
            "胃口不好",
            "项强",
        ]
    )
)
CLINICAL_CORE_EVIDENCE_CLUE_TERMS = (
    "下利",
    "黄臭",
    "热利",
    "寒利",
    "恶心",
    "干呕",
    "腹痛",
    "肠鸣",
    "心下",
    "心下痞",
    "心下痞满",
    "痞满",
    "腹满",
    "便脓血",
    "肛门灼热",
    "食欲差",
    "食欲不振",
    "里证",
)
KNOWLEDGE_EXTRACTOR_VERSION = "local_rules_v1"
FORMULA_DOSAGE_SAFETY_NOTICE = (
    "涉及剂量、方药或处方线索时必须谨慎：不同人的体质不同，病情阶段、兼证、年龄、基础病和用药史都不同；"
    "现代药材来源、炮制、浓度和药效也和以前差很多。建议去线下正规中医渠道面诊辨证，"
    "不要私自购药有风险。"
)
EMERGENCY_SAFETY_NOTICE = (
    "如果正在出现胸痛、呼吸困难、昏厥、意识改变、疑似中风、大出血或其他急重症象，"
    "请立即联系当地急救或前往急诊，不要等待课程资料检索结果。"
)
EMERGENCY_QUERY_TERMS = (
    "胸痛",
    "胸口痛",
    "心前区痛",
    "呼吸困难",
    "气短",
    "氣短",
    "喘不过气",
    "昏厥",
    "意识不清",
    "意识改变",
    "抽搐",
    "口角歪",
    "单侧无力",
    "單側無力",
    "大出血",
    "呕血",
    "便血",
    "严重脱水",
    "嚴重脫水",
    "中毒",
    "严重过敏",
    "嚴重過敏",
)
SOURCE_LOOKUP_MARKERS = ("出处", "哪本书", "哪一本书", "哪一页", "哪一段", "原文")
REFERENCE_MATERIAL_QUERY_MARKERS = (
    "参考书",
    "书单",
    "推荐书",
    "推荐过哪些书",
    "推荐了哪些书",
    "推荐哪些书",
    "哪几本书",
)
ANSWER_ANCHOR_EXCLUDED_TERMS = {
    *SOURCE_LOOKUP_MARKERS,
    "在哪里",
    "在哪裡",
    "在哪裏",
    "方证",
    "鉴别",
    "比较",
    "区别",
    "主之",
    "治法",
    "材料",
    "方法",
    "来源",
    "课程",
    "相关线索",
}
RELIABLE_SOURCE_NAMED_TERMS = ("太阳病欲解时", "木香饼", "一钱", "太阳病", "黄金比例")
DOMAIN_ENTITY_TERMS = (
    "合谷",
    "太冲",
    "四关",
    "胸痹",
    "太阳病欲解时",
    "欲解时",
    "欲解",
    "上品",
    "中品",
    "下品",
    "上中下三品",
    "春夏秋冬",
    "春夏",
    "秋冬",
    "伤寒论",
    "金匮要略",
    "黄帝内经",
    "神农本草经",
    "神农本草",
    "针灸",
    "天纪",
    "先天卦",
    "后天卦",
    "易经",
    "八卦",
    "紫微斗数",
    "阳宅",
    "学习主线",
    "学习路线",
    "系统复习",
    "复习顺序",
)
COURSE_SCOPE_TERMS = frozenset({"伤寒论", "金匮要略", "黄帝内经", "神农本草经", "神农本草", "针灸"})
TASK_ONLY_QUERY_TERMS = frozenset(
    {
        "合称",
        "学习主线",
        "学习路线",
        "系统复习",
        "复习顺序",
        "鉴别",
        "比较",
        "区别",
        "出处",
        "原文",
        "顺序",
    }
)
RAG_TIANJI_QUERY_TERMS = ("天纪", "先天卦", "后天卦", "紫微斗数", "阳宅", "风水")
RAG_LEARNING_ROUTE_TERMS = ("复习顺序", "系统复习", "怎么学")
KNOWN_FORMULA_ANCHORS = frozenset(
    {
        "桂枝汤",
        "麻黄汤",
        "四逆汤",
        "真武汤",
        "葛根汤",
        "小柴胡汤",
        "理中汤",
        "黄芩加半夏生姜汤",
        "黄芩汤",
        "半夏泻心汤",
        "生姜泻心汤",
        "甘草泻心汤",
        "葛根黄芩黄连汤",
        "白虎汤",
        "大承气汤",
        "小承气汤",
        "调胃承气汤",
        "小建中汤",
        "十枣汤",
        "大柴胡汤",
        "小青龙汤",
        "大青龙汤",
        "吴茱萸汤",
        "当归四逆汤",
        "苓桂术甘汤",
        "茵陈蒿汤",
        "越婢汤",
        "旋覆代赭汤",
        "麦门冬汤",
        "木防己汤",
        "百合知母汤",
        "五苓散",
        "肾气丸",
        "麻子仁丸",
        "乌头桂枝汤",
        "白虎加人参汤",
        "通脉四逆汤",
        "大陷胸汤",
        "小半夏汤",
    }
)
FORMULA_LEFT_QUERY_PREFIXES = ("请问", "关于", "查询", "和", "与", "、")
FORMULA_RIGHT_QUERY_SUFFIXES = (
    "的出处",
    "的方证",
    "的鉴别",
    "的比较",
    "的区别",
    "出处",
    "原文",
    "哪本书",
    "哪一页",
    "方证",
    "主治",
    "对应",
    "开什么方",
    "是什么方",
    "怎么理解",
    "如何理解",
    "如何",
    "鉴别",
    "比较",
    "区别",
    "和",
    "与",
    "、",
)
EXPLICIT_FORMULA_RIGHT_QUERY_SUFFIXES = (
    *FORMULA_RIGHT_QUERY_SUFFIXES,
    "是什么方",
    "开什么方",
    "如何理解",
    "怎么理解",
    "见于哪里",
)
EXPLICIT_FORMULA_NARRATIVE_PREFIXES = (
    "可能出现",
    "因为",
    "可能",
    "提到",
    "患者",
    "病人",
    "关于",
    "查询",
    "请问",
    "喝",
    "吃",
    "有",
)
EXPLICIT_FORMULA_FOOD_TERMS = frozenset(
    {"鸡", "排骨", "鱼", "菜", "饭", "粥", "酸辣", "火锅", "羊肉", "牛肉", "猪肉", "海鲜"}
)
MAX_RUNTIME_META_VALUE_CHARS = 4096
MAX_PUBLIC_ANSWER_LIMIT = 100
MAX_INTERNAL_SEARCH_LIMIT = 400
MAX_VECTOR_UNIT_LIMIT = 400
MAX_SQLITE_IN_ITEMS = 900
MAX_RUNTIME_MANIFEST_BYTES = 2_000_000
MAX_REFERENCE_LINK_EVIDENCE = 200
MAX_LINKED_REFERENCE_MATERIALS = 12
MAX_EVIDENCE_CONTEXT_TEXT_CHARS = 2_400
MAX_EVIDENCE_CONTEXT_RESULTS = 100
REFERENCE_RELATION_LABELS = {
    "recommended_title_match_unverified_edition": "课程推荐书目（具体版本未核实）",
    "course_cited_reference": "课程引用资料",
    "course_used_reference": "课程使用资料",
    "user_supplied_related": "用户提供的关联资料",
}
REFERENCE_EDITION_LABELS = {
    "unverified": "版本未核实",
    "authenticity_disputed_and_edition_unverified": "真伪存在争议，具体版本未核实",
}
NAMED_RIGHT_QUERY_SUFFIXES = (
    *FORMULA_RIGHT_QUERY_SUFFIXES,
    "的原文",
    "热熨法",
    "是",
    "多少",
    "几克",
    "换算",
)
QUERY_BOUNDARY_CHARS = frozenset("，,。！？!?；;、：:（）()【】[]「」『』《》〈〉/\\|\t\r\n ")
FORMULA_PRODUCT_CONTINUATIONS = ("圆", "锅", "装", "子", "产品", "包装")
NAMED_EVIDENCE_INVALID_CONTINUATIONS = {
    "木香饼": ("干",),
    "太阳病": ("人",),
    "一钱": ("包",),
}


def validate_runtime_limit(value: object, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    if value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return value


@dataclass(frozen=True)
class ParsedParagraph:
    paragraph_id: str
    doc_id: str
    source_path: str
    title: str
    page_start: int
    page_end: int
    text: str


@dataclass(frozen=True)
class RetrievalUnit:
    unit_id: str
    paragraph_id: str
    doc_id: str
    unit_type: str
    text: str
    text_for_embedding: str
    sentence_start: int
    sentence_end: int
    weight: float


@dataclass(frozen=True)
class KnowledgeUnit:
    knowledge_unit_id: str
    paragraph_id: str
    doc_id: str
    source_path: str
    title: str
    page_start: int
    page_end: int
    unit_type: str
    subject: str
    predicate: str
    object: str
    attributes_json: str
    evidence_quote: str
    confidence: float
    extractor_version: str = KNOWLEDGE_EXTRACTOR_VERSION


@dataclass(frozen=True)
class GuideNode:
    node_id: str
    parent_id: str
    node_type: str
    label: str
    badge: str
    path: str
    content: str
    search_text: str
    paragraph_id: str = ""
    source_path: str = ""
    title: str = ""
    page_start: int = 0
    page_end: int = 0
    evidence_quote: str = ""


GUIDE_UNIT_STYLE = {
    "formula_pattern": ("formula", "方证"),
    "symptom": ("concept", "症状"),
    "dosage": ("concept", "剂量"),
    "method": ("concept", "方法"),
    "comparison": ("concept", "鉴别"),
    "caution": ("concept", "注意"),
}


def guide_style_for_unit(unit_type: str) -> tuple[str, str]:
    return GUIDE_UNIT_STYLE.get(unit_type, ("concept", "知识点"))


def has_repeated_ocr_phrase(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(re.search(r"([\u4e00-\u9fff]{2,8})\1{2,}", compact))


def has_guide_source_noise(text: str) -> bool:
    normalized = normalize_whitespace(text)
    if re.search(r"[.．·]{6,}", normalized):
        return True
    if normalized.count("...") >= 2:
        return True
    if has_repeated_ocr_phrase(normalized):
        return True
    return False


def retrieval_noise_penalty(title: str, text: str) -> float:
    """Down-rank navigation/boilerplate fragments without mutating the source DB."""
    normalized = normalize_whitespace(text)
    penalty = 0.0
    if len(normalized) < 24:
        penalty += 0.35
    if has_guide_source_noise(normalized):
        penalty += 0.65
    if "目录" in title or normalized.startswith("目录"):
        penalty += 0.55
    if re.search(r"(?:版权所有|本书编委会|出版社|图书在版编目)", normalized[:240]):
        penalty += 0.55
    return min(penalty, 1.35)


def overview_structure_bonus(query: str, text: str) -> float:
    normalized_query = normalize_query_text(query)
    if not any(marker in normalized_query for marker in ("学习主线", "学习路线", "课程概览")):
        return 0.0
    normalized_text = normalize_query_text(text)
    bonus = 0.0
    if "病脉证并治" in normalized_text:
        bonus += 0.55
    if re.search(r"第[一二三四五六七八九十\d]+篇", normalized_text):
        bonus += 0.6
    if any(marker in normalized_text for marker in ("第一条", "接下来看", "这一篇")):
        bonus += 0.35
    return bonus


def clean_guide_evidence_text(text: str) -> str:
    cleaned = normalize_whitespace(text)
    cleaned = re.sub(r"^微信公众号[:：].*?道法自然\d*", "", cleaned)
    cleaned = re.sub(r"^微信公众号[:：][^。！？；\n]{0,120}\d*", "", cleaned)
    cleaned = re.sub(r"^\d{1,4}(?=[\u4e00-\u9fff])", "", cleaned)
    return cleaned.strip()


def public_source_path(source_path: object) -> str:
    """Return a deterministic source path suitable for public JSON and citations."""
    raw = str(source_path).strip()
    if not raw:
        return ""

    def decode_path(value: str) -> str | None:
        if len(value) > 8192:
            return None
        decoded = value
        for _ in range(8):
            next_value = unquote(decoded, errors="replace")
            if len(next_value) > 8192:
                return None
            if next_value == decoded:
                return decoded
            decoded = next_value
        if re.search(r"%[0-9A-Fa-f]{2}", decoded):
            return None
        return decoded

    def safe_basename(value: str) -> str:
        cleaned = re.split(r"[?#]", value, maxsplit=1)[0]
        cleaned = cleaned.replace("/", "_").replace("\\", "_")
        cleaned = "".join(
            character
            for character in cleaned
            if not unicodedata.category(character).startswith("C")
        )
        cleaned = cleaned.strip().lstrip("._ ")
        return cleaned if cleaned not in {"", ".", ".."} else "source.pdf"

    decoded_raw = decode_path(raw)
    if decoded_raw is None:
        return "pdfs/source.pdf"
    introduced_separator = decoded_raw.count("/") > raw.count("/") or decoded_raw.count(
        "\\"
    ) > raw.count("\\")

    windows_drive = bool(re.match(r"^[A-Za-z]:", decoded_raw))
    uri_scheme = bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", decoded_raw))
    if uri_scheme and not windows_drive:
        try:
            uri_path = decode_path(urlsplit(decoded_raw).path)
        except (UnicodeError, ValueError):
            return "pdfs/source.pdf"
        if uri_path is None:
            return "pdfs/source.pdf"
        parsed_path = re.sub(r"/{2,}", "/", uri_path.replace("\\", "/"))
        uri_basename = (
            parsed_path.rsplit("/", 1)[-1] if parsed_path and not parsed_path.endswith("/") else ""
        )
        return f"pdfs/{safe_basename(uri_basename)}"

    slash_normalized = decoded_raw.replace("\\", "/")
    normalized = re.sub(r"/{2,}", "/", slash_normalized)
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    basename = safe_basename(parts[-1] if parts else "")
    is_absolute = slash_normalized.startswith("/") or windows_drive
    is_unsafe_relative = introduced_separator
    normalized_parts: list[str] = []
    for index, part in enumerate(parts):
        normalized_part = part.strip()
        has_control = any(
            unicodedata.category(character).startswith("C") for character in normalized_part
        )
        decoded_scheme_prefix = index == 0 and bool(
            re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", normalized_part)
        )
        if (
            not normalized_part
            or normalized_part in {".", "..", "~"}
            or normalized_part.startswith("~")
            or "?" in normalized_part
            or "#" in normalized_part
            or has_control
            or decoded_scheme_prefix
        ):
            is_unsafe_relative = True
        normalized_parts.append(normalized_part)
    if is_absolute or is_unsafe_relative:
        return f"pdfs/{basename}"
    return "/".join([*normalized_parts[:-1], basename])


def is_guide_source_text(text: str) -> bool:
    normalized = normalize_whitespace(text)
    if len(normalized) < 12:
        return False
    if has_guide_source_noise(normalized):
        return False
    return True


def load_dotenv_if_present(start: Path | None = None) -> None:
    search_start = (start or Path.cwd()).resolve()
    candidates = [search_start, *search_start.parents]
    module_root = Path(__file__).resolve().parents[1]
    if module_root not in candidates:
        candidates.append(module_root)
    for directory in candidates:
        env_path = directory / ".env"
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return


def stable_id(*parts: object, length: int = 16) -> str:
    raw = "\n".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def clean_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", "", text.strip())
    if not normalized:
        return []
    sentences = [match.group(0).strip() for match in SENTENCE_RE.finditer(normalized)]
    return [sentence for sentence in sentences if sentence]


def split_long_text_to_paragraphs(
    text: str, max_chars: int = 900, min_chars: int = 120
) -> list[str]:
    sentences = split_sentences(text)
    if not sentences:
        return []
    paragraphs: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        sentence_len = len(sentence)
        if current and current_len + sentence_len > max_chars:
            paragraphs.append("".join(current))
            current = [sentence]
            current_len = sentence_len
        else:
            current.append(sentence)
            current_len += sentence_len
        if current_len >= min_chars and sentence.endswith(("。", "！", "？", "!", "?")):
            continue
    if current:
        paragraphs.append("".join(current))
    return paragraphs


def dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def clean_formula_candidate(candidate: str) -> str:
    cleaned = candidate.strip(" \t\r\n'\"`「」『』《》〈〉“”‘’（）()[]【】：:，,。；;、")
    changed = True
    while changed:
        changed = False
        for prefix in sorted(FORMULA_PREFIX_NOISE, key=len, reverse=True):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip(
                    " \t\r\n'\"`「」『』《》〈〉“”‘’（）()[]【】：:，,。；;、"
                )
                changed = True
        for marker in ("用", "宜"):
            marker_offset = cleaned.rfind(marker)
            if marker_offset > 0:
                cleaned = cleaned[marker_offset + len(marker) :].strip(
                    " \t\r\n'\"`「」『』《》〈〉“”‘’（）()[]【】：:，,。；;、"
                )
                changed = True
    return cleaned


def is_probable_formula_term(candidate: str, suffix: str) -> bool:
    if not (FORMULA_MIN_CHARS <= len(candidate) <= FORMULA_MAX_CHARS):
        return False
    if not candidate.endswith(suffix):
        return False
    if not re.fullmatch(r"[\u4e00-\u9fff]+", candidate):
        return False
    if any(connector in candidate[1:-1] for connector in ("和", "与", "及")):
        return False
    if any(candidate.endswith(ending) for ending in FORMULA_NON_FORMULA_ENDINGS):
        return False
    if suffix in FORMULA_SIGNAL_REQUIRED_SUFFIXES:
        has_signal = bool(set(candidate) & FORMULA_SIGNAL_CHARS)
        has_numeral_prefix = candidate.startswith(FORMULA_NUMERAL_PREFIXES)
        if not has_signal and not has_numeral_prefix:
            return False
    return True


def extract_formula_terms(text: str) -> list[str]:
    formulas: list[str] = []
    for fragment in TERM_SPLIT_RE.split(text):
        fragment = fragment.strip()
        if not fragment:
            continue
        for suffix in FORMULA_SUFFIXES:
            offset = fragment.find(suffix)
            while offset >= 0:
                end = offset + len(suffix)
                max_len = min(FORMULA_MAX_CHARS + 2, end)
                for length in range(max_len, FORMULA_MIN_CHARS - 1, -1):
                    candidate = clean_formula_candidate(fragment[end - length : end])
                    if is_probable_formula_term(candidate, suffix):
                        formulas.append(candidate)
                        break
                offset = fragment.find(suffix, offset + len(suffix))
    return dedupe_keep_order(formulas)


def extract_known_terms(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if term in text]


def query_domain_terms(query: str) -> list[str]:
    normalized = normalize_query_text(query)
    fixed_terms = (
        "一钱",
        "黄金比例",
        "木香饼",
        "热熨",
        "主之",
        "方证",
        "鉴别",
        "出处",
        "太阳病",
        "欲解",
        "合称",
        *DOMAIN_ENTITY_TERMS,
        *SYMPTOM_TERMS,
        *SIX_CHANNEL_TERMS,
    )
    terms = extract_formula_terms(normalized)
    terms.extend(term for term in fixed_terms if term in normalized)
    if "合称" in normalized and "合谷" in normalized and "太冲" in normalized:
        terms.append("四关")
    return dedupe_keep_order(terms)


def text_search_terms(query: str) -> list[str]:
    terms = lexical_query_terms(query, domain_terms=query_domain_terms(query))
    normalized = normalize_query_text(query)
    if "合称" in normalized and "合谷" in normalized and "太冲" in normalized:
        terms.append("四关")
    if "上中下三品" in normalized:
        terms.extend(["上品", "中品", "下品"])
    return dedupe_keep_order(terms)


def query_core_entity_terms(query: str) -> list[str]:
    """Return literal domain entities that retrieved正文 must actually support."""
    normalized = normalize_query_text(query)
    terms = [
        *reliable_formula_anchors(normalized),
        *explicit_query_formula_terms(normalized),
        *direct_present_terms(normalized, DOMAIN_ENTITY_TERMS),
        *direct_present_terms(normalized, SYMPTOM_TERMS),
    ]
    terms = [term for term in dedupe_keep_order(terms) if term not in TASK_ONLY_QUERY_TERMS]
    if "上中下三品" in normalized:
        terms = [term for term in terms if term != "上中下三品"]
        terms.extend(["上品", "中品", "下品"])
    substantive = [term for term in terms if term not in COURSE_SCOPE_TERMS]
    return (substantive or terms)[:12]


def exact_query_phrases(query: str) -> list[str]:
    anchors = reliable_source_anchors(query)
    if anchors:
        return anchors
    return [term for term in query_core_entity_terms(query) if len(term) >= 3][:6]


def query_requires_all_core_terms(query: str, intent: str) -> bool:
    core_terms = set(query_core_entity_terms(query))
    return (
        intent == "comparison"
        or "合称" in normalize_query_text(query)
        or {"上品", "中品", "下品"} <= core_terms
        or {"有汗", "无汗"} <= core_terms
    )


def knowledge_search_terms(query: str) -> list[str]:
    terms = text_search_terms(query)
    normalized = normalize_query_text(query)
    terms.extend(term for term in ("禁忌", "误用", "比较", "区别") if term in normalized)
    return dedupe_keep_order(terms)


def fts5_quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def fts5_query_from_terms(terms: Iterable[str]) -> str:
    fts_terms = [fts5_quote(term) for term in terms if len(term) >= 3]
    return " OR ".join(fts_terms)


def generate_paragraph_questions(paragraph: ParsedParagraph, max_questions: int = 12) -> list[str]:
    text = paragraph.text
    formulas = extract_formula_terms(text)
    channels = extract_known_terms(text, SIX_CHANNEL_TERMS)
    symptoms = extract_known_terms(text, SYMPTOM_TERMS)
    questions: list[str] = []

    for formula in formulas:
        questions.append(f"{formula}对应什么方证或症状？")
        questions.append(f"什么时候会提到{formula}？")

    if len(formulas) >= 2:
        questions.append(f"{formulas[0]}和{formulas[1]}如何鉴别？")

    for channel in channels:
        questions.append(f"{channel}相关的辨证要点是什么？")

    for symptom in symptoms:
        questions.append(f"{symptom}相关的辨证要点是什么？")

    if "主之" in text:
        questions.append("这段提到什么情况下可以对应某个方证？")
    if "不可" in text or "误" in text:
        questions.append("这段有哪些禁忌、误用或需要避免的情况？")
    if "区别" in text or "鉴别" in text or "比较" in text:
        questions.append("这段在比较或鉴别哪些证候、方剂或症状？")

    if not questions and text:
        questions.append(f"{paragraph.title}这一段主要讲什么？")

    return dedupe_keep_order(questions)[:max_questions]


def build_retrieval_units(
    paragraphs: Iterable[ParsedParagraph],
    window_size: int = 6,
    overlap: int = 2,
) -> list[RetrievalUnit]:
    if window_size < 1:
        raise ValueError("window_size must be >= 1")
    if overlap < 0 or overlap >= window_size:
        raise ValueError("overlap must be >= 0 and < window_size")

    units: list[RetrievalUnit] = []
    stride = max(1, window_size - overlap)
    for paragraph in paragraphs:
        sentences = split_sentences(paragraph.text)
        prefix = "\n".join(
            part
            for part in [
                f"标题：{paragraph.title}" if paragraph.title else "",
                f"页码：{paragraph.page_start}-{paragraph.page_end}",
            ]
            if part
        )

        for index, sentence in enumerate(sentences):
            unit_text = sentence
            text_for_embedding = f"{prefix}\n正文：{unit_text}" if prefix else unit_text
            unit_id = stable_id(paragraph.paragraph_id, "sentence", index)
            units.append(
                RetrievalUnit(
                    unit_id=unit_id,
                    paragraph_id=paragraph.paragraph_id,
                    doc_id=paragraph.doc_id,
                    unit_type="sentence",
                    text=unit_text,
                    text_for_embedding=text_for_embedding,
                    sentence_start=index,
                    sentence_end=index,
                    weight=1.0,
                )
            )

        for start in range(0, len(sentences), stride):
            window_sentences = sentences[start : start + window_size]
            if not window_sentences:
                continue
            if start > 0 and len(window_sentences) < max(2, window_size // 2):
                continue
            unit_text = "".join(window_sentences)
            text_for_embedding = f"{prefix}\n正文：{unit_text}" if prefix else unit_text
            unit_id = stable_id(
                paragraph.paragraph_id, "window", start, start + len(window_sentences) - 1
            )
            units.append(
                RetrievalUnit(
                    unit_id=unit_id,
                    paragraph_id=paragraph.paragraph_id,
                    doc_id=paragraph.doc_id,
                    unit_type="window",
                    text=unit_text,
                    text_for_embedding=text_for_embedding,
                    sentence_start=start,
                    sentence_end=start + len(window_sentences) - 1,
                    weight=1.1,
                )
            )

        if paragraph.text:
            text_for_embedding = f"{prefix}\n正文：{paragraph.text}" if prefix else paragraph.text
            units.append(
                RetrievalUnit(
                    unit_id=stable_id(paragraph.paragraph_id, "paragraph"),
                    paragraph_id=paragraph.paragraph_id,
                    doc_id=paragraph.doc_id,
                    unit_type="paragraph",
                    text=paragraph.text,
                    text_for_embedding=text_for_embedding,
                    sentence_start=0,
                    sentence_end=max(0, len(sentences) - 1),
                    weight=0.9,
                )
            )

        for index, question in enumerate(generate_paragraph_questions(paragraph)):
            text_for_embedding = f"{prefix}\n问题：{question}" if prefix else f"问题：{question}"
            units.append(
                RetrievalUnit(
                    unit_id=stable_id(paragraph.paragraph_id, "question", index, question),
                    paragraph_id=paragraph.paragraph_id,
                    doc_id=paragraph.doc_id,
                    unit_type="question",
                    text=question,
                    text_for_embedding=text_for_embedding,
                    sentence_start=0,
                    sentence_end=max(0, len(sentences) - 1),
                    weight=1.15,
                )
            )
    return units


def build_question_retrieval_units(paragraphs: Iterable[ParsedParagraph]) -> list[RetrievalUnit]:
    units: list[RetrievalUnit] = []
    for paragraph in paragraphs:
        sentences = split_sentences(paragraph.text)
        prefix = "\n".join(
            part
            for part in [
                f"标题：{paragraph.title}" if paragraph.title else "",
                f"页码：{paragraph.page_start}-{paragraph.page_end}",
            ]
            if part
        )
        for index, question in enumerate(generate_paragraph_questions(paragraph)):
            text_for_embedding = f"{prefix}\n问题：{question}" if prefix else f"问题：{question}"
            units.append(
                RetrievalUnit(
                    unit_id=stable_id(paragraph.paragraph_id, "question", index, question),
                    paragraph_id=paragraph.paragraph_id,
                    doc_id=paragraph.doc_id,
                    unit_type="question",
                    text=question,
                    text_for_embedding=text_for_embedding,
                    sentence_start=0,
                    sentence_end=max(0, len(sentences) - 1),
                    weight=1.15,
                )
            )
    return units


def evidence_quote(text: str, max_chars: int = 240) -> str:
    normalized = re.sub(r"\s+", "", text.strip())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1] + "…"


def json_attributes(**values: object) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def make_knowledge_unit(
    paragraph: ParsedParagraph,
    unit_type: str,
    subject: str,
    predicate: str,
    object_text: str,
    evidence: str,
    confidence: float,
    **attributes: object,
) -> KnowledgeUnit:
    return KnowledgeUnit(
        knowledge_unit_id=stable_id(
            paragraph.paragraph_id,
            unit_type,
            subject,
            predicate,
            object_text,
            evidence_quote(evidence, max_chars=120),
        ),
        paragraph_id=paragraph.paragraph_id,
        doc_id=paragraph.doc_id,
        source_path=paragraph.source_path,
        title=paragraph.title,
        page_start=paragraph.page_start,
        page_end=paragraph.page_end,
        unit_type=unit_type,
        subject=subject,
        predicate=predicate,
        object=object_text,
        attributes_json=json_attributes(**attributes),
        evidence_quote=evidence_quote(evidence),
        confidence=confidence,
    )


def extract_knowledge_units_from_paragraph(paragraph: ParsedParagraph) -> list[KnowledgeUnit]:
    text = paragraph.text
    sentences = split_sentences(text) or [text]
    units: list[KnowledgeUnit] = []

    if ("一钱" in text or "1钱" in text) and ("克" in text or "黄金比例" in text or "比例" in text):
        dosage_evidence = next(
            (sentence for sentence in sentences if "一钱" in sentence or "1钱" in sentence),
            text,
        )
        dosage_context_markers = (
            "一钱是",
            "一钱等于",
            "一钱约",
            "一钱当",
            "一钱算",
            "一钱的量",
            "一钱，",
            "一钱 ",
        )
        if "一钱匕" in dosage_evidence and not any(
            marker in dosage_evidence for marker in dosage_context_markers
        ):
            dosage_evidence = ""
        local_text = dosage_evidence
        if local_text and len(re.findall(r"\d+(?:\.\d+)?\s*克", local_text)) > 8:
            offset = local_text.find("一钱")
            if offset < 0:
                offset = local_text.find("1钱")
            local_text = local_text[max(0, offset - 80) : offset + 120]
        grams = dedupe_keep_order(re.findall(r"\d+(?:\.\d+)?\s*克", local_text))
        object_parts = grams[:]
        if "黄金比例" in local_text:
            object_parts.append("首重黄金比例")
        elif "比例" in local_text:
            object_parts.append("首重比例")
        if object_parts:
            units.append(
                make_knowledge_unit(
                    paragraph,
                    unit_type="dosage",
                    subject="一钱",
                    predicate="换算与剂量原则",
                    object_text="；".join(object_parts),
                    evidence=local_text,
                    confidence=0.86,
                    grams=grams,
                )
            )

    if "木香饼" in text and "热熨" in text:
        method_sentence = next(
            (sentence for sentence in sentences if "木香饼" in sentence or "热熨" in sentence),
            text,
        )
        materials = [term for term in ("木香", "生地") if term in method_sentence]
        indications = []
        if "治" in method_sentence:
            indications.append(method_sentence.split("治", 1)[1].rstrip("。；;"))
        units.append(
            make_knowledge_unit(
                paragraph,
                unit_type="method",
                subject="木香饼热熨法",
                predicate="治法",
                object_text=evidence_quote(method_sentence, max_chars=120),
                evidence=method_sentence,
                confidence=0.9,
                materials=materials,
                indications=indications,
            )
        )

    for sentence in sentences:
        if "主之" in sentence:
            for formula in extract_formula_terms(sentence):
                units.append(
                    make_knowledge_unit(
                        paragraph,
                        unit_type="formula_pattern",
                        subject=formula,
                        predicate="方证",
                        object_text=evidence_quote(sentence, max_chars=120),
                        evidence=sentence,
                        confidence=0.82,
                    )
                )

        if any(term in sentence for term in CAUTION_TERMS):
            units.append(
                make_knowledge_unit(
                    paragraph,
                    unit_type="caution",
                    subject="禁忌或误用",
                    predicate="提示",
                    object_text=evidence_quote(sentence, max_chars=120),
                    evidence=sentence,
                    confidence=0.72,
                    matched_terms=[term for term in CAUTION_TERMS if term in sentence],
                )
            )

        sentence_symptoms = extract_known_terms(sentence, SYMPTOM_TERMS)
        for symptom in sentence_symptoms[:4]:
            units.append(
                make_knowledge_unit(
                    paragraph,
                    unit_type="symptom",
                    subject=symptom,
                    predicate="相关原文",
                    object_text=evidence_quote(sentence, max_chars=120),
                    evidence=sentence,
                    confidence=0.68,
                )
            )

        formulas = extract_formula_terms(sentence)
        if len(formulas) >= 2 and (
            "鉴别" in sentence or "区别" in sentence or "比较" in sentence or "和" in sentence
        ):
            units.append(
                make_knowledge_unit(
                    paragraph,
                    unit_type="comparison",
                    subject=" vs ".join(formulas[:3]),
                    predicate="鉴别比较",
                    object_text=evidence_quote(sentence, max_chars=120),
                    evidence=sentence,
                    confidence=0.76,
                    formulas=formulas,
                )
            )

    unique: dict[str, KnowledgeUnit] = {}
    for unit in units:
        unique[unit.knowledge_unit_id] = unit
    return list(unique.values())


def build_knowledge_units(paragraphs: Iterable[ParsedParagraph]) -> list[KnowledgeUnit]:
    units: list[KnowledgeUnit] = []
    for paragraph in paragraphs:
        units.extend(extract_knowledge_units_from_paragraph(paragraph))
    return units


def sparse_hash_embedding(text: str, dims: int = 2048) -> dict[int, float]:
    tokens = embedding_tokens(text)
    if not tokens:
        return {}
    counts: dict[int, float] = {}
    for token in tokens:
        bucket = int(hashlib.blake2b(token.encode("utf-8"), digest_size=8).hexdigest(), 16) % dims
        counts[bucket] = counts.get(bucket, 0.0) + 1.0
    norm = math.sqrt(sum(value * value for value in counts.values()))
    if norm == 0:
        return {}
    return {key: value / norm for key, value in counts.items()}


def embedding_tokens(text: str) -> list[str]:
    lowered = text.lower()
    tokens = ASCII_WORD_RE.findall(lowered)
    chinese_chars = CHINESE_CHAR_RE.findall(lowered)
    tokens.extend(chinese_chars)
    tokens.extend("".join(chinese_chars[i : i + 2]) for i in range(max(0, len(chinese_chars) - 1)))
    tokens.extend("".join(chinese_chars[i : i + 3]) for i in range(max(0, len(chinese_chars) - 2)))
    return [token for token in tokens if token.strip()]


class SparseHashEmbeddingBackend:
    name = "sparse_hash_char_ngrams_v1"
    vector_kind = "sparse"

    def __init__(self, dims: int = 2048) -> None:
        self.dims = dims

    def embed_texts(self, texts: list[str]) -> list[dict[int, float]]:
        return [sparse_hash_embedding(text, dims=self.dims) for text in texts]


class DenseEmbeddingBackend:
    name = "dense"
    vector_kind = "dense"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class LocalBgeM3EmbeddingBackend(DenseEmbeddingBackend):
    """Local BAAI/bge-m3 dense embedding backend.

    The model is loaded lazily so text/knowledge-only workflows do not need
    torch/transformers installed.
    """

    def __init__(
        self,
        model: str = "BAAI/bge-m3",
        batch_size: int = 12,
        max_length: int = 8192,
        use_fp16: bool | None = None,
        model_instance: object | None = None,
        model_loader: object | None = None,
    ) -> None:
        self.model = model
        self.batch_size = batch_size
        self.max_length = max_length
        self.use_fp16 = (
            os.getenv("LOCAL_BGE_M3_USE_FP16", "false").lower() in {"1", "true", "yes", "on"}
            if use_fp16 is None
            else use_fp16
        )
        self.model_instance = model_instance
        self.model_loader = model_loader
        self.name = f"local-bge-m3:{model}"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            encoded = self._encode_batch(model, batch)
            vectors.extend(normalize_dense_vector(vector) for vector in encoded)
        return vectors

    def _get_model(self) -> object:
        if self.model_instance is not None:
            return self.model_instance
        if self.model_loader is not None:
            self.model_instance = self.model_loader(self.model)
            return self.model_instance
        try:
            from FlagEmbedding import BGEM3FlagModel

            self.model_instance = BGEM3FlagModel(self.model, use_fp16=self.use_fp16)
            return self.model_instance
        except ImportError:
            try:
                from sentence_transformers import SentenceTransformer

                self.model_instance = SentenceTransformer(self.model)
                return self.model_instance
            except ImportError as sentence_error:
                raise RuntimeError(
                    "Local bge-m3 embeddings require optional local dependencies. "
                    'Install with `pip install ".[local]"` or `pip install FlagEmbedding`.'
                ) from sentence_error
            except Exception as sentence_error:
                raise RuntimeError(
                    f"failed to load local embedding model {self.model}: {sentence_error}"
                ) from sentence_error
        except Exception as flag_error:
            raise RuntimeError(
                f"failed to load local embedding model {self.model}: {flag_error}"
            ) from flag_error

    def _encode_batch(self, model: object, batch: list[str]) -> list[list[float]]:
        try:
            encoded = model.encode(
                batch,
                batch_size=self.batch_size,
                max_length=self.max_length,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
        except TypeError:
            encoded = model.encode(
                batch,
                batch_size=self.batch_size,
                normalize_embeddings=True,
            )

        if isinstance(encoded, dict):
            raw_vectors = encoded.get("dense_vecs")
            if raw_vectors is None:
                raw_vectors = encoded.get("dense")
        else:
            raw_vectors = encoded
        if raw_vectors is None:
            raise RuntimeError("local bge-m3 model did not return dense vectors")
        if hasattr(raw_vectors, "tolist"):
            raw_vectors = raw_vectors.tolist()
        return [[float(value) for value in vector] for vector in raw_vectors]


class SiliconFlowEmbeddingBackend(DenseEmbeddingBackend):
    name = "siliconflow:BAAI/bge-m3"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "BAAI/bge-m3",
        base_url: str = "https://api.siliconflow.cn/v1",
        batch_size: int = 32,
        timeout: int = 120,
        max_retries: int = 3,
        session: object | None = None,
    ) -> None:
        load_dotenv_if_present()
        self.api_key = api_key or os.getenv("SILICONFLOW_API_KEY", "")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.batch_size = batch_size
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session
        self.name = f"siliconflow:{model}"
        if not self.api_key:
            raise RuntimeError("SILICONFLOW_API_KEY is required for SiliconFlow embeddings")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        session = self.session
        if session is None:
            import requests

            session = requests.Session()

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors.extend(self._post_batch(session, batch))
        return vectors

    def _post_batch(self, session: object, batch: list[str]) -> list[list[float]]:
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": batch,
            "encoding_format": "float",
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = session.post(url, headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()["data"]
                data = sorted(data, key=lambda item: item.get("index", 0))
                return [item["embedding"] for item in data]
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= self.max_retries:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"SiliconFlow embedding request failed: {last_error}") from last_error


def write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def write_build_traces(
    trace_dir: Path,
    pdf_dir: Path,
    out_dir: Path,
    embedding_name: str,
    vector_kind: str,
    window_size: int,
    overlap: int,
    unit_types: set[str],
    paragraphs: list[ParsedParagraph],
    units: list[RetrievalUnit],
    document_events: list[dict[str, object]],
) -> dict[str, int | str]:
    trace_dir = trace_dir.expanduser().resolve()
    trace_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pdf_dir": str(pdf_dir),
        "out_dir": str(out_dir),
        "embedding": embedding_name,
        "vector_kind": vector_kind,
        "window_size": window_size,
        "overlap": overlap,
        "unit_types": sorted(unit_types),
        "paragraphs": len(paragraphs),
        "retrieval_units": len(units),
        "documents": len(document_events),
        "secret_policy": "API keys and Authorization headers are not written to traces.",
    }
    (trace_dir / "build_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paragraph_rows = (
        {
            "paragraph_id": paragraph.paragraph_id,
            "doc_id": paragraph.doc_id,
            "source_path": paragraph.source_path,
            "title": paragraph.title,
            "page_start": paragraph.page_start,
            "page_end": paragraph.page_end,
            "text": paragraph.text,
        }
        for paragraph in paragraphs
    )
    unit_rows = (
        {
            "unit_id": unit.unit_id,
            "paragraph_id": unit.paragraph_id,
            "doc_id": unit.doc_id,
            "unit_type": unit.unit_type,
            "text": unit.text,
            "text_for_embedding": unit.text_for_embedding,
            "sentence_start": unit.sentence_start,
            "sentence_end": unit.sentence_end,
            "weight": unit.weight,
        }
        for unit in units
    )
    event_rows = (
        {
            "event": "document_processed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        for event in document_events
    )
    paragraph_count = write_jsonl(trace_dir / "paragraphs.jsonl", paragraph_rows)
    unit_count = write_jsonl(trace_dir / "retrieval_units.jsonl", unit_rows)
    event_count = write_jsonl(trace_dir / "build_events.jsonl", event_rows)
    return {
        "trace_dir": str(trace_dir),
        "trace_paragraphs": paragraph_count,
        "trace_retrieval_units": unit_count,
        "trace_events": event_count,
    }


def sparse_dot(left: dict[int, float], right: dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(key, 0.0) for key, value in left.items())


def pack_sparse_vector(vector: dict[int, float]) -> bytes:
    payload = bytearray()
    for key, value in sorted(vector.items()):
        payload.extend(struct.pack("<Hf", int(key), float(value)))
    return bytes(payload)


def unpack_sparse_vector(blob: bytes) -> dict[int, float]:
    if len(blob) % 6 != 0:
        raise ValueError("invalid sparse vector blob length")
    vector: dict[int, float] = {}
    for offset in range(0, len(blob), 6):
        key, value = struct.unpack("<Hf", blob[offset : offset + 6])
        vector[int(key)] = float(value)
    return vector


def normalize_dense_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm == 0:
        return [0.0 for _ in vector]
    return [float(value) / norm for value in vector]


def dense_dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def pack_dense_vector(vector: list[float]) -> bytes:
    normalized = normalize_dense_vector(vector)
    return struct.pack(f"<{len(normalized)}f", *normalized)


def unpack_dense_vector(blob: bytes) -> list[float]:
    if len(blob) % 4 != 0:
        raise ValueError("invalid dense vector blob length")
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def default_faiss_index_path(db_path: Path) -> Path:
    return db_path.with_name("vectors.faiss")


def default_faiss_ids_path(db_path: Path) -> Path:
    return db_path.with_name("vector_ids.jsonl")


def load_faiss_module() -> object | None:
    try:
        import faiss

        return faiss
    except ImportError:
        return None


def faiss_matrix(rows: list[list[float]]) -> object:
    try:
        import numpy as np

        return np.asarray(rows, dtype="float32")
    except ImportError:
        return rows


def read_faiss_unit_ids(ids_path: Path) -> list[str]:
    try:
        if ids_path.stat().st_size > MAX_MAPPING_FILE_BYTES:
            raise ValueError("FAISS ID mapping exceeds safety limit")
        unit_ids: list[str] = []
        processed_bytes = 0
        with ids_path.open("rb") as mapping_file:
            while True:
                raw_line = mapping_file.readline(MAX_MAPPING_LINE_BYTES + 1)
                if not raw_line:
                    break
                processed_bytes += len(raw_line)
                if (
                    processed_bytes > MAX_MAPPING_FILE_BYTES
                    or len(raw_line) > MAX_MAPPING_LINE_BYTES
                    or len(unit_ids) >= MAX_MAPPING_RECORDS
                ):
                    raise ValueError("FAISS ID mapping exceeds safety limit")
                if not raw_line.strip():
                    continue
                payload = json.loads(raw_line.decode("utf-8"))
                unit_id = payload.get("unit_id") if isinstance(payload, dict) else None
                if not isinstance(unit_id, str) or not unit_id.strip():
                    raise ValueError("invalid unit ID")
                unit_ids.append(unit_id)
        return unit_ids
    except ValueError as exc:
        if "safety limit" in str(exc):
            raise
        raise ValueError("invalid FAISS ID mapping") from None
    except (
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
    ):
        raise ValueError("invalid FAISS ID mapping") from None


FileFingerprint = tuple[str, int, int, int, int, int]


class _ObjectIdentity:
    def __init__(self, value: object) -> None:
        self.value = value

    def __hash__(self) -> int:
        return id(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ObjectIdentity) and self.value is other.value


FaissBundleCacheKey = tuple[FileFingerprint, FileFingerprint, _ObjectIdentity]
_FAISS_BUNDLE_CACHE: OrderedDict[FaissBundleCacheKey, tuple[object, list[str]]] = OrderedDict()
_FAISS_BUNDLE_CACHE_LIMIT = 1
_FAISS_BUNDLE_CACHE_LOCK = threading.RLock()
_FAISS_VALIDATION_CACHE: OrderedDict[tuple[object, ...], bool] = OrderedDict()
_FAISS_VALIDATION_CACHE_LIMIT = 16
_FAISS_VALIDATION_CACHE_LOCK = threading.RLock()


def clear_faiss_caches() -> None:
    with _FAISS_BUNDLE_CACHE_LOCK:
        with _FAISS_VALIDATION_CACHE_LOCK:
            _FAISS_BUNDLE_CACHE.clear()
            _FAISS_VALIDATION_CACHE.clear()


def _file_fingerprint(path: Path) -> FileFingerprint:
    resolved = path.resolve()
    stat = resolved.stat()
    return (
        str(resolved),
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_size),
        int(stat.st_mtime_ns),
        int(stat.st_ctime_ns),
    )


def _faiss_bundle_cache_key(
    index_path: Path,
    ids_path: Path,
    faiss_module: object,
) -> FaissBundleCacheKey:
    return (
        _file_fingerprint(index_path),
        _file_fingerprint(ids_path),
        _ObjectIdentity(faiss_module),
    )


def _optional_file_fingerprint(path: Path) -> FileFingerprint | None:
    try:
        fingerprint = _file_fingerprint(path)
        return fingerprint if fingerprint[3] > 0 else None
    except FileNotFoundError:
        return None


def _database_revision_fingerprint(db_path: Path) -> tuple[object, ...]:
    return (
        _file_fingerprint(db_path),
        _optional_file_fingerprint(Path(f"{db_path}-wal")),
    )


def load_faiss_bundle(
    index_path: Path,
    ids_path: Path,
    faiss_module: object,
) -> tuple[object, list[str]]:
    """Load a FAISS index and ID mapping, caching unchanged on-disk bundles."""
    with _FAISS_BUNDLE_CACHE_LOCK:
        for _ in range(3):
            key = _faiss_bundle_cache_key(index_path, ids_path, faiss_module)
            cached = _FAISS_BUNDLE_CACHE.get(key)
            if cached is not None:
                _FAISS_BUNDLE_CACHE.move_to_end(key)
                return cached
            bundle = (
                faiss_module.read_index(str(index_path)),
                read_faiss_unit_ids(ids_path),
            )
            if key != _faiss_bundle_cache_key(index_path, ids_path, faiss_module):
                continue
            _FAISS_BUNDLE_CACHE[key] = bundle
            _FAISS_BUNDLE_CACHE.move_to_end(key)
            while len(_FAISS_BUNDLE_CACHE) > _FAISS_BUNDLE_CACHE_LIMIT:
                _FAISS_BUNDLE_CACHE.popitem(last=False)
            return bundle
    raise RuntimeError("FAISS artifacts changed while loading")


def _strict_nonnegative_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError("expected a nonnegative integer")
    return int(value)


def _audit_faiss_bundle_ids(
    conn: sqlite3.Connection,
    index: object,
    unit_ids: list[str],
) -> bool:
    if not unit_ids or len(unit_ids) != len(set(unit_ids)):
        return False
    try:
        if _strict_nonnegative_integer(index.ntotal) != len(unit_ids):
            return False
        sqlite_unit_ids = {
            str(row[0]) for row in conn.execute("SELECT unit_id FROM retrieval_units").fetchall()
        }
    except Exception:
        return False
    return len(sqlite_unit_ids) == len(unit_ids) and sqlite_unit_ids == set(unit_ids)


def _faiss_bundle_is_valid(
    conn: sqlite3.Connection,
    db_path: Path,
    index_path: Path,
    ids_path: Path,
    faiss_module: object,
    index: object,
    unit_ids: list[str],
) -> bool:
    try:
        unit_count = int(conn.execute("SELECT COUNT(*) FROM retrieval_units").fetchone()[0])
        key = (
            _faiss_bundle_cache_key(index_path, ids_path, faiss_module),
            _database_revision_fingerprint(db_path),
            unit_count,
            id(index),
            id(unit_ids),
        )
    except Exception:
        return False
    with _FAISS_VALIDATION_CACHE_LOCK:
        cached = _FAISS_VALIDATION_CACHE.get(key)
        if cached is not None:
            _FAISS_VALIDATION_CACHE.move_to_end(key)
            return cached
        valid = unit_count == len(unit_ids) and _audit_faiss_bundle_ids(conn, index, unit_ids)
        if key[1] != _database_revision_fingerprint(db_path):
            return False
        _FAISS_VALIDATION_CACHE[key] = valid
        _FAISS_VALIDATION_CACHE.move_to_end(key)
        while len(_FAISS_VALIDATION_CACHE) > _FAISS_VALIDATION_CACHE_LIMIT:
            _FAISS_VALIDATION_CACHE.popitem(last=False)
        return valid


def build_faiss_vector_index(
    db_path: Path,
    index_path: Path | None = None,
    ids_path: Path | None = None,
    batch_size: int = 4096,
    faiss_module: object | None = None,
) -> dict[str, object]:
    faiss = faiss_module or load_faiss_module()
    if faiss is None:
        raise RuntimeError(
            'FAISS is required. Install with `pip install ".[faiss]"` or `pip install faiss-cpu`.'
        )

    index_path = (index_path or default_faiss_index_path(db_path)).resolve()
    ids_path = (ids_path or default_faiss_ids_path(db_path)).resolve()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    ids_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path, factory=ClosingConnection) as conn:
        conn.row_factory = sqlite3.Row
        meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
        if meta.get("vector_kind") != "dense":
            raise RuntimeError("FAISS index can only be built for dense vectors")

        first = conn.execute(
            "SELECT vector_blob FROM retrieval_units ORDER BY unit_id LIMIT 1"
        ).fetchone()
        if first is None:
            raise RuntimeError("no retrieval_units found")
        dims = len(unpack_dense_vector(first["vector_blob"]))
        index = faiss.IndexFlatIP(dims)

        total = 0
        with ids_path.open("w", encoding="utf-8") as ids_file:
            offset = 0
            while True:
                rows = conn.execute(
                    """
                    SELECT unit_id, weight, vector_blob
                    FROM retrieval_units
                    ORDER BY unit_id
                    LIMIT ? OFFSET ?
                    """,
                    (batch_size, offset),
                ).fetchall()
                if not rows:
                    break
                vectors: list[list[float]] = []
                for row in rows:
                    vector = unpack_dense_vector(row["vector_blob"])
                    vectors.append(vector)
                    ids_file.write(
                        json.dumps({"unit_id": row["unit_id"]}, ensure_ascii=False) + "\n"
                    )
                index.add(faiss_matrix(vectors))
                total += len(rows)
                offset += len(rows)

        faiss.write_index(index, str(index_path))
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("faiss_index", str(index_path)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", ("faiss_ids", str(ids_path))
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", ("faiss_vectors", str(total))
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", ("faiss_dim", str(dims))
        )

    manifest_path = db_path.parent / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["faiss_index"] = str(index_path)
        manifest["faiss_ids"] = str(ids_path)
        manifest["faiss_vectors"] = total
        manifest["faiss_dim"] = dims
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return {
        "faiss_index": str(index_path),
        "faiss_ids": str(ids_path),
        "faiss_vectors": total,
        "faiss_dim": dims,
    }


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        result = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return bool(result)


class LocalVectorStore:
    def __init__(
        self,
        db_path: Path,
        dims: int = 2048,
        embedding_backend: SparseHashEmbeddingBackend | DenseEmbeddingBackend | None = None,
        brute_force_limit: int = 10_000,
    ) -> None:
        if isinstance(brute_force_limit, bool) or not isinstance(brute_force_limit, int):
            raise TypeError("brute_force_limit must be a nonnegative integer")
        if brute_force_limit < 0:
            raise ValueError("brute_force_limit must be a nonnegative integer")
        self.db_path = db_path
        self.dims = dims
        self.embedding_backend = embedding_backend or SparseHashEmbeddingBackend(dims=dims)
        self.brute_force_limit = brute_force_limit

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn

    def read_meta(self) -> dict[str, str]:
        if not self.db_path.exists():
            return {}
        with self.connect() as conn:
            try:
                return {
                    row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")
                }
            except sqlite3.OperationalError:
                return {}

    @staticmethod
    def _read_meta_keys_from_connection(
        conn: sqlite3.Connection,
        keys: tuple[str, ...],
    ) -> dict[str, str]:
        try:
            meta_objects = conn.execute(
                "SELECT type FROM sqlite_master WHERE name = ? COLLATE NOCASE",
                ("meta",),
            )
            meta_object = meta_objects.fetchone()
            if meta_object is None:
                return {}
            if meta_objects.fetchone() is not None or meta_object[0] != "table":
                raise RuntimeError("database metadata is invalid")
            placeholders = ",".join("?" for _ in keys)
            query = f"""SELECT key, typeof(value), length(CAST(value AS BLOB)),
                CASE WHEN typeof(value) = 'text'
                           AND length(CAST(value AS BLOB)) <= ?
                     THEN value ELSE NULL END
                FROM meta WHERE key IN ({placeholders})"""
            metadata: dict[str, str] = {}
            for key, value_type, value_length, safe_value in conn.execute(
                query,
                (MAX_RUNTIME_META_VALUE_CHARS, *keys),
            ):
                if (
                    not isinstance(key, str)
                    or key in metadata
                    or value_type != "text"
                    or not isinstance(value_length, int)
                    or value_length > MAX_RUNTIME_META_VALUE_CHARS
                    or not isinstance(safe_value, str)
                ):
                    raise RuntimeError("database metadata is invalid")
                metadata[key] = safe_value
        except (MemoryError, OverflowError, sqlite3.DatabaseError, TypeError, ValueError):
            raise RuntimeError("database metadata is invalid") from None
        return metadata

    def read_meta_keys(self, keys: tuple[str, ...]) -> dict[str, str]:
        if not keys or not self.db_path.exists():
            return {}
        with self.connect() as conn:
            return self._read_meta_keys_from_connection(conn, keys)

    def recreate(self) -> None:
        if self.db_path.exists():
            self.db_path.unlink()
        with self.connect() as conn:
            conn.executescript(
                """
                DROP TABLE IF EXISTS paragraphs;
                DROP TABLE IF EXISTS retrieval_units;
                DROP TABLE IF EXISTS guide_nodes_fts;
                DROP TABLE IF EXISTS guide_nodes;
                DROP TABLE IF EXISTS knowledge_units_fts;
                DROP TABLE IF EXISTS knowledge_units;
                DROP TABLE IF EXISTS meta;

                CREATE TABLE meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE paragraphs (
                    paragraph_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    page_start INTEGER NOT NULL,
                    page_end INTEGER NOT NULL,
                    text TEXT NOT NULL
                );

                CREATE TABLE retrieval_units (
                    unit_id TEXT PRIMARY KEY,
                    paragraph_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    unit_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    sentence_start INTEGER NOT NULL,
                    sentence_end INTEGER NOT NULL,
                    weight REAL NOT NULL,
                    vector_blob BLOB NOT NULL,
                    FOREIGN KEY(paragraph_id) REFERENCES paragraphs(paragraph_id)
                );

                CREATE INDEX idx_units_paragraph ON retrieval_units(paragraph_id);
                CREATE INDEX idx_units_type ON retrieval_units(unit_type);

                CREATE TABLE knowledge_units (
                    knowledge_unit_id TEXT PRIMARY KEY,
                    paragraph_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    page_start INTEGER NOT NULL,
                    page_end INTEGER NOT NULL,
                    unit_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    attributes_json TEXT NOT NULL,
                    evidence_quote TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    extractor_version TEXT NOT NULL,
                    FOREIGN KEY(paragraph_id) REFERENCES paragraphs(paragraph_id)
                );

                CREATE INDEX idx_knowledge_paragraph ON knowledge_units(paragraph_id);
                CREATE INDEX idx_knowledge_type ON knowledge_units(unit_type);

                CREATE TABLE guide_nodes (
                    node_id TEXT PRIMARY KEY,
                    parent_id TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    badge TEXT NOT NULL,
                    path TEXT NOT NULL,
                    content TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    paragraph_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    page_start INTEGER NOT NULL,
                    page_end INTEGER NOT NULL,
                    evidence_quote TEXT NOT NULL
                );

                CREATE INDEX idx_guide_type ON guide_nodes(node_type);
                """
            )
            conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", ("dims", str(self.dims)))
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?)", ("vector_dim", str(self.dims))
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                ("embedding", self.embedding_backend.name),
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                ("vector_kind", self.embedding_backend.vector_kind),
            )

    def insert_paragraphs(self, paragraphs: Iterable[ParsedParagraph]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO paragraphs
                (paragraph_id, doc_id, source_path, title, page_start, page_end, text)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        paragraph.paragraph_id,
                        paragraph.doc_id,
                        paragraph.source_path,
                        paragraph.title,
                        paragraph.page_start,
                        paragraph.page_end,
                        paragraph.text,
                    )
                    for paragraph in paragraphs
                ],
            )
        self.rebuild_text_index()

    def rebuild_text_index(self) -> dict[str, int | str]:
        with self.connect() as conn:
            conn.execute("DROP TABLE IF EXISTS paragraphs_fts")
            tokenizer = "trigram"
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE paragraphs_fts USING fts5(
                        paragraph_id UNINDEXED,
                        doc_id UNINDEXED,
                        source_path UNINDEXED,
                        title,
                        text,
                        tokenize='trigram'
                    )
                    """
                )
            except sqlite3.OperationalError:
                tokenizer = "unicode61"
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE paragraphs_fts USING fts5(
                        paragraph_id UNINDEXED,
                        doc_id UNINDEXED,
                        source_path UNINDEXED,
                        title,
                        text
                    )
                    """
                )
            conn.execute(
                """
                INSERT INTO paragraphs_fts(paragraph_id, doc_id, source_path, title, text)
                SELECT paragraph_id, doc_id, source_path, title, text
                FROM paragraphs
                ORDER BY doc_id, page_start, paragraph_id
                """
            )
            rows = conn.execute("SELECT COUNT(*) FROM paragraphs_fts").fetchone()[0]
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("text_index", f"fts5_{tokenizer}"),
            )
        _update_manifest_after_text_index(self.db_path, f"fts5_{tokenizer}", rows)
        return {
            "db_path": str(self.db_path),
            "text_index": f"fts5_{tokenizer}",
            "text_index_rows": rows,
        }

    def ensure_knowledge_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS knowledge_units (
                knowledge_unit_id TEXT PRIMARY KEY,
                paragraph_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                title TEXT NOT NULL,
                page_start INTEGER NOT NULL,
                page_end INTEGER NOT NULL,
                unit_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                attributes_json TEXT NOT NULL,
                evidence_quote TEXT NOT NULL,
                confidence REAL NOT NULL,
                extractor_version TEXT NOT NULL,
                FOREIGN KEY(paragraph_id) REFERENCES paragraphs(paragraph_id)
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_paragraph ON knowledge_units(paragraph_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_type ON knowledge_units(unit_type);
            """
        )

    def ensure_guide_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guide_nodes (
                node_id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL,
                node_type TEXT NOT NULL,
                label TEXT NOT NULL,
                badge TEXT NOT NULL,
                path TEXT NOT NULL,
                content TEXT NOT NULL,
                search_text TEXT NOT NULL,
                paragraph_id TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                page_start INTEGER NOT NULL DEFAULT 0,
                page_end INTEGER NOT NULL DEFAULT 0,
                evidence_quote TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_guide_type ON guide_nodes(node_type);
            """
        )
        existing = {
            row["name"] for row in conn.execute("PRAGMA table_info(guide_nodes)").fetchall()
        }
        migrations = {
            "paragraph_id": "ALTER TABLE guide_nodes ADD COLUMN paragraph_id TEXT NOT NULL DEFAULT ''",
            "source_path": "ALTER TABLE guide_nodes ADD COLUMN source_path TEXT NOT NULL DEFAULT ''",
            "title": "ALTER TABLE guide_nodes ADD COLUMN title TEXT NOT NULL DEFAULT ''",
            "page_start": "ALTER TABLE guide_nodes ADD COLUMN page_start INTEGER NOT NULL DEFAULT 0",
            "page_end": "ALTER TABLE guide_nodes ADD COLUMN page_end INTEGER NOT NULL DEFAULT 0",
            "evidence_quote": "ALTER TABLE guide_nodes ADD COLUMN evidence_quote TEXT NOT NULL DEFAULT ''",
        }
        for column, sql in migrations.items():
            if column not in existing:
                conn.execute(sql)

    def _rebuild_guide_fts(self, conn: sqlite3.Connection) -> None:
        conn.execute("DROP TABLE IF EXISTS guide_nodes_fts")
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE guide_nodes_fts USING fts5(
                    node_id UNINDEXED,
                    label,
                    path,
                    content,
                    search_text,
                    tokenize='unicode61'
                )
                """
            )
        except sqlite3.OperationalError:
            conn.execute(
                """
                CREATE VIRTUAL TABLE guide_nodes_fts USING fts5(
                    node_id UNINDEXED,
                    label,
                    path,
                    content,
                    search_text
                )
                """
            )
        conn.execute(
            """
            INSERT INTO guide_nodes_fts(node_id, label, path, content, search_text)
            SELECT node_id, label, path, content, search_text
            FROM guide_nodes
            ORDER BY path, node_id
            """
        )

    def rebuild_guide_nodes(self) -> dict[str, object]:
        with self.connect() as conn:
            self.ensure_knowledge_schema(conn)
            self.ensure_guide_schema(conn)
            rows = conn.execute(
                """
                SELECT knowledge_unit_id, paragraph_id, doc_id, source_path, title, page_start,
                       page_end, unit_type, subject, predicate, object, evidence_quote
                FROM knowledge_units
                ORDER BY source_path, page_start, knowledge_unit_id
                """
            ).fetchall()
            nodes: list[GuideNode] = []
            for row in rows:
                raw_evidence = normalize_whitespace(str(row["evidence_quote"]))
                if has_guide_source_noise(raw_evidence):
                    continue
                evidence = clean_guide_evidence_text(raw_evidence)
                node_type, badge = guide_style_for_unit(str(row["unit_type"]))
                label = str(row["subject"] or row["object"]).strip()
                if not label:
                    continue
                source_name = Path(str(row["source_path"])).name
                path = f"{source_name} p{row['page_start']} > {badge} > {label}"
                content = clean_guide_evidence_text(str(row["object"] or evidence))
                search_text = normalize_whitespace(
                    " ".join(
                        [
                            path,
                            str(row["unit_type"]),
                            label,
                            str(row["predicate"]),
                            content,
                            evidence,
                        ]
                    )
                )
                nodes.append(
                    GuideNode(
                        node_id=f"guide-{row['knowledge_unit_id']}",
                        parent_id="",
                        node_type=node_type,
                        label=label,
                        badge=badge,
                        path=path,
                        content=content,
                        search_text=search_text,
                        paragraph_id=str(row["paragraph_id"]),
                        source_path=str(row["source_path"]),
                        title=str(row["title"]),
                        page_start=int(row["page_start"]),
                        page_end=int(row["page_end"]),
                        evidence_quote=evidence,
                    )
                )
            paragraph_rows = conn.execute(
                """
                SELECT paragraph_id, source_path, title, page_start, page_end, text
                FROM paragraphs
                ORDER BY source_path, page_start, paragraph_id
                """
            ).fetchall()
            existing_node_ids = {node.node_id for node in nodes}
            for row in paragraph_rows:
                text = str(row["text"])
                if not is_guide_source_text(text):
                    continue
                for formula in extract_formula_terms(text):
                    node_id = f"guide-formula-{stable_id(row['paragraph_id'], formula)}"
                    if node_id in existing_node_ids:
                        continue
                    existing_node_ids.add(node_id)
                    source_name = Path(str(row["source_path"])).name
                    path = f"{source_name} p{row['page_start']} > 方证 > {formula}"
                    evidence = clean_guide_evidence_text(evidence_quote(text, max_chars=260))
                    search_text = normalize_whitespace(
                        " ".join([path, "formula_pattern", formula, text[:600], evidence])
                    )
                    nodes.append(
                        GuideNode(
                            node_id=node_id,
                            parent_id="",
                            node_type="formula",
                            label=formula,
                            badge="方证",
                            path=path,
                            content=evidence,
                            search_text=search_text,
                            paragraph_id=str(row["paragraph_id"]),
                            source_path=str(row["source_path"]),
                            title=str(row["title"]),
                            page_start=int(row["page_start"]),
                            page_end=int(row["page_end"]),
                            evidence_quote=evidence,
                        )
                    )
            conn.execute("DELETE FROM guide_nodes")
            conn.executemany(
                """
                INSERT OR REPLACE INTO guide_nodes
                (node_id, parent_id, node_type, label, badge, path, content, search_text,
                 paragraph_id, source_path, title, page_start, page_end, evidence_quote)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        node.node_id,
                        node.parent_id,
                        node.node_type,
                        node.label,
                        node.badge,
                        node.path,
                        node.content,
                        node.search_text,
                        node.paragraph_id,
                        node.source_path,
                        node.title,
                        node.page_start,
                        node.page_end,
                        node.evidence_quote,
                    )
                    for node in nodes
                ],
            )
            self._rebuild_guide_fts(conn)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("guide_nodes", str(len(nodes))),
            )
        return {"db_path": str(self.db_path), "guide_nodes": len(nodes)}

    def search_guide_nodes(self, query: str, limit: int = 8) -> list[dict[str, object]]:
        validate_runtime_limit(limit, "limit", MAX_PUBLIC_ANSWER_LIMIT)
        if not self.db_path.exists():
            return []
        with self.connect() as conn:
            self.ensure_guide_schema(conn)
            terms = useful_query_terms(query, max_terms=12)
            terms.extend(extract_formula_terms(query))
            terms = dedupe_keep_order(terms)
            candidates: dict[str, float] = {}
            try:
                fts_query = fts5_query_from_terms(terms)
                if fts_query:
                    rows = conn.execute(
                        """
                        SELECT node_id, bm25(guide_nodes_fts) AS rank
                        FROM guide_nodes_fts
                        WHERE guide_nodes_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (fts_query, max(limit * 4, 16)),
                    ).fetchall()
                    for row in rows:
                        candidates[str(row["node_id"])] = max(
                            candidates.get(str(row["node_id"]), 0.0),
                            1.0 / (1.0 + abs(float(row["rank"]))),
                        )
            except sqlite3.OperationalError:
                pass

            like_terms = terms[:8] or [query]
            for term in like_terms:
                pattern = f"%{term}%"
                rows = conn.execute(
                    """
                    SELECT node_id
                    FROM guide_nodes
                    WHERE label LIKE ? OR path LIKE ? OR content LIKE ? OR search_text LIKE ?
                    LIMIT ?
                    """,
                    (pattern, pattern, pattern, pattern, max(limit * 4, 16)),
                ).fetchall()
                for row in rows:
                    candidates[str(row["node_id"])] = candidates.get(str(row["node_id"]), 0.0) + 1.0

            if not candidates:
                return []
            placeholders = ",".join("?" for _ in candidates)
            rows = conn.execute(
                f"""
                SELECT node_id, parent_id, node_type, label, badge, path, content, search_text,
                       paragraph_id, source_path, title, page_start, page_end, evidence_quote
                FROM guide_nodes
                WHERE node_id IN ({placeholders})
                """,
                list(candidates),
            ).fetchall()
        normalized_query = normalize_whitespace(query)
        results = []
        for row in rows:
            score = candidates[str(row["node_id"])]
            label = str(row["label"])
            if label and label in normalized_query:
                score += 20.0
            if row["node_type"] == "formula":
                score += 5.0
            if row["badge"] == "方证":
                score += 3.0
            results.append(
                {
                    "node_id": row["node_id"],
                    "parent_id": row["parent_id"],
                    "node_type": row["node_type"],
                    "label": row["label"],
                    "badge": row["badge"],
                    "path": row["path"],
                    "content": row["content"],
                    "search_text": row["search_text"],
                    "paragraph_id": row["paragraph_id"],
                    "source_path": public_source_path(row["source_path"]),
                    "title": row["title"],
                    "page_start": row["page_start"],
                    "page_end": row["page_end"],
                    "evidence_quote": row["evidence_quote"],
                    "score": score,
                }
            )
        results.sort(key=lambda item: (float(item["score"]), len(str(item["path"]))), reverse=True)
        unique_results: list[dict[str, object]] = []
        seen_result_labels: set[tuple[str, str]] = set()
        for result in results:
            key = (
                normalize_whitespace(str(result.get("badge") or result.get("node_type") or "")),
                normalize_whitespace(str(result.get("label") or "")),
            )
            if key in seen_result_labels:
                continue
            seen_result_labels.add(key)
            unique_results.append(result)
            if len(unique_results) >= limit:
                break
        return unique_results

    def rebuild_knowledge_units(self, trace_dir: Path | None = None) -> dict[str, object]:
        with self.connect() as conn:
            self.ensure_knowledge_schema(conn)
            paragraph_rows = conn.execute(
                """
                SELECT paragraph_id, doc_id, source_path, title, page_start, page_end, text
                FROM paragraphs
                ORDER BY doc_id, page_start, paragraph_id
                """
            ).fetchall()
            paragraphs = [
                ParsedParagraph(
                    paragraph_id=row["paragraph_id"],
                    doc_id=row["doc_id"],
                    source_path=row["source_path"],
                    title=row["title"],
                    page_start=row["page_start"],
                    page_end=row["page_end"],
                    text=row["text"],
                )
                for row in paragraph_rows
            ]
            units = build_knowledge_units(paragraphs)

            conn.execute("DELETE FROM knowledge_units")
            conn.executemany(
                """
                INSERT OR REPLACE INTO knowledge_units
                (knowledge_unit_id, paragraph_id, doc_id, source_path, title, page_start, page_end,
                 unit_type, subject, predicate, object, attributes_json, evidence_quote,
                 confidence, extractor_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        unit.knowledge_unit_id,
                        unit.paragraph_id,
                        unit.doc_id,
                        unit.source_path,
                        unit.title,
                        unit.page_start,
                        unit.page_end,
                        unit.unit_type,
                        unit.subject,
                        unit.predicate,
                        unit.object,
                        unit.attributes_json,
                        unit.evidence_quote,
                        unit.confidence,
                        unit.extractor_version,
                    )
                    for unit in units
                ],
            )
            self._rebuild_knowledge_fts(conn)
            rows = conn.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]
            type_rows = conn.execute(
                """
                SELECT unit_type, COUNT(*) AS count
                FROM knowledge_units
                GROUP BY unit_type
                ORDER BY unit_type
                """
            ).fetchall()
            unit_types = {row["unit_type"]: int(row["count"]) for row in type_rows}
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("knowledge_units", str(rows)),
            )

        trace_path = None
        if trace_dir is not None:
            trace_path = trace_dir.expanduser() / "knowledge_units.jsonl"
            write_jsonl(
                trace_path,
                (
                    {
                        "knowledge_unit_id": unit.knowledge_unit_id,
                        "paragraph_id": unit.paragraph_id,
                        "doc_id": unit.doc_id,
                        "source_path": unit.source_path,
                        "title": unit.title,
                        "page_start": unit.page_start,
                        "page_end": unit.page_end,
                        "unit_type": unit.unit_type,
                        "subject": unit.subject,
                        "predicate": unit.predicate,
                        "object": unit.object,
                        "attributes": json.loads(unit.attributes_json),
                        "evidence_quote": unit.evidence_quote,
                        "confidence": unit.confidence,
                        "extractor_version": unit.extractor_version,
                    }
                    for unit in units
                ),
            )

        _update_manifest_after_knowledge_units(self.db_path, rows, unit_types, trace_path)
        return {
            "db_path": str(self.db_path),
            "knowledge_units": rows,
            "knowledge_unit_types": unit_types,
            "knowledge_trace": str(trace_path) if trace_path else "",
        }

    def _rebuild_knowledge_fts(self, conn: sqlite3.Connection) -> None:
        conn.execute("DROP TABLE IF EXISTS knowledge_units_fts")
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE knowledge_units_fts USING fts5(
                    knowledge_unit_id UNINDEXED,
                    paragraph_id UNINDEXED,
                    unit_type UNINDEXED,
                    subject,
                    predicate,
                    object,
                    evidence_quote,
                    tokenize='trigram'
                )
                """
            )
        except sqlite3.OperationalError:
            conn.execute(
                """
                CREATE VIRTUAL TABLE knowledge_units_fts USING fts5(
                    knowledge_unit_id UNINDEXED,
                    paragraph_id UNINDEXED,
                    unit_type UNINDEXED,
                    subject,
                    predicate,
                    object,
                    evidence_quote
                )
                """
            )
        conn.execute(
            """
            INSERT INTO knowledge_units_fts(
                knowledge_unit_id, paragraph_id, unit_type, subject, predicate, object, evidence_quote
            )
            SELECT knowledge_unit_id, paragraph_id, unit_type, subject, predicate, object, evidence_quote
            FROM knowledge_units
            ORDER BY doc_id, page_start, knowledge_unit_id
            """
        )

    def has_text_index(self) -> bool:
        if not self.db_path.exists():
            return False
        with self.connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'paragraphs_fts'"
            ).fetchone()
            return row is not None

    def has_knowledge_index(self) -> bool:
        if not self.db_path.exists():
            return False
        with self.connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_units'"
            ).fetchone()
            return row is not None

    def insert_units(self, units: Iterable[RetrievalUnit], insert_batch_size: int = 256) -> None:
        unit_list = list(units)
        with self.connect() as conn:
            for start in range(0, len(unit_list), insert_batch_size):
                batch = unit_list[start : start + insert_batch_size]
                vectors = self.embedding_backend.embed_texts(
                    [unit.text_for_embedding for unit in batch]
                )
                if len(vectors) != len(batch):
                    raise RuntimeError("embedding backend returned a different number of vectors")
                if self.embedding_backend.vector_kind == "dense":
                    vector_dim = len(vectors[0]) if vectors else 0
                    if any(len(vector) != vector_dim for vector in vectors):
                        raise RuntimeError(
                            "dense embedding backend returned inconsistent vector dimensions"
                        )
                    conn.execute(
                        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                        ("dims", str(vector_dim)),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                        ("vector_dim", str(vector_dim)),
                    )
                rows = []
                for unit, vector in zip(batch, vectors):
                    vector_blob = (
                        pack_sparse_vector(vector)
                        if self.embedding_backend.vector_kind == "sparse"
                        else pack_dense_vector(vector)
                    )
                    rows.append(
                        (
                            unit.unit_id,
                            unit.paragraph_id,
                            unit.doc_id,
                            unit.unit_type,
                            unit.text,
                            unit.sentence_start,
                            unit.sentence_end,
                            unit.weight,
                            vector_blob,
                        )
                    )
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO retrieval_units
                    (unit_id, paragraph_id, doc_id, unit_type, text,
                     sentence_start, sentence_end, weight, vector_blob)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

    def stats(self) -> dict[str, int | str]:
        with self.connect() as conn:
            paragraphs = conn.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0]
            units = conn.execute("SELECT COUNT(*) FROM retrieval_units").fetchone()[0]
            docs = conn.execute("SELECT COUNT(DISTINCT doc_id) FROM paragraphs").fetchone()[0]
            try:
                knowledge_units = conn.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]
            except sqlite3.OperationalError:
                knowledge_units = 0
        return {
            "db_path": str(self.db_path),
            "documents": docs,
            "paragraphs": paragraphs,
            "retrieval_units": units,
            "knowledge_units": knowledge_units,
        }

    def _apply_source_layer_policy(
        self,
        results: list[dict[str, object]],
        include_reference_secondary: bool,
    ) -> list[dict[str, object]]:
        if not results:
            return []
        paragraph_ids = dedupe_keep_order(str(result.get("paragraph_id", "")) for result in results)
        paragraph_ids = [paragraph_id for paragraph_id in paragraph_ids if paragraph_id]
        if not paragraph_ids:
            return results
        with self.connect() as conn:
            tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {"documents", "evidence_records"} <= tables:
                return results
            placeholders = ",".join("?" for _ in paragraph_ids)
            rows = conn.execute(
                f"""
                SELECT ev.paragraph_id, d.source_layer
                FROM evidence_records ev
                JOIN documents d ON d.document_id = ev.document_id
                WHERE ev.paragraph_id IN ({placeholders})
                """,
                paragraph_ids,
            ).fetchall()
        layers = {str(row["paragraph_id"]): str(row["source_layer"]) for row in rows}
        filtered: list[dict[str, object]] = []
        for result in results:
            layer = layers.get(str(result.get("paragraph_id", "")))
            if layer == "reference_secondary" and not include_reference_secondary:
                continue
            if layer:
                result = {**result, "source_layer": layer}
            filtered.append(result)
        return filtered

    def search_vector(
        self,
        query: str,
        limit: int = 8,
        unit_limit: int = 80,
        faiss_module: object | None = None,
    ) -> list[dict[str, object]]:
        validate_runtime_limit(limit, "limit", MAX_INTERNAL_SEARCH_LIMIT)
        validate_runtime_limit(unit_limit, "unit_limit", MAX_VECTOR_UNIT_LIMIT)
        vector_kind = self.embedding_backend.vector_kind
        stored_vector_kind = self.read_meta_keys(("vector_kind",)).get("vector_kind")
        if stored_vector_kind and stored_vector_kind != vector_kind:
            raise RuntimeError(
                "vector_kind mismatch: "
                f"database uses {stored_vector_kind}, but embedding backend produces {vector_kind}. "
                "Use the same embedding family that built the database, for example "
                "`--embedding siliconflow` with BAAI/bge-m3 or `--embedding local-bge-m3`."
            )
        query_vectors = self.embedding_backend.embed_texts([query])
        if not query_vectors:
            return []
        query_vector = query_vectors[0]
        if not query_vector:
            return []
        dense_query_vector = (
            normalize_dense_vector(query_vector) if vector_kind == "dense" else None
        )
        hits: list[tuple[float, sqlite3.Row]] = []
        with self.connect() as conn:
            if dense_query_vector is not None:
                faiss_results = self._search_vector_faiss(
                    conn=conn,
                    query_vector=dense_query_vector,
                    limit=limit,
                    unit_limit=unit_limit,
                    faiss_module=faiss_module,
                )
                if faiss_results is not None:
                    return faiss_results

                unit_count = int(conn.execute("SELECT COUNT(*) FROM retrieval_units").fetchone()[0])
                if unit_count > self.brute_force_limit:
                    raise RuntimeError(
                        f"Dense search has {unit_count} retrieval units and cannot safely brute-force "
                        f"more than {self.brute_force_limit}. Install FAISS with "
                        '`pip install ".[runtime]"` and run `nihaisha-rag doctor`.'
                    )

            rows = conn.execute(
                """
                SELECT unit_id, paragraph_id, unit_type, text, sentence_start, sentence_end, weight, vector_blob
                FROM retrieval_units
                """
            ).fetchall()
            for row in rows:
                if vector_kind == "sparse":
                    vector = unpack_sparse_vector(row["vector_blob"])
                    score = sparse_dot(query_vector, vector) * float(row["weight"])
                else:
                    vector = unpack_dense_vector(row["vector_blob"])
                    score = dense_dot(dense_query_vector, vector) * float(row["weight"])
                if score > 0:
                    hits.append((score, row))
            hits.sort(key=lambda item: item[0], reverse=True)
            return self._vector_hits_to_results(
                conn, hits[:unit_limit], limit=limit, source="vector"
            )

    def _search_vector_faiss(
        self,
        conn: sqlite3.Connection,
        query_vector: list[float],
        limit: int,
        unit_limit: int,
        faiss_module: object | None = None,
    ) -> list[dict[str, object]] | None:
        try:
            artifact_meta = self._read_meta_keys_from_connection(
                conn,
                ("faiss_index", "faiss_ids"),
            )
            artifacts = resolve_faiss_artifacts(
                self.db_path,
                artifact_meta.get("faiss_index"),
                artifact_meta.get("faiss_ids"),
            )
            index_path = artifacts.index
            ids_path = artifacts.ids
        except Exception:
            return None
        if not index_path.exists() or not ids_path.exists():
            return None
        faiss = load_faiss_module() if faiss_module is None else faiss_module
        if faiss is None:
            return None
        if faiss is False:
            return None
        try:
            index, unit_ids = load_faiss_bundle(index_path, ids_path, faiss)
        except Exception:  # malformed artifacts and third-party loader failures fall back safely
            return None
        if not _faiss_bundle_is_valid(
            conn,
            self.db_path,
            index_path,
            ids_path,
            faiss,
            index,
            unit_ids,
        ):
            return None
        top_k = min(len(unit_ids), MAX_SQLITE_IN_ITEMS, max(unit_limit, limit * 20))
        try:
            scores, indices = index.search(faiss_matrix([query_vector]), top_k)
        except Exception:  # unusable FAISS indexes must not bypass the scan guard
            return None
        scored_unit_ids: list[tuple[float, str]] = []
        seen_row_indices: set[int] = set()
        try:
            returned_hits = zip(scores[0], indices[0])
            for score_value, row_index_value in returned_hits:
                try:
                    row_index = int(row_index_value)
                    score = float(score_value)
                except (OverflowError, TypeError, ValueError):
                    continue
                if (
                    row_index < 0
                    or row_index >= len(unit_ids)
                    or row_index in seen_row_indices
                    or not math.isfinite(score)
                    or score <= 0
                ):
                    continue
                seen_row_indices.add(row_index)
                scored_unit_ids.append((score, unit_ids[row_index]))
        except Exception:
            return None
        if not scored_unit_ids:
            return []

        placeholders = ",".join("?" for _ in scored_unit_ids)
        rows = conn.execute(
            f"""
            SELECT unit_id, paragraph_id, unit_type, text, sentence_start, sentence_end, weight, vector_blob
            FROM retrieval_units
            WHERE unit_id IN ({placeholders})
            """,
            [unit_id for _, unit_id in scored_unit_ids],
        ).fetchall()
        row_by_id = {row["unit_id"]: row for row in rows}
        hits = [
            (score * float(row_by_id[unit_id]["weight"]), row_by_id[unit_id])
            for score, unit_id in scored_unit_ids
            if unit_id in row_by_id
        ]
        return self._vector_hits_to_results(conn, hits, limit=limit, source="faiss")

    def _vector_hits_to_results(
        self,
        conn: sqlite3.Connection,
        hits: list[tuple[float, sqlite3.Row]],
        limit: int,
        source: str,
    ) -> list[dict[str, object]]:
        paragraph_scores: dict[str, dict[str, object]] = {}
        for score, row in hits:
            paragraph_id = row["paragraph_id"]
            current = paragraph_scores.setdefault(
                paragraph_id,
                {
                    "paragraph_id": paragraph_id,
                    "score": 0.0,
                    "hit_count": 0,
                    "unit_types": set(),
                    "matched_units": [],
                },
            )
            current["score"] = max(float(current["score"]), score)
            current["hit_count"] = int(current["hit_count"]) + 1
            current["unit_types"].add(row["unit_type"])
            current["matched_units"].append(
                {
                    "unit_id": row["unit_id"],
                    "unit_type": row["unit_type"],
                    "score": round(score, 6),
                    "text": row["text"],
                    "sentence_start": row["sentence_start"],
                    "sentence_end": row["sentence_end"],
                }
            )

        ranked = []
        for item in paragraph_scores.values():
            diversity_bonus = 0.03 * max(0, len(item["unit_types"]) - 1)
            count_bonus = 0.01 * min(8, int(item["hit_count"]) - 1)
            item["score"] = float(item["score"]) + diversity_bonus + count_bonus
            ranked.append(item)
        ranked.sort(key=lambda item: float(item["score"]), reverse=True)

        results = []
        for item in ranked[:limit]:
            paragraph = conn.execute(
                "SELECT * FROM paragraphs WHERE paragraph_id = ?", (item["paragraph_id"],)
            ).fetchone()
            if not paragraph:
                continue
            results.append(
                {
                    "paragraph_id": paragraph["paragraph_id"],
                    "doc_id": paragraph["doc_id"],
                    "source_path": public_source_path(paragraph["source_path"]),
                    "title": paragraph["title"],
                    "page_start": paragraph["page_start"],
                    "page_end": paragraph["page_end"],
                    "text": paragraph["text"],
                    "score": round(float(item["score"]), 6),
                    "vector_score": round(float(item["score"]), 6),
                    "text_score": 0.0,
                    "knowledge_score": 0.0,
                    "retrieval_sources": [source],
                    "hit_count": item["hit_count"],
                    "unit_types": sorted(item["unit_types"]),
                    "matched_units": item["matched_units"][:5],
                    "matched_text_terms": [],
                    "matched_knowledge_units": [],
                }
            )
        return results

    def search_text(
        self, query: str, limit: int = 8, candidate_limit: int = 200
    ) -> list[dict[str, object]]:
        validate_runtime_limit(limit, "limit", MAX_INTERNAL_SEARCH_LIMIT)
        validate_runtime_limit(candidate_limit, "candidate_limit", MAX_INTERNAL_SEARCH_LIMIT)
        terms = text_search_terms(query)
        if not terms:
            return []

        paragraph_scores: dict[str, dict[str, object]] = {}
        with self.connect() as conn:
            if self.has_text_index():
                fts_query = fts5_query_from_terms(terms)
                if fts_query:
                    try:
                        rows = conn.execute(
                            """
                            SELECT paragraph_id, bm25(paragraphs_fts) AS rank
                            FROM paragraphs_fts
                            WHERE paragraphs_fts MATCH ?
                            ORDER BY rank
                            LIMIT ?
                            """,
                            (fts_query, candidate_limit),
                        ).fetchall()
                        fts_ranks = [float(row["rank"]) for row in rows]
                        best_rank = min(fts_ranks, default=0.0)
                        worst_rank = max(fts_ranks, default=0.0)
                        rank_span = worst_rank - best_rank
                        for row in rows:
                            bm25_rank = float(row["rank"])
                            normalized_bm25 = (
                                (worst_rank - bm25_rank) / rank_span if rank_span > 0 else 1.0
                            )
                            score = 0.35 + 0.45 * normalized_bm25
                            item = paragraph_scores.setdefault(
                                row["paragraph_id"],
                                {
                                    "paragraph_id": row["paragraph_id"],
                                    "text_score": 0.0,
                                    "matched_text_terms": set(),
                                    "bm25_rank": bm25_rank,
                                },
                            )
                            item["text_score"] = max(float(item["text_score"]), score)
                            item["bm25_rank"] = min(
                                float(item.get("bm25_rank", bm25_rank)), bm25_rank
                            )
                    except sqlite3.OperationalError:
                        pass

            clauses = []
            params: list[str] = []
            for term in terms:
                pattern = f"%{term}%"
                clauses.append("text LIKE ?")
                params.append(pattern)
            like_rows = conn.execute(
                f"""
                SELECT paragraph_id, title, text
                FROM paragraphs
                WHERE {" OR ".join(clauses)}
                ORDER BY paragraph_id
                LIMIT ?
                """,
                [*params, candidate_limit],
            ).fetchall()

            for row in like_rows:
                normalized_text = normalize_query_text(str(row["text"]))
                matched_terms = [
                    term for term in terms if normalize_query_text(term) in normalized_text
                ]
                if not matched_terms:
                    continue
                item = paragraph_scores.setdefault(
                    row["paragraph_id"],
                    {
                        "paragraph_id": row["paragraph_id"],
                        "text_score": 0.0,
                        "matched_text_terms": set(),
                        "bm25_rank": None,
                    },
                )
                item["matched_text_terms"].update(matched_terms)

            core_terms = query_core_entity_terms(query)
            phrases = exact_query_phrases(query)
            scored: list[tuple[dict[str, object], sqlite3.Row]] = []
            for item in paragraph_scores.values():
                paragraph = conn.execute(
                    "SELECT * FROM paragraphs WHERE paragraph_id = ?", (item["paragraph_id"],)
                ).fetchone()
                if not paragraph:
                    continue
                body = str(paragraph["text"])
                title = str(paragraph["title"])
                normalized_body = normalize_query_text(body)
                normalized_title = normalize_query_text(title)
                body_terms = [
                    term for term in terms if normalize_query_text(term) in normalized_body
                ]
                title_terms = [
                    term for term in terms if normalize_query_text(term) in normalized_title
                ]
                normalized_core = dedupe_keep_order(
                    normalize_query_text(term) for term in core_terms
                )
                core_hits = [term for term in normalized_core if term in normalized_body]
                phrase_hits = [
                    phrase for phrase in phrases if normalize_query_text(phrase) in normalized_body
                ]
                if title_terms and not body_terms:
                    continue
                score = float(item["text_score"])
                score += 0.12 * min(len(body_terms), 6)
                if phrase_hits:
                    score += 1.25 + 0.12 * min(len(phrase_hits), 3)
                if normalized_core and len(core_hits) == len(normalized_core):
                    score += 0.55
                elif normalized_core:
                    score += 0.2 * (len(core_hits) / len(normalized_core))
                score += overview_structure_bonus(query, body)
                score -= retrieval_noise_penalty(title, body)
                item["text_score"] = max(0.0, score)
                item["matched_text_terms"].update(body_terms)
                item["matched_core_terms"] = core_hits
                item["exact_phrase_matches"] = phrase_hits
                scored.append((item, paragraph))

            scored.sort(
                key=lambda pair: (
                    -float(pair[0]["text_score"]),
                    str(pair[0]["paragraph_id"]),
                )
            )

            results = []
            for item, paragraph in scored[:limit]:
                results.append(
                    {
                        "paragraph_id": paragraph["paragraph_id"],
                        "doc_id": paragraph["doc_id"],
                        "source_path": public_source_path(paragraph["source_path"]),
                        "title": paragraph["title"],
                        "page_start": paragraph["page_start"],
                        "page_end": paragraph["page_end"],
                        "text": paragraph["text"],
                        "score": round(float(item["text_score"]), 6),
                        "vector_score": 0.0,
                        "text_score": round(float(item["text_score"]), 6),
                        "knowledge_score": 0.0,
                        "retrieval_sources": ["text"],
                        "hit_count": 0,
                        "unit_types": [],
                        "matched_units": [],
                        "matched_text_terms": sorted(item["matched_text_terms"]),
                        "matched_core_terms": list(item.get("matched_core_terms", [])),
                        "exact_phrase_matches": list(item.get("exact_phrase_matches", [])),
                        "bm25_rank": item.get("bm25_rank"),
                        "matched_knowledge_units": [],
                    }
                )
            return results

    def search_knowledge_units(
        self,
        query: str,
        limit: int = 8,
        candidate_limit: int = 200,
    ) -> list[dict[str, object]]:
        validate_runtime_limit(limit, "limit", MAX_INTERNAL_SEARCH_LIMIT)
        validate_runtime_limit(candidate_limit, "candidate_limit", MAX_INTERNAL_SEARCH_LIMIT)
        terms = knowledge_search_terms(query)
        if not terms or not self.has_knowledge_index():
            return []
        normalized_query = normalize_query_text(query)
        dosage_intent = "一钱" in normalized_query and (
            "多少" in normalized_query or "几克" in normalized_query or "克" in normalized_query
        )

        paragraph_scores: dict[str, dict[str, object]] = {}
        with self.connect() as conn:
            fts_query = fts5_query_from_terms(terms)
            if fts_query:
                try:
                    rows = conn.execute(
                        """
                        SELECT knowledge_unit_id, paragraph_id, unit_type
                        FROM knowledge_units_fts
                        WHERE knowledge_units_fts MATCH ?
                        LIMIT ?
                        """,
                        (fts_query, candidate_limit),
                    ).fetchall()
                    for index, row in enumerate(rows):
                        if dosage_intent and row["unit_type"] != "dosage":
                            continue
                        score = 0.55 + 0.25 * (1.0 - index / max(1, len(rows)))
                        item = paragraph_scores.setdefault(
                            row["paragraph_id"],
                            {
                                "paragraph_id": row["paragraph_id"],
                                "knowledge_score": 0.0,
                                "matched_knowledge_unit_ids": set(),
                            },
                        )
                        item["knowledge_score"] = max(float(item["knowledge_score"]), score)
                        item["matched_knowledge_unit_ids"].add(row["knowledge_unit_id"])
                except sqlite3.OperationalError:
                    pass

            clauses = []
            params: list[str] = []
            for term in terms:
                pattern = f"%{term}%"
                clauses.append(
                    "(subject LIKE ? OR predicate LIKE ? OR object LIKE ? OR evidence_quote LIKE ?)"
                )
                params.extend([pattern, pattern, pattern, pattern])
            like_rows = conn.execute(
                f"""
                SELECT knowledge_unit_id, paragraph_id, unit_type, subject, predicate, object, evidence_quote
                FROM knowledge_units
                WHERE {" OR ".join(clauses)}
                LIMIT ?
                """,
                [*params, candidate_limit],
            ).fetchall()

            for row in like_rows:
                if dosage_intent and row["unit_type"] != "dosage":
                    continue
                haystack = "\n".join(
                    [
                        row["unit_type"],
                        row["subject"],
                        row["predicate"],
                        row["object"],
                        row["evidence_quote"],
                    ]
                )
                matched_terms = [term for term in terms if term in haystack]
                if not matched_terms:
                    continue
                all_terms_bonus = 0.14 if len(matched_terms) == len(terms) else 0.0
                score = 0.62 + 0.08 * len(matched_terms) + all_terms_bonus
                if row["unit_type"] in {"dosage", "method", "formula_pattern"}:
                    score += 0.08
                if row["unit_type"] == "dosage" and dosage_intent:
                    gram_mentions = re.findall(r"\d+(?:\.\d+)?\s*克", row["object"])
                    score += 0.18 + 0.06 * max(0, len(gram_mentions) - 1)
                item = paragraph_scores.setdefault(
                    row["paragraph_id"],
                    {
                        "paragraph_id": row["paragraph_id"],
                        "knowledge_score": 0.0,
                        "matched_knowledge_unit_ids": set(),
                    },
                )
                item["knowledge_score"] = max(float(item["knowledge_score"]), score)
                item["matched_knowledge_unit_ids"].add(row["knowledge_unit_id"])

            ranked = sorted(
                paragraph_scores.values(),
                key=lambda item: float(item["knowledge_score"]),
                reverse=True,
            )

            results = []
            for item in ranked[:limit]:
                paragraph = conn.execute(
                    "SELECT * FROM paragraphs WHERE paragraph_id = ?", (item["paragraph_id"],)
                ).fetchone()
                if not paragraph:
                    continue
                unit_rows = conn.execute(
                    f"""
                    SELECT knowledge_unit_id, unit_type, subject, predicate, object,
                           evidence_quote, confidence
                    FROM knowledge_units
                    WHERE knowledge_unit_id IN ({",".join("?" for _ in item["matched_knowledge_unit_ids"])})
                    ORDER BY confidence DESC, unit_type, subject
                    LIMIT 5
                    """,
                    list(item["matched_knowledge_unit_ids"]),
                ).fetchall()
                matched_units = [
                    {
                        "knowledge_unit_id": row["knowledge_unit_id"],
                        "unit_type": row["unit_type"],
                        "subject": row["subject"],
                        "predicate": row["predicate"],
                        "object": row["object"],
                        "evidence_quote": row["evidence_quote"],
                        "confidence": row["confidence"],
                    }
                    for row in unit_rows
                ]
                top_unit = matched_units[0] if matched_units else {}
                results.append(
                    {
                        "paragraph_id": paragraph["paragraph_id"],
                        "doc_id": paragraph["doc_id"],
                        "source_path": public_source_path(paragraph["source_path"]),
                        "title": paragraph["title"],
                        "page_start": paragraph["page_start"],
                        "page_end": paragraph["page_end"],
                        "text": paragraph["text"],
                        "score": round(float(item["knowledge_score"]), 6),
                        "vector_score": 0.0,
                        "text_score": 0.0,
                        "knowledge_score": round(float(item["knowledge_score"]), 6),
                        "retrieval_sources": ["knowledge"],
                        "hit_count": len(matched_units),
                        "unit_types": [],
                        "matched_units": [],
                        "matched_text_terms": [],
                        "matched_knowledge_units": matched_units,
                        "knowledge_unit_id": top_unit.get("knowledge_unit_id", ""),
                        "unit_type": top_unit.get("unit_type", ""),
                        "subject": top_unit.get("subject", ""),
                        "predicate": top_unit.get("predicate", ""),
                        "object": top_unit.get("object", ""),
                        "evidence_quote": top_unit.get("evidence_quote", ""),
                    }
                )
            return results

    def search_graph_relations(
        self,
        query: str,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        """Navigate accepted entity relations back to their original paragraphs."""
        validate_runtime_limit(limit, "limit", MAX_INTERNAL_SEARCH_LIMIT)
        normalized_query = normalize_query_text(query)
        entity_terms = dedupe_keep_order(
            [
                *reliable_formula_anchors(normalized_query),
                *explicit_query_formula_terms(normalized_query),
                *direct_present_terms(normalized_query, DOMAIN_ENTITY_TERMS),
                *(term for term in SYMPTOM_TERMS if term in normalized_query),
                *(term for term in ("一钱",) if term in normalized_query),
            ]
        )[:24]
        if not entity_terms:
            return []

        with self.connect() as conn:
            tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            required = {"documents", "evidence_records", "entities", "relations", "paragraphs"}
            if not required <= tables:
                return []
            relation_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(relations)")}
            if "evidence_quote" not in relation_columns:
                return []
            placeholders = ",".join("?" for _ in entity_terms)
            rows = conn.execute(
                f"""
                SELECT r.relation_id, r.predicate, r.literal_value, r.evidence_quote, r.confidence,
                       r.extractor_version, r.review_status, r.source_layer,
                       e.entity_id, e.entity_type, e.canonical_name,
                       ev.evidence_id, ev.previous_evidence_id, ev.next_evidence_id,
                       p.*
                FROM entities e
                JOIN relations r ON r.subject_entity_id = e.entity_id
                JOIN evidence_records ev ON ev.evidence_id = r.evidence_id
                JOIN paragraphs p ON p.paragraph_id = ev.paragraph_id
                WHERE e.normalized_key IN ({placeholders})
                  AND r.review_status IN ('auto_accepted', 'reviewed')
                ORDER BY CASE r.review_status WHEN 'reviewed' THEN 0 ELSE 1 END,
                         r.confidence DESC, r.relation_id
                LIMIT ?
                """,
                [*(normalize_whitespace(term).casefold() for term in entity_terms), limit * 8],
            ).fetchall()

            grouped: dict[str, dict[str, object]] = {}
            for row in rows:
                paragraph_id = str(row["paragraph_id"])
                relation = {
                    "relation_id": row["relation_id"],
                    "entity_id": row["entity_id"],
                    "entity_type": row["entity_type"],
                    "entity_name": row["canonical_name"],
                    "predicate": row["predicate"],
                    "literal_value": row["literal_value"],
                    "evidence_quote": row["evidence_quote"],
                    "confidence": row["confidence"],
                    "extractor_version": row["extractor_version"],
                    "review_status": row["review_status"],
                    "source_layer": row["source_layer"],
                    "evidence_id": row["evidence_id"],
                }
                item = grouped.setdefault(
                    paragraph_id,
                    {
                        "paragraph_id": paragraph_id,
                        "doc_id": row["doc_id"],
                        "source_path": public_source_path(row["source_path"]),
                        "title": row["title"],
                        "page_start": row["page_start"],
                        "page_end": row["page_end"],
                        "text": row["text"],
                        "score": 0.0,
                        "vector_score": 0.0,
                        "text_score": 0.0,
                        "knowledge_score": 0.0,
                        "graph_score": 0.0,
                        "retrieval_sources": ["graph"],
                        "hit_count": 0,
                        "unit_types": [],
                        "matched_units": [],
                        "matched_text_terms": [],
                        "matched_knowledge_units": [],
                        "matched_graph_relations": [],
                        "previous_evidence_id": row["previous_evidence_id"] or "",
                        "next_evidence_id": row["next_evidence_id"] or "",
                    },
                )
                matched = item["matched_graph_relations"]
                assert isinstance(matched, list)
                matched.append(relation)
                item["hit_count"] = len(matched)
                item["graph_score"] = max(float(item["graph_score"]), float(row["confidence"]))
                item["score"] = item["graph_score"]

        core_terms = query_core_entity_terms(query)
        grounded = [
            item
            for item in grouped.values()
            if not core_terms
            or any(
                normalize_query_text(term) in normalize_query_text(str(item.get("text", "")))
                for term in core_terms
            )
        ]
        ranked = sorted(
            grounded,
            key=lambda item: (
                -len(item["matched_graph_relations"]),
                -float(item["graph_score"]),
                str(item["paragraph_id"]),
            ),
        )
        return ranked[:limit]

    def search_hybrid(
        self,
        query: str,
        limit: int = 8,
        unit_limit: int = 120,
        text_limit: int = 80,
    ) -> list[dict[str, object]]:
        validate_runtime_limit(limit, "limit", MAX_INTERNAL_SEARCH_LIMIT)
        validate_runtime_limit(unit_limit, "unit_limit", MAX_VECTOR_UNIT_LIMIT)
        validate_runtime_limit(text_limit, "text_limit", MAX_INTERNAL_SEARCH_LIMIT)
        vector_limit = min(MAX_INTERNAL_SEARCH_LIMIT, max(limit * 4, 16))
        text_channel_limit = min(MAX_INTERNAL_SEARCH_LIMIT, max(text_limit, limit * 4))
        vector_results = self.search_vector(query, limit=vector_limit, unit_limit=unit_limit)
        text_results = self.search_text(query, limit=text_channel_limit)
        knowledge_results = self.search_knowledge_units(query, limit=text_channel_limit)
        graph_results = self.search_graph_relations(query, limit=text_channel_limit)
        return fuse_ranked_channels(
            {
                "graph": graph_results,
                "vector": vector_results,
                "text": text_results,
                "knowledge": knowledge_results,
            },
            limit=limit,
            channel_weights={"graph": 0.35},
        )

    def search(
        self,
        query: str,
        limit: int = 8,
        unit_limit: int = 120,
        mode: str = "hybrid",
        include_reference_secondary: bool = False,
    ) -> list[dict[str, object]]:
        validate_runtime_limit(limit, "limit", MAX_INTERNAL_SEARCH_LIMIT)
        validate_runtime_limit(unit_limit, "unit_limit", MAX_VECTOR_UNIT_LIMIT)
        if not isinstance(include_reference_secondary, bool):
            raise TypeError("include_reference_secondary must be a boolean")
        retrieval_limit = (
            limit
            if include_reference_secondary
            else min(MAX_INTERNAL_SEARCH_LIMIT, max(limit * 8, 80))
        )
        retrieval_unit_limit = (
            unit_limit
            if include_reference_secondary
            else max(
                unit_limit,
                min(MAX_VECTOR_UNIT_LIMIT, retrieval_limit * 5),
            )
        )
        if mode == "vector":
            results = self.search_vector(
                query,
                limit=retrieval_limit,
                unit_limit=retrieval_unit_limit,
            )
        elif mode == "text":
            results = self.search_text(query, limit=retrieval_limit)
        elif mode == "knowledge":
            results = self.search_knowledge_units(query, limit=retrieval_limit)
        elif mode == "graph":
            results = self.search_graph_relations(query, limit=retrieval_limit)
        elif mode == "hybrid":
            results = self.search_hybrid(
                query,
                limit=retrieval_limit,
                unit_limit=retrieval_unit_limit,
            )
        else:
            raise ValueError(f"unsupported search mode: {mode}")
        return self._apply_source_layer_policy(results, include_reference_secondary)[:limit]


def detect_answer_intent(query: str) -> str:
    normalized = normalize_query_text(query)
    if "一钱" in normalized and ("克" in normalized or "多少" in normalized or "几" in normalized):
        return "dosage"
    if is_reference_material_query(normalized) or any(
        marker in normalized for marker in SOURCE_LOOKUP_MARKERS
    ):
        return "source_lookup"
    if any(marker in normalized for marker in ("鉴别", "比较", "区别")):
        return "comparison"
    clinical_markers = (
        "病人",
        "患者",
        "发烧",
        "發燒",
        "下利",
        "拉肚子",
        "恶心",
        "噁心",
        "建议开",
        "开什么方",
        "處方",
        "处方",
        "男性",
        "女性",
        "男患者",
        "女患者",
        "咳嗽",
        "怕冷",
    )
    if any(marker in normalized for marker in clinical_markers) or re.search(
        r"\d+\s*岁(?:\s*[男女])?", normalized
    ):
        return "clinical"
    return "general"


def is_reference_material_query(query: str) -> bool:
    normalized = normalize_query_text(query)
    return any(marker in normalized for marker in REFERENCE_MATERIAL_QUERY_MARKERS) or (
        "推荐" in normalized and "书" in normalized
    )


def direct_present_terms(text: str, terms: Iterable[str]) -> list[str]:
    normalized = normalize_query_text(text)
    occurrences: list[tuple[int, int, str]] = []
    for term in dedupe_keep_order(normalize_query_text(term) for term in terms):
        offset = normalized.find(term)
        while term and offset >= 0:
            occurrences.append((offset, offset + len(term), term))
            offset = normalized.find(term, offset + 1)
    selected: list[tuple[int, int, str]] = []
    for start, end, term in sorted(occurrences, key=lambda item: (item[0], -(item[1] - item[0]))):
        if any(start < kept_end and end > kept_start for kept_start, kept_end, _ in selected):
            continue
        selected.append((start, end, term))
    return dedupe_keep_order(term for _, _, term in selected)


def answer_anchor_terms(query: str, max_terms: int = 8) -> list[str]:
    normalized = normalize_query_text(query)
    topic_text = normalized
    for generic in sorted(ANSWER_ANCHOR_EXCLUDED_TERMS, key=len, reverse=True):
        topic_text = topic_text.replace(generic, " ")
    formulas = extract_formula_terms(topic_text)
    domain_terms = direct_present_terms(topic_text, query_domain_terms(topic_text))
    lexical_terms = [term for term in text_search_terms(topic_text) if term in topic_text]
    candidates = [*formulas, *domain_terms, *lexical_terms]
    anchors = [
        term
        for term in dedupe_keep_order(candidates)
        if len(term) >= 2 and term not in ANSWER_ANCHOR_EXCLUDED_TERMS
    ]
    if formulas or any(term not in SIX_CHANNEL_TERMS and term != "太阳病" for term in anchors):
        anchors = [term for term in anchors if term not in SIX_CHANNEL_TERMS and term != "太阳病"]
    return anchors[:max_terms]


def bounded_query_terms(
    query: str,
    terms: Iterable[str],
    right_suffixes: tuple[str, ...],
) -> list[str]:
    normalized = normalize_query_text(query)
    occurrences: list[tuple[int, int, str]] = []
    for term in sorted(set(terms), key=lambda item: (-len(item), item)):
        offset = normalized.find(term)
        while offset >= 0:
            end = offset + len(term)
            left = normalized[:offset]
            right = normalized[end:]
            left_ok = (
                not left
                or left[-1] in QUERY_BOUNDARY_CHARS
                or any(left.endswith(prefix) for prefix in FORMULA_LEFT_QUERY_PREFIXES)
            )
            right_ok = (
                not right
                or right[0] in QUERY_BOUNDARY_CHARS
                or any(right.startswith(suffix) for suffix in right_suffixes)
            )
            if left_ok and right_ok:
                occurrences.append((offset, end, term))
            offset = normalized.find(term, offset + 1)
    selected: list[tuple[int, int, str]] = []
    for start, end, formula in sorted(
        occurrences, key=lambda item: (item[0], -len(item[2]), item[2])
    ):
        if any(start < kept_end and end > kept_start for kept_start, kept_end, _ in selected):
            continue
        selected.append((start, end, formula))
    return [formula for _, _, formula in selected]


def reliable_formula_anchors(query: str) -> list[str]:
    return bounded_query_terms(query, KNOWN_FORMULA_ANCHORS, FORMULA_RIGHT_QUERY_SUFFIXES)


def known_formula_terms_in_evidence(text: str) -> list[str]:
    found = _longest_known_formula_occurrences(text)
    return dedupe_keep_order(formula for _, _, formula in found)


def _longest_known_formula_occurrences(text: str) -> list[tuple[int, int, str]]:
    normalized = normalize_query_text(text)
    occurrences: list[tuple[int, int, str]] = []
    for formula in sorted(KNOWN_FORMULA_ANCHORS, key=lambda item: (-len(item), item)):
        offset = normalized.find(formula)
        while offset >= 0:
            end = offset + len(formula)
            right = normalized[end:]
            if not any(
                right.startswith(continuation) for continuation in FORMULA_PRODUCT_CONTINUATIONS
            ):
                occurrences.append((offset, end, formula))
            offset = normalized.find(formula, offset + 1)
    selected: list[tuple[int, int, str]] = []
    formula_like_occurrences: list[tuple[int, int, str]] = []
    for candidate in extract_formula_terms(normalized):
        offset = normalized.find(candidate)
        while offset >= 0:
            formula_like_occurrences.append((offset, offset + len(candidate), candidate))
            offset = normalized.find(candidate, offset + 1)
    for occurrence in sorted(occurrences, key=lambda item: (item[0], -len(item[2]), item[2])):
        start, end, _ = occurrence
        embedded_in_known = any(
            kept_start <= start and end <= kept_end and (kept_end - kept_start) > (end - start)
            for kept_start, kept_end, _ in occurrences
        )
        embedded_in_formula_like = any(
            kept_start <= start and end <= kept_end and (kept_end - kept_start) > (end - start)
            for kept_start, kept_end, _ in formula_like_occurrences
        )
        if embedded_in_known or embedded_in_formula_like:
            continue
        selected.append(occurrence)
    return selected


def is_conservative_explicit_formula_candidate(candidate: str) -> bool:
    if not (FORMULA_MIN_CHARS <= len(candidate) <= FORMULA_MAX_CHARS):
        return False
    if candidate.startswith(EXPLICIT_FORMULA_NARRATIVE_PREFIXES):
        return False
    if any(term in candidate for term in EXPLICIT_FORMULA_FOOD_TERMS):
        return False
    suffix = next((item for item in FORMULA_SUFFIXES if candidate.endswith(item)), "")
    if not suffix:
        return False
    stem = candidate[: -len(suffix)]
    if stem.startswith(FORMULA_NUMERAL_PREFIXES):
        return True
    signal_chars = set(stem) & FORMULA_SIGNAL_CHARS
    if "加" in stem:
        left, right = stem.split("加", 1)
        if (set(left) & FORMULA_SIGNAL_CHARS) and (set(right) & FORMULA_SIGNAL_CHARS):
            return True
    if len(signal_chars) >= 2:
        return True
    return stem.startswith("通脉") and any(
        character in stem for character in FORMULA_NUMERAL_PREFIXES
    )


def explicit_query_formula_terms(query: str) -> list[str]:
    candidates = [
        candidate
        for candidate in extract_formula_terms(query)
        if candidate not in KNOWN_FORMULA_ANCHORS
        and is_conservative_explicit_formula_candidate(candidate)
    ]
    return bounded_query_terms(query, candidates, EXPLICIT_FORMULA_RIGHT_QUERY_SUFFIXES)[:8]


def literal_product_safe_term_in_text(term: str, text: str) -> bool:
    offset = text.find(term)
    while term and offset >= 0:
        right = text[offset + len(term) :]
        if not any(
            right.startswith(continuation) for continuation in FORMULA_PRODUCT_CONTINUATIONS
        ):
            return True
        offset = text.find(term, offset + 1)
    return False


def explicit_query_formulas_in_result(query: str, result: dict[str, object]) -> list[str]:
    paragraph = str(result.get("text", "")).strip()
    if not paragraph:
        return []
    return [
        term
        for term in explicit_query_formula_terms(query)
        if literal_product_safe_term_in_text(term, paragraph)
    ]


def validated_source_anchor_spans(
    text: str,
    anchors: list[str],
) -> dict[str, list[tuple[int, int]]]:
    normalized = normalize_query_text(text)
    validated: dict[str, list[tuple[int, int]]] = {}
    formula_occurrences = _longest_known_formula_occurrences(normalized)
    for anchor in dedupe_keep_order(anchors):
        if anchor not in KNOWN_FORMULA_ANCHORS and anchor not in RELIABLE_SOURCE_NAMED_TERMS:
            continue
        if anchor in KNOWN_FORMULA_ANCHORS:
            spans = [
                (start, end) for start, end, formula in formula_occurrences if formula == anchor
            ]
            if spans:
                validated[anchor] = spans
            continue
        invalid_continuations = NAMED_EVIDENCE_INVALID_CONTINUATIONS.get(anchor, ())
        offset = normalized.find(anchor)
        spans: list[tuple[int, int]] = []
        while offset >= 0:
            end = offset + len(anchor)
            right = normalized[end:]
            if not any(right.startswith(continuation) for continuation in invalid_continuations):
                spans.append((offset, end))
            offset = normalized.find(anchor, offset + 1)
        if spans:
            validated[anchor] = spans
    return validated


def source_anchor_matches_evidence(anchor: str, text: str) -> bool:
    return anchor in validated_source_anchor_spans(text, [anchor])


def evidence_has_longer_formula_topic(text: str, formula_anchors: list[str]) -> bool:
    evidence_formulas = known_formula_terms_in_evidence(text)
    return any(
        anchor != evidence_formula and anchor in evidence_formula
        for anchor in formula_anchors
        for evidence_formula in evidence_formulas
    )


def evidence_contains_source_anchors(text: str, anchors: list[str]) -> bool:
    validated = validated_source_anchor_spans(text, anchors)
    return all(anchor in validated for anchor in anchors)


def verified_unit_evidence_quotes(result: dict[str, object]) -> list[str]:
    paragraph = str(result.get("text", "")).strip()
    if not paragraph:
        return []
    quotes: list[str] = []
    for unit in result.get("matched_knowledge_units", []) or []:
        quote = str(unit.get("evidence_quote", "")).strip()
        offset = paragraph.find(quote) if quote else -1
        if offset >= 0:
            quotes.append(paragraph[offset : offset + len(quote)])
    return dedupe_keep_order(quotes)


def verified_graph_evidence_quotes(result: dict[str, object]) -> list[str]:
    paragraph = str(result.get("text", "")).strip()
    if not paragraph:
        return []
    quotes: list[str] = []
    for relation in result.get("matched_graph_relations", []) or []:
        if str(relation.get("review_status", "")) not in {"auto_accepted", "reviewed"}:
            continue
        quote = str(relation.get("evidence_quote", "")).strip()
        offset = paragraph.find(quote) if quote else -1
        if offset >= 0:
            quotes.append(paragraph[offset : offset + len(quote)])
    return dedupe_keep_order(quotes)


def source_primary_evidence_texts(result: dict[str, object]) -> list[str]:
    texts = [
        str(result.get("text", "")).strip(),
        *verified_unit_evidence_quotes(result),
        *verified_graph_evidence_quotes(result),
    ]
    return [text for text in texts if text]


def primary_evidence_text(result: dict[str, object]) -> str:
    return "\n".join(source_primary_evidence_texts(result))


def reliable_source_anchors(query: str) -> list[str]:
    normalized = normalize_query_text(query)
    formulas = reliable_formula_anchors(normalized)
    named = bounded_query_terms(normalized, RELIABLE_SOURCE_NAMED_TERMS, NAMED_RIGHT_QUERY_SUFFIXES)
    return dedupe_keep_order([*formulas, *named])[:8]


def useful_query_terms(text: str, max_terms: int = 24) -> list[str]:
    terms: list[str] = []
    terms.extend(MEASURE_TERM_RE.findall(text))
    for term in text_search_terms(text):
        normalized = term.strip()
        if len(normalized) < 2 or normalized in QUERY_EXPANSION_STOP_TERMS:
            continue
        if normalized.isdigit():
            continue
        terms.append(normalized)
    return dedupe_keep_order(terms)[:max_terms]


def evidence_sentences_for_followup(query: str, results: list[dict[str, object]]) -> list[str]:
    query_terms = set(useful_query_terms(normalize_query_text(query), max_terms=16))
    sentences: list[str] = []
    for result in results[:8]:
        for sentence in split_sentences(result_evidence_text(result)):
            sentence = sentence.strip()
            if not sentence:
                continue
            has_query_term = any(term in sentence for term in query_terms)
            has_measure = bool(MEASURE_TERM_RE.search(sentence))
            has_knowledge = any(
                str(unit.get("unit_type", "")) in sentence
                for unit in result.get("matched_knowledge_units", []) or []
            )
            if has_query_term or has_measure or has_knowledge:
                sentences.append(sentence)
    return dedupe_keep_order(sentences)


def intent_query_terms(intent: str) -> str:
    if intent == "dosage":
        return "一钱 克 钱 剂量 换算 度量衡 比例 汉制 今制 药房"
    if intent == "source_lookup":
        return "出处 原文 治法 材料 方法 来源"
    if intent == "comparison":
        return "鉴别 比较 区别"
    if intent == "clinical":
        return "方证 鉴别 症状 加减 禁忌 表证 里证 寒热 虚实"
    return ""


def normalized_clinical_terms(query: str) -> list[str]:
    normalized = normalize_query_text(query)
    terms: list[str] = []
    replacements = {
        "拉肚子": "下利",
        "腹泻": "下利",
        "噁心": "恶心",
        "呕吐": "恶心",
        "發燒": "发烧",
        "黃臭": "黄臭",
        "胃口差": "食欲差",
    }
    for term in CLINICAL_REWRITE_TERMS:
        if term in normalized:
            terms.append(replacements.get(term, term))
    if "排泄物黄臭" in normalized or "大便黄臭" in normalized or "黄臭" in normalized:
        terms.extend(["下利", "黄臭", "热利"])
    if "退烧" in normalized:
        terms.extend(["退烧", "表证"])
    return dedupe_keep_order(terms)


def clinical_rewrite_queries(query: str) -> list[str]:
    terms = normalized_clinical_terms(query)
    term_set = set(terms)
    queries: list[str] = []
    if terms:
        queries.append(" ".join(terms))

    has_diarrhea = bool(term_set & {"下利"})
    has_nausea = bool(term_set & {"恶心", "干呕"})
    has_heat_diarrhea = "热利" in term_set or "黄臭" in term_set
    has_abdominal_pain = "腹痛" in term_set
    has_epigastric = bool(term_set & {"心下痞", "肠鸣"})

    if {"有汗", "无汗"} <= term_set:
        queries.insert(0, "桂枝汤 麻黄汤 汗出 无汗 营卫 鉴别")
    if has_heat_diarrhea:
        queries.append("下利 黄臭 热利 方证 鉴别")
        queries.append("葛根黄芩黄连汤 热利 下利 表证 鉴别")
    if has_diarrhea and has_nausea:
        queries.append("下利 恶心 干呕 黄芩加半夏生姜汤 黄芩汤")
    if has_abdominal_pain and has_nausea:
        queries.append("腹痛 下利 恶心 黄芩汤 半夏 生姜 鉴别")
    if has_epigastric:
        queries.append("心下痞 肠鸣 下利 恶心 半夏泻心汤 生姜泻心汤")
    if has_diarrhea:
        queries.append("下利 方证 热利 寒利 鉴别")
    return dedupe_keep_order(query for query in queries if query.strip())


def rewritten_query_terms(query: str, intent: str) -> list[str]:
    normalized = normalize_query_text(query)
    if intent == "clinical":
        terms = normalized_clinical_terms(normalized)
        terms.extend(extract_formula_terms(normalized))
        return dedupe_keep_order(terms)

    terms = useful_query_terms(normalized, max_terms=16)
    terms = [
        term
        for term in terms
        if term not in QUERY_REWRITE_BACKGROUND_TERMS and not re.fullmatch(r"\d+\s*岁", term)
    ]
    terms.extend(extract_formula_terms(normalized))
    return dedupe_keep_order(terms)


def build_query_plan(
    query: str,
    intent: str | None = None,
    seed_results: list[dict[str, object]] | None = None,
    max_queries: int = 8,
) -> list[str]:
    normalized = normalize_query_text(query)
    resolved_intent = intent or detect_answer_intent(normalized)
    planned: list[str] = []

    source_anchors = reliable_source_anchors(normalized)
    if resolved_intent == "source_lookup" and source_anchors:
        exact_first = [" ".join(source_anchors), normalized]
        if query != normalized:
            exact_first.append(query)
        return dedupe_keep_order(exact_first)[:max_queries]

    if (
        resolved_intent == "general"
        and "学习主线" in normalized
        and "胸痹" in query_core_entity_terms(normalized)
    ):
        planned.append("胸痹心痛短气病脉证第九篇")

    query_terms = rewritten_query_terms(normalized, resolved_intent)
    if query_terms:
        planned.append(" ".join(query_terms))

    reference_material_query = is_reference_material_query(normalized)
    if reference_material_query:
        planned.append("书单 开八本书 参考 看伤寒")

    if resolved_intent == "clinical":
        planned.extend(clinical_rewrite_queries(normalized))

    intent_terms = "" if reference_material_query else intent_query_terms(resolved_intent)
    if intent_terms:
        planned.append(intent_terms)

    if seed_results:
        evidence_queries: list[str] = []
        for sentence in evidence_sentences_for_followup(query, seed_results):
            terms = useful_query_terms(sentence, max_terms=10)
            if terms:
                evidence_queries.append(" ".join(terms))

        kg_terms: list[str] = []
        for result in seed_results[:8]:
            for unit in result.get("matched_knowledge_units", []) or []:
                kg_terms.extend(
                    useful_query_terms(
                        " ".join(
                            [
                                str(unit.get("unit_type", "")),
                                str(unit.get("subject", "")),
                                str(unit.get("predicate", "")),
                                str(unit.get("object", "")),
                                str(unit.get("evidence_quote", "")),
                            ]
                        ),
                        max_terms=10,
                    )
                )
        if kg_terms:
            planned.append(" ".join(dedupe_keep_order(kg_terms)[:16]))
        planned.extend(evidence_queries[:4])

    fallback_queries: list[str] = []
    if normalized != query:
        fallback_queries.append(normalized)
    fallback_queries.append(query)

    primary = dedupe_keep_order(part.strip() for part in planned if part.strip())
    fallback = [item for item in dedupe_keep_order(fallback_queries) if item not in primary]
    if len(primary) >= max_queries:
        if fallback:
            return [*primary[: max_queries - 1], fallback[-1]]
        return primary[:max_queries]
    return [*primary, *fallback][:max_queries]


def fuse_query_rewrites(
    result_sets: list[list[dict[str, object]]],
    limit: int,
    rank_constant: int = 60,
) -> list[dict[str, object]]:
    if limit <= 0:
        return []

    max_observations = 16
    merge_fields = (
        "matched_units",
        "matched_knowledge_units",
        "matched_text_terms",
        "unit_types",
    )
    fused: dict[str, dict[str, object]] = {}
    for rewrite_index, results in enumerate(result_sets, start=1):
        seen_paragraph_ids: set[str] = set()
        for rank, result in enumerate(results, start=1):
            paragraph_id = str(result.get("paragraph_id", ""))
            if not paragraph_id:
                continue
            contributes_to_query_fusion = paragraph_id not in seen_paragraph_ids
            if contributes_to_query_fusion:
                seen_paragraph_ids.add(paragraph_id)

            rrf_increment = 1.0 / (rank_constant + rank)
            raw_score = float(result.get("score", 0.0))
            representative_key = (raw_score, -rewrite_index, -rank)
            observation: dict[str, object] = {
                "rewrite_index": rewrite_index,
                "rank": rank,
                "raw_score": raw_score,
            }
            for field in ("fusion_score", "channel_ranks"):
                if field in result:
                    observation[field] = copy.deepcopy(result[field])

            current = fused.get(paragraph_id)
            if current is None:
                current = {
                    "representative": copy.deepcopy(result),
                    "representative_key": representative_key,
                    "query_fusion_score": 0.0,
                    "retrieval_sources": [],
                    "rewrite_observations": [],
                    "rewrite_observation_count": 0,
                }
                for field in merge_fields:
                    current[field] = []
                fused[paragraph_id] = current
            elif representative_key > current["representative_key"]:
                current["representative"] = copy.deepcopy(result)
                current["representative_key"] = representative_key

            if contributes_to_query_fusion:
                current["query_fusion_score"] = float(current["query_fusion_score"]) + rrf_increment
            current["rewrite_observation_count"] = int(current["rewrite_observation_count"]) + 1
            observations = current["rewrite_observations"]
            assert isinstance(observations, list)
            if len(observations) < max_observations:
                observations.append(observation)
            elif representative_key == current["representative_key"]:
                observations[-1] = observation

            current["retrieval_sources"] = merge_unique(
                list(current["retrieval_sources"]),
                list(result.get("retrieval_sources", [])),
            )
            for field in merge_fields:
                current[field] = merge_unique(
                    list(current[field]),
                    list(result.get(field, [])),
                )

    ranked: list[dict[str, object]] = []
    for paragraph_id, state in fused.items():
        representative = state["representative"]
        assert isinstance(representative, dict)
        item = copy.deepcopy(representative)
        item["raw_score"] = float(representative.get("score", 0.0))
        item["query_fusion_score"] = float(state["query_fusion_score"])
        item["score"] = item["query_fusion_score"]
        item["retrieval_sources"] = sorted(str(source) for source in state["retrieval_sources"])
        for field in merge_fields:
            item[field] = copy.deepcopy(state[field])
        item["rewrite_observations"] = copy.deepcopy(state["rewrite_observations"])
        item["rewrite_observation_count"] = int(state["rewrite_observation_count"])
        item["paragraph_id"] = paragraph_id
        ranked.append(item)

    ranked.sort(
        key=lambda item: (
            -float(item.get("query_fusion_score", 0.0)),
            -float(item.get("raw_score", 0.0)),
            str(item.get("paragraph_id", "")),
        ),
    )
    return ranked[:limit]


def query_specific_terms(query: str) -> list[str]:
    generic_terms = {
        "方证",
        "鉴别",
        "症状",
        "加减",
        "禁忌",
        "表证",
        "里证",
        "寒热",
        "虚实",
        "寒利",
        "热利",
    }
    return [term for term in useful_query_terms(query, max_terms=24) if term not in generic_terms]


def clinical_evidence_clues(text: str) -> list[str]:
    normalized = normalize_query_text(text)
    replacements = {
        "拉肚子": "下利",
        "腹泻": "下利",
        "呕吐": "恶心",
        "胃口不好": "食欲差",
        "食欲不振": "食欲差",
    }
    clues = [
        replacements.get(term, term) for term in CLINICAL_EVIDENCE_CLUE_TERMS if term in normalized
    ]
    if "黄臭" in normalized and "下利" in normalized:
        clues.append("热利")
    return dedupe_keep_order(clues)


def clinical_core_evidence_clues(text: str) -> list[str]:
    normalized = normalize_query_text(text)
    clues = clinical_evidence_clues(normalized)
    core_terms = {normalize_query_text(term) for term in CLINICAL_CORE_EVIDENCE_CLUE_TERMS}
    return [term for term in clues if normalize_query_text(term) in core_terms]


def canonical_clinical_clues(text: str) -> list[str]:
    canonical_by_variant = {
        "怕冷": "恶寒",
        "恶寒": "恶寒",
        "有汗": "汗出",
        "汗出": "汗出",
        "无汗": "无汗",
        "腹泻": "下利",
        "拉肚子": "下利",
        "下利": "下利",
        "恶心": "恶心",
        "干呕": "恶心",
        "呕吐": "恶心",
        "发烧": "发热",
        "發燒": "发热",
        "发热": "发热",
        "咽喉疼痛": "咽痛",
        "咽痛": "咽痛",
        "胃口差": "食欲差",
        "胃口不好": "食欲差",
        "食欲差": "食欲差",
        "食欲不振": "食欲差",
    }
    normalized = normalize_query_text(text)
    observed = direct_present_terms(normalized, CLINICAL_EVIDENCE_CLUE_TERMS)
    return dedupe_keep_order(canonical_by_variant.get(clue, clue) for clue in observed)


def sweat_formula_comparison_excerpt(text: str, max_chars: int = 520) -> str:
    """Select the two source sentences that actually ground the sweat contrast."""
    sentences = split_sentences(text)
    positive = [
        sentence
        for sentence in sentences
        if "桂枝汤" in sentence and any(term in sentence for term in ("自汗", "汗出", "有汗"))
    ]
    negative = [sentence for sentence in sentences if "麻黄汤" in sentence and "无汗" in sentence]
    if not positive or not negative:
        return ""

    def pair_quality(pair: tuple[str, str]) -> tuple[int, int, int]:
        joined = " ".join(dedupe_keep_order(pair))
        differentiators = sum(
            term in joined for term in ("营卫", "自汗", "恶寒", "怕冷", "身痛", "骨节", "喘")
        )
        unsafe_actions = sum(term in joined for term in ("直接开", "放心用", "不要手软", "剂量"))
        return differentiators, -unsafe_actions, -len(joined)

    best_pair = max(
        (
            (positive_sentence, negative_sentence)
            for positive_sentence in positive
            for negative_sentence in negative
        ),
        key=pair_quality,
    )
    return evidence_quote(" ".join(dedupe_keep_order(best_pair)), max_chars=max_chars)


def is_clinical_relevant_result(result: dict[str, object]) -> bool:
    evidence = primary_evidence_text(result)
    formulas = known_formula_terms_in_evidence(evidence)
    clues = clinical_evidence_clues(evidence)
    if formulas and clues:
        return True
    if len(clinical_core_evidence_clues(evidence)) >= 2:
        return True
    return False


def has_clinical_formula_evidence(result: dict[str, object]) -> bool:
    return bool(known_formula_terms_in_evidence(primary_evidence_text(result)))


def filter_results_for_query(
    query: str, results: list[dict[str, object]], intent: str
) -> list[dict[str, object]]:
    if intent != "clinical":
        return results

    terms = query_specific_terms(query)
    formulas = reliable_formula_anchors(query)
    filtered: list[dict[str, object]] = []
    for result in results:
        evidence = primary_evidence_text(result)
        evidence_formulas = set(known_formula_terms_in_evidence(evidence))
        formula_match = bool(formulas and any(formula in evidence_formulas for formula in formulas))
        matched_terms = [term for term in terms if term in evidence]
        if (formula_match and clinical_evidence_clues(evidence)) or len(matched_terms) >= 2:
            filtered.append(result)
    return filtered


def run_query_plan_search(
    store: object,
    query_plan: list[str],
    limit: int,
    mode: str,
    intent: str,
    include_reference_secondary: bool = False,
) -> list[dict[str, object]]:
    per_query_limit = min(MAX_INTERNAL_SEARCH_LIMIT, max(limit * 2, 8))
    result_sets: list[list[dict[str, object]]] = []
    for planned_query in query_plan:
        if include_reference_secondary:
            results = store.search(
                planned_query,
                limit=per_query_limit,
                mode=mode,
                include_reference_secondary=True,
            )
        else:
            results = store.search(planned_query, limit=per_query_limit, mode=mode)
        results = filter_results_for_query(planned_query, results, intent)
        if not results:
            continue
        result_sets.append(results)
    return fuse_query_rewrites(result_sets, limit=max(limit * 4, 16))


def result_diversity_facets(result: dict[str, object], intent: str = "general") -> set[str]:
    evidence = result_evidence_text(result)
    facets: set[str] = {
        f"source:{Path(str(result.get('source_path', ''))).name}:{result.get('page_start', '')}"
    }
    for term in MEASURE_TERM_RE.findall(evidence):
        facets.add(f"measure:{term.replace(' ', '')}")
    for term in useful_query_terms(evidence, max_terms=40):
        if len(term) >= 2:
            facets.add(f"term:{term}")
    for unit in result.get("matched_knowledge_units", []) or []:
        unit_type = str(unit.get("unit_type", ""))
        subject = str(unit.get("subject", ""))
        predicate = str(unit.get("predicate", ""))
        object_text = str(unit.get("object", ""))
        if unit_type:
            facets.add(f"unit:{unit_type}")
        if subject:
            facets.add(f"subject:{subject}")
        if predicate:
            facets.add(f"predicate:{predicate}")
        for term in useful_query_terms(object_text, max_terms=12):
            facets.add(f"object:{term}")
    if intent != "general":
        facets.add(f"intent:{intent}")
    return facets


def clinical_result_quality_bonus(result: dict[str, object]) -> float:
    evidence = primary_evidence_text(result)
    formulas = known_formula_terms_in_evidence(evidence)
    core_clues = clinical_core_evidence_clues(evidence)
    bonus = 0.0
    if formulas:
        bonus += 0.18
    bonus += 0.12 * min(len(core_clues), 4)
    if {"下利", "热利"} <= set(core_clues) or {"下利", "寒利"} <= set(core_clues):
        bonus += 0.2
    if {"下利", "恶心"} <= set(core_clues) or {"下利", "干呕"} <= set(core_clues):
        bonus += 0.12
    return bonus


def select_diverse_results(
    results: list[dict[str, object]],
    limit: int,
    intent: str = "general",
) -> list[dict[str, object]]:
    if limit <= 0 or not results:
        return []
    if intent not in {"clinical", "dosage"}:
        return sorted(
            results,
            key=lambda item: (
                -float(item.get("score", 0.0)),
                str(item.get("paragraph_id", "")),
            ),
        )[:limit]
    if len(results) <= limit and intent != "clinical":
        return results[:limit]

    remaining = sorted(results, key=lambda item: float(item.get("score", 0.0)), reverse=True)
    max_score = max(float(item.get("score", 0.0)) for item in remaining) or 1.0
    selected: list[dict[str, object]] = []
    covered_facets: set[str] = set()

    while remaining and len(selected) < limit:
        best_index = 0
        best_score = -1.0
        for index, candidate in enumerate(remaining):
            facets = result_diversity_facets(candidate, intent=intent)
            new_facets = facets - covered_facets
            new_measures = {facet for facet in new_facets if facet.startswith("measure:")}
            relevance = float(candidate.get("score", 0.0)) / max_score
            novelty = min(len(new_facets), 12) / 12
            measure_bonus = 0.0
            if intent == "dosage":
                measure_bonus = 0.35 * min(len(new_measures), 3)
            source_bonus = (
                0.08
                if not any(
                    Path(str(item.get("source_path", ""))).name
                    == Path(str(candidate.get("source_path", ""))).name
                    for item in selected
                )
                else 0.0
            )
            clinical_bonus = (
                clinical_result_quality_bonus(candidate) if intent == "clinical" else 0.0
            )
            candidate_score = (
                relevance + 0.45 * novelty + measure_bonus + source_bonus + clinical_bonus
            )
            if candidate_score > best_score:
                best_score = candidate_score
                best_index = index
        chosen = remaining.pop(best_index)
        selected.append(chosen)
        covered_facets.update(result_diversity_facets(chosen, intent=intent))

    return selected


def citation_label(result: dict[str, object]) -> str:
    source_name = Path(str(result.get("source_path", ""))).name
    page_start = result.get("page_start", "")
    page_end = result.get("page_end", page_start)
    page = f"p{page_start}" if page_start == page_end else f"p{page_start}-{page_end}"
    label = f"{source_name} {page}".strip()
    if result.get("source_layer") == "reference_secondary":
        return f"关联参考资料（非倪海厦著作） · {label}"
    return label


def _runtime_reference_manifest(db_path: Path) -> dict[str, object]:
    manifest_path = db_path.parent / "manifest.json"
    try:
        if not manifest_path.is_file() or manifest_path.stat().st_size > MAX_RUNTIME_MANIFEST_BYTES:
            return {}
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _manifest_text(value: object, max_chars: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return normalize_whitespace(value)[:max_chars]


def _manifest_string_list(value: object, max_items: int = 20, max_chars: int = 160) -> list[str]:
    if not isinstance(value, list):
        return []
    return dedupe_keep_order(
        text for raw in value[:max_items] if (text := _manifest_text(raw, max_chars=max_chars))
    )


def linked_reference_materials(
    db_path: Path,
    citations: list[dict[str, object]],
    limit: int = 8,
) -> list[dict[str, object]]:
    """Resolve reference cards only when a visible primary citation triggers a catalog link."""
    if not citations or limit <= 0:
        return []
    limit = min(limit, MAX_LINKED_REFERENCE_MATERIALS)
    manifest = _runtime_reference_manifest(db_path)
    raw_evidence = manifest.get("reference_link_evidence")
    raw_documents = manifest.get("documents")
    if not isinstance(raw_evidence, list) or not isinstance(raw_documents, list):
        return []

    evidence_by_id: dict[str, dict[str, object]] = {}
    for raw in raw_evidence[:MAX_REFERENCE_LINK_EVIDENCE]:
        if not isinstance(raw, dict):
            continue
        evidence_id = _manifest_text(raw.get("evidence_id"), max_chars=160)
        raw_source_path = _manifest_text(raw.get("logical_source_path"), max_chars=500)
        source_path = public_source_path(raw_source_path) if raw_source_path else ""
        page = raw.get("page")
        if (
            not evidence_id
            or not source_path
            or isinstance(page, bool)
            or not isinstance(page, int)
            or page < 1
        ):
            continue
        evidence_by_id[evidence_id] = {
            "evidence_id": evidence_id,
            "source_path": source_path,
            "page": page,
            "evidence_quote": _manifest_text(raw.get("evidence_quote"), max_chars=800),
        }
    if not evidence_by_id:
        return []

    triggered: dict[str, dict[str, object]] = {}
    for citation in citations[:MAX_PUBLIC_ANSWER_LIMIT]:
        if not isinstance(citation, dict) or citation.get("source_layer") not in {
            "course_primary",
            "classic_primary",
        }:
            continue
        raw_source_path = _manifest_text(citation.get("source_path"), max_chars=500)
        source_path = public_source_path(raw_source_path) if raw_source_path else ""
        page_start = citation.get("page_start")
        page_end = citation.get("page_end", page_start)
        if (
            not source_path
            or isinstance(page_start, bool)
            or not isinstance(page_start, int)
            or isinstance(page_end, bool)
            or not isinstance(page_end, int)
        ):
            continue
        source_key = source_catalog_key(source_path)
        for evidence_id, evidence in evidence_by_id.items():
            if (
                source_catalog_key(str(evidence["source_path"])) == source_key
                and page_start <= int(evidence["page"]) <= page_end
            ):
                triggered.setdefault(
                    evidence_id,
                    {
                        **evidence,
                        "citation_index": citation.get("index"),
                        "citation_label": _manifest_text(citation.get("label"), max_chars=300),
                        "evidence_quote": _manifest_text(
                            citation.get("evidence_quote") or evidence.get("evidence_quote"),
                            max_chars=800,
                        ),
                    },
                )
    if not triggered:
        return []

    linked: list[dict[str, object]] = []
    for raw in raw_documents[:500]:
        if not isinstance(raw, dict) or raw.get("source_layer") != "reference_secondary":
            continue
        relation_ids = _manifest_string_list(raw.get("relation_evidence_ids"))
        trigger_id = next((item for item in relation_ids if item in triggered), "")
        if not trigger_id:
            continue
        raw_source_path = _manifest_text(raw.get("source_path"), max_chars=500)
        source_path = public_source_path(raw_source_path) if raw_source_path else ""
        if not source_path:
            continue
        relation_type = _manifest_text(raw.get("relation_type"), max_chars=120)
        edition_status = _manifest_text(raw.get("edition_verification"), max_chars=160)
        title = _manifest_text(raw.get("display_title"), max_chars=240) or Path(source_path).stem
        linked.append(
            {
                "title": title,
                "source_path": source_path,
                "source_layer": "reference_secondary",
                "label": f"课程提到的关联资料（非倪海厦著作） · {Path(source_path).name}",
                "relation_type": relation_type,
                "relation_label": REFERENCE_RELATION_LABELS.get(relation_type, "关联参考资料"),
                "authorship": _manifest_text(raw.get("authorship"), max_chars=120),
                "edition_verification": edition_status,
                "edition_label": REFERENCE_EDITION_LABELS.get(edition_status, edition_status),
                "quality_flags": _manifest_string_list(raw.get("quality_flags"), max_items=12),
                "trigger": triggered[trigger_id],
            }
        )
        if len(linked) >= limit:
            break
    return linked


def _bounded_original_text(value: object, max_chars: int = MAX_EVIDENCE_CONTEXT_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        return ""
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + "…"


def _evidence_context_record(row: sqlite3.Row) -> dict[str, object]:
    source_path = public_source_path(row["logical_source_path"])
    locator = _manifest_text(row["locator"], max_chars=80)
    page_start = row["page_start"]
    page_end = row["page_end"]
    label = f"{Path(source_path).name} {locator}".strip()
    return {
        "evidence_id": _manifest_text(row["evidence_id"], max_chars=160),
        "paragraph_id": _manifest_text(row["paragraph_id"], max_chars=160),
        "source_path": source_path,
        "source_layer": _manifest_text(row["source_layer"], max_chars=80),
        "title": _manifest_text(
            row["paragraph_title"] or row["canonical_title"],
            max_chars=300,
        ),
        "locator": locator,
        "page_start": page_start
        if isinstance(page_start, int) and not isinstance(page_start, bool)
        else "",
        "page_end": page_end
        if isinstance(page_end, int) and not isinstance(page_end, bool)
        else "",
        "label": label,
        "evidence_quote": evidence_quote(str(row["original_text"]), max_chars=260),
        "paragraph_text": _bounded_original_text(row["original_text"]),
    }


def enrich_results_with_evidence_context(
    db_path: Path,
    results: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Attach stable evidence IDs and one-hop previous/current/next source records."""
    enriched = [dict(result) for result in results]
    if not enriched or not db_path.is_file():
        return enriched
    paragraph_ids = dedupe_keep_order(
        str(result.get("paragraph_id", ""))
        for result in enriched[:MAX_EVIDENCE_CONTEXT_RESULTS]
        if str(result.get("paragraph_id", ""))
    )
    if not paragraph_ids:
        return enriched

    select_sql = """
        SELECT ev.evidence_id, ev.paragraph_id, ev.locator, ev.original_text,
               ev.previous_evidence_id, ev.next_evidence_id,
               d.logical_source_path, d.canonical_title, d.source_layer,
               p.title AS paragraph_title, p.page_start, p.page_end
        FROM evidence_records ev
        JOIN documents d ON d.document_id = ev.document_id
        JOIN paragraphs p ON p.paragraph_id = ev.paragraph_id
    """
    try:
        with LocalVectorStore(db_path).connect() as conn:
            tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {"documents", "evidence_records", "paragraphs"} <= tables:
                return enriched
            placeholders = ",".join("?" for _ in paragraph_ids)
            current_rows = conn.execute(
                select_sql + f" WHERE ev.paragraph_id IN ({placeholders})",
                paragraph_ids,
            ).fetchall()
            neighbor_ids = dedupe_keep_order(
                str(row[key])
                for row in current_rows
                for key in ("previous_evidence_id", "next_evidence_id")
                if row[key]
            )
            neighbor_rows: list[sqlite3.Row] = []
            if neighbor_ids:
                neighbor_placeholders = ",".join("?" for _ in neighbor_ids)
                neighbor_rows = conn.execute(
                    select_sql + f" WHERE ev.evidence_id IN ({neighbor_placeholders})",
                    neighbor_ids,
                ).fetchall()
    except (OSError, sqlite3.DatabaseError):
        return enriched

    rows_by_evidence = {str(row["evidence_id"]): row for row in [*current_rows, *neighbor_rows]}
    current_by_paragraph = {str(row["paragraph_id"]): row for row in current_rows}
    output: list[dict[str, object]] = []
    for result in enriched:
        row = current_by_paragraph.get(str(result.get("paragraph_id", "")))
        if row is None:
            output.append(result)
            continue
        current = _evidence_context_record(row)
        previous_row = rows_by_evidence.get(str(row["previous_evidence_id"] or ""))
        next_row = rows_by_evidence.get(str(row["next_evidence_id"] or ""))
        result.update(
            {
                "evidence_id": current["evidence_id"],
                "locator": current["locator"],
                "previous_evidence_id": str(row["previous_evidence_id"] or ""),
                "next_evidence_id": str(row["next_evidence_id"] or ""),
                "context_navigation": {
                    "previous": _evidence_context_record(previous_row) if previous_row else None,
                    "current": current,
                    "next": _evidence_context_record(next_row) if next_row else None,
                },
            }
        )
        output.append(result)
    return output


def dosage_evidence_snippet(text: str, max_chars: int = 520) -> str:
    if len(text) <= max_chars:
        return text
    anchor_offsets = [offset for offset in (text.find("一钱"), text.find("1钱")) if offset >= 0]
    gram_match = MEASURE_TERM_RE.search(text)
    offsets = anchor_offsets[:]
    if gram_match is not None:
        offsets.append(gram_match.start())
    if not offsets:
        return evidence_quote(text, max_chars=max_chars)
    center = min(offsets)
    start = max(0, center - 60)
    end = min(len(text), center + max_chars - 10)
    return evidence_quote(text[start:end], max_chars=max_chars)


def anchor_evidence_snippet(text: str, anchors: list[str], max_chars: int = 220) -> str:
    validated = validated_source_anchor_spans(text, anchors)
    sentence_matches = list(SENTENCE_RE.finditer(text))
    for match in sentence_matches:
        if all(
            any(
                match.start() <= start and end <= match.end()
                for start, end in validated.get(anchor, [])
            )
            for anchor in anchors
        ):
            sentence = match.group(0).strip()
            if len(sentence) <= max_chars:
                return sentence
    selected: list[str] = []
    for anchor in anchors:
        for start, end in validated.get(anchor, []):
            match = next(
                (item for item in sentence_matches if item.start() <= start and end <= item.end()),
                None,
            )
            if match is not None:
                selected.append(match.group(0).strip())
                break
    selected = dedupe_keep_order(selected)
    joined = " ".join(selected)
    if selected and len(joined) <= max_chars and evidence_contains_source_anchors(joined, anchors):
        return joined
    offsets = [validated.get(anchor, [(-1, -1)])[0][0] for anchor in anchors]
    if offsets and all(offset >= 0 for offset in offsets):
        span_start = min(offsets)
        span_end = max(offset + len(anchor) for offset, anchor in zip(offsets, anchors))
        if span_end - span_start <= max_chars:
            context = max_chars - (span_end - span_start)
            start = max(0, span_start - context // 2)
            end = min(len(text), start + max_chars)
            start = max(0, end - max_chars)
            return text[start:end].strip()
    present = dedupe_keep_order(anchor for offset, anchor in zip(offsets, anchors) if offset >= 0)
    separator = " … "
    minimum = sum(len(anchor) for anchor in present) + len(separator) * max(0, len(present) - 1)
    if not present:
        return ""
    if minimum > max_chars:
        raise ValueError("source anchor names exceed citation excerpt budget")
    remaining = max_chars - minimum
    shared_context, extra = divmod(remaining, len(present))
    snippets: list[str] = []
    for index, anchor in enumerate(present):
        budget = len(anchor) + shared_context + (1 if index < extra else 0)
        offset = validated[anchor][0][0]
        context = budget - len(anchor)
        start = max(0, offset - context // 2)
        end = min(len(text), start + budget)
        start = max(0, end - budget)
        snippets.append(text[start:end].strip())
    return separator.join(snippets)


def literal_term_evidence_snippet(text: str, terms: list[str], max_chars: int = 220) -> str:
    present = [term for term in terms if literal_product_safe_term_in_text(term, text)]
    if not present:
        return ""
    for match in SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        if any(literal_product_safe_term_in_text(term, sentence) for term in present):
            if len(sentence) <= max_chars:
                return sentence
    term = present[0]
    offset = text.find(term)
    context = max_chars - len(term)
    start = max(0, offset - context // 2)
    end = min(len(text), start + max_chars)
    start = max(0, end - max_chars)
    return text[start:end].strip()


def core_terms_evidence_snippet(
    text: str,
    terms: list[str],
    *,
    require_all: bool = False,
    max_chars: int = 280,
) -> str:
    normalized_terms = dedupe_keep_order(normalize_query_text(term) for term in terms)
    if not normalized_terms:
        return ""
    clue_terms = (
        "有汗",
        "自汗",
        "流汗",
        "汗出",
        "无汗",
        "悪风",
        "悪寒",
        "怕冷",
        "喘",
        "身痛",
        "脉浮",
        "脉紧",
    )
    candidates: list[tuple[int, int, int, str]] = []
    for sentence in split_sentences(text):
        normalized_sentence = normalize_query_text(sentence)
        hit_count = sum(term in normalized_sentence for term in normalized_terms)
        if hit_count and (not require_all or hit_count == len(normalized_terms)):
            clue_count = sum(clue in normalized_sentence for clue in clue_terms)
            candidates.append((hit_count, clue_count, -len(sentence), sentence))

    def distributed_term_sentences() -> tuple[int, str]:
        selected: list[str] = []
        total_clues = 0
        for term in normalized_terms:
            term_candidates: list[tuple[int, int, str]] = []
            for sentence in split_sentences(text):
                normalized_sentence = normalize_query_text(sentence)
                if term not in normalized_sentence:
                    continue
                clue_count = sum(clue in normalized_sentence for clue in clue_terms)
                term_candidates.append((clue_count, -len(sentence), sentence))
            if not term_candidates:
                return 0, ""
            term_candidates.sort(reverse=True)
            total_clues += term_candidates[0][0]
            selected.append(term_candidates[0][2])
        joined = " ".join(dedupe_keep_order(selected))
        return total_clues, evidence_quote(joined, max_chars=max_chars)

    if not candidates:
        if not require_all:
            return ""
        return distributed_term_sentences()[1]
    candidates.sort(reverse=True)
    if require_all and candidates[0][1] == 0:
        distributed_clues, distributed = distributed_term_sentences()
        if distributed_clues and distributed:
            return distributed
    return evidence_quote(candidates[0][3], max_chars=max_chars)


def citation_evidence_for_result(
    result: dict[str, object],
    intent: str = "general",
    query: str = "",
) -> str:
    if intent == "dosage":
        evidence_parts: list[str] = []
        for sentence in split_sentences(str(result.get("text", ""))):
            if ("一钱" in sentence or "1钱" in sentence) and (
                "克" in sentence or "比例" in sentence
            ):
                evidence_parts.append(sentence)
        for quote in verified_unit_evidence_quotes(result):
            if "一钱" in quote or "1钱" in quote or "克" in quote:
                evidence_parts.append(quote)
        for quote in verified_graph_evidence_quotes(result):
            if "一钱" in quote or "1钱" in quote or "克" in quote:
                evidence_parts.append(quote)
        evidence = " ".join(dedupe_keep_order(evidence_parts))
        if evidence:
            return dosage_evidence_snippet(evidence)

    unit_quotes = dedupe_keep_order(
        [*verified_graph_evidence_quotes(result), *verified_unit_evidence_quotes(result)]
    )
    paragraph = str(result.get("text", "")).strip()
    if (
        intent == "general"
        and "春夏秋冬" in normalize_query_text(query)
        and "养生" in normalize_query_text(query)
    ):
        mapping_match = re.search(
            r"春天就是肝脏[^。！？!?]{0,80}?夏天就是心脏[^。！？!?]{0,80}?"
            r"秋天是肺脏[^。！？!?]{0,80}?冬天是肾脏",
            paragraph,
        )
        if mapping_match:
            return mapping_match.group(0) + "。"
        for sentence in split_sentences(paragraph):
            if "长夏" in sentence and "节气" in sentence:
                return evidence_quote(sentence, max_chars=280)
    if intent == "clinical":
        if {"有汗", "无汗"} <= set(query_core_entity_terms(query)):
            for quote in [*unit_quotes, paragraph]:
                snippet = sweat_formula_comparison_excerpt(quote)
                if snippet:
                    return snippet
        formula_anchors = reliable_formula_anchors(query)
        if formula_anchors:
            for quote in unit_quotes:
                if evidence_contains_source_anchors(quote, formula_anchors):
                    return anchor_evidence_snippet(quote, formula_anchors)
            if evidence_contains_source_anchors(paragraph, formula_anchors):
                return anchor_evidence_snippet(paragraph, formula_anchors)
    if intent == "source_lookup":
        if is_reference_material_query(query) and paragraph:
            offsets = [
                paragraph.find(marker)
                for marker in ("开八本书", "书单")
                if paragraph.find(marker) >= 0
            ]
            if offsets:
                start = max(0, min(offsets) - 40)
                return evidence_quote(paragraph[start : start + 520], max_chars=520)
        anchors = reliable_source_anchors(query)
        if anchors:
            for quote in unit_quotes:
                if evidence_contains_source_anchors(quote, anchors):
                    return anchor_evidence_snippet(quote, anchors)
            if paragraph and evidence_contains_source_anchors(paragraph, anchors):
                return anchor_evidence_snippet(paragraph, anchors)
        explicit_terms = explicit_query_formula_terms(query) if not anchors else []
        if explicit_terms:
            for quote in unit_quotes:
                snippet = literal_term_evidence_snippet(quote, explicit_terms)
                if snippet:
                    return snippet
            snippet = literal_term_evidence_snippet(paragraph, explicit_terms)
            if snippet:
                return snippet
    core_terms = query_core_entity_terms(query)
    if core_terms:
        require_all = query_requires_all_core_terms(query, intent)
        for quote in unit_quotes:
            snippet = core_terms_evidence_snippet(
                quote,
                core_terms,
                require_all=require_all,
            )
            if snippet:
                return snippet
        snippet = core_terms_evidence_snippet(
            paragraph,
            core_terms,
            require_all=require_all,
        )
        if snippet:
            return snippet
    if unit_quotes:
        return unit_quotes[0]
    return evidence_quote(paragraph, max_chars=220).strip()


def citation_retrieval_provenance(result: dict[str, object]) -> dict[str, object]:
    allowed_channels = {"vector", "text", "knowledge", "graph"}
    raw_sources = result.get("retrieval_sources")
    channels = (
        dedupe_keep_order(
            source
            for source in raw_sources[:12]
            if isinstance(source, str) and source in allowed_channels
        )
        if type(raw_sources) in {list, tuple}
        else []
    )
    raw_ranks = result.get("channel_ranks")
    channel_ranks: dict[str, int] = {}
    if type(raw_ranks) is dict:
        for channel in sorted(allowed_channels):
            rank = raw_ranks.get(channel)
            if isinstance(rank, int) and not isinstance(rank, bool) and 0 < rank <= 1_000_000:
                channel_ranks[channel] = rank
    channels = dedupe_keep_order([*channels, *channel_ranks])
    return {"channels": channels, "channel_ranks": channel_ranks}


def build_citations(
    results: list[dict[str, object]],
    max_citations: int = 6,
    intent: str = "general",
    query: str = "",
) -> list[dict[str, object]]:
    citations: list[dict[str, object]] = []
    seen: set[tuple[str, object, str]] = set()
    for result in results:
        evidence = citation_evidence_for_result(result, intent=intent, query=query)
        if not evidence:
            continue
        source_path = public_source_path(result.get("source_path", ""))
        key = (source_path, result.get("page_start"), evidence)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            {
                "index": len(citations) + 1,
                "paragraph_id": result.get("paragraph_id", ""),
                "source_path": source_path,
                "title": result.get("title", ""),
                "page_start": result.get("page_start", ""),
                "page_end": result.get("page_end", result.get("page_start", "")),
                "label": citation_label({**result, "source_path": source_path}),
                "evidence_quote": evidence,
                "paragraph_text": str(result.get("text", "")),
                "evidence_id": result.get("evidence_id", ""),
                "locator": result.get("locator", ""),
                "previous_evidence_id": result.get("previous_evidence_id", ""),
                "next_evidence_id": result.get("next_evidence_id", ""),
                "context_navigation": copy.deepcopy(result.get("context_navigation") or {}),
                "retrieval_provenance": citation_retrieval_provenance(result),
                "source_layer": result.get("source_layer", ""),
            }
        )
        if len(citations) >= max_citations:
            break
    return citations


def knowledge_relations(
    db_path: Path | str,
    entity_name: str,
    limit: int = 20,
) -> list[dict[str, object]]:
    """Return evidence-grounded relation candidates from the normalized schema."""
    bounded_limit = min(max(int(limit), 0), 100)
    normalized_name = normalize_whitespace(entity_name).casefold()
    path = Path(db_path)
    if not normalized_name or bounded_limit == 0 or not path.is_file():
        return []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        required = {"documents", "evidence_records", "entities", "relations"}
        if not required <= tables:
            return []
        rows = conn.execute(
            """
            SELECT r.relation_id, e.entity_id, e.entity_type, e.canonical_name,
                   r.predicate, r.literal_value, r.confidence,
                   r.extraction_method, r.extractor_version, r.review_status,
                   r.source_layer, ev.evidence_id, ev.paragraph_id, ev.locator,
                   ev.original_text, ev.previous_evidence_id, ev.next_evidence_id,
                   d.canonical_title, d.logical_source_path
            FROM entities e
            JOIN relations r ON r.subject_entity_id = e.entity_id
            JOIN evidence_records ev ON ev.evidence_id = r.evidence_id
            JOIN documents d ON d.document_id = ev.document_id
            WHERE e.normalized_key = ? AND r.review_status != 'rejected'
            ORDER BY CASE r.review_status WHEN 'reviewed' THEN 0 ELSE 1 END,
                     r.confidence DESC, r.relation_id
            LIMIT ?
            """,
            (normalized_name, bounded_limit),
        ).fetchall()
    return [
        {
            "relation_id": row["relation_id"],
            "entity_id": row["entity_id"],
            "entity_type": row["entity_type"],
            "entity_name": row["canonical_name"],
            "predicate": row["predicate"],
            "literal_value": row["literal_value"],
            "confidence": row["confidence"],
            "extraction_method": row["extraction_method"],
            "extractor_version": row["extractor_version"],
            "review_status": row["review_status"],
            "source_layer": row["source_layer"],
            "evidence_id": row["evidence_id"],
            "paragraph_id": row["paragraph_id"],
            "locator": row["locator"],
            "paragraph_text": row["original_text"],
            "previous_evidence_id": row["previous_evidence_id"] or "",
            "next_evidence_id": row["next_evidence_id"] or "",
            "title": row["canonical_title"],
            "source_path": public_source_path(row["logical_source_path"]),
        }
        for row in rows
    ]


def result_evidence_text(result: dict[str, object]) -> str:
    parts = [str(result.get("title", "")), str(result.get("text", ""))]
    for unit in result.get("matched_knowledge_units", []) or []:
        parts.extend(
            [
                str(unit.get("unit_type", "")),
                str(unit.get("subject", "")),
                str(unit.get("predicate", "")),
                str(unit.get("object", "")),
                str(unit.get("evidence_quote", "")),
            ]
        )
    return "\n".join(parts)


def filter_results_for_intent(
    query: str,
    intent: str,
    results: list[dict[str, object]],
) -> list[dict[str, object]]:
    if intent == "dosage":
        return [result for result in results if is_dosage_relevant_result(result)]
    elif intent == "source_lookup":
        if is_reference_material_query(query):
            return [
                result
                for result in results
                if "开八本书" in primary_evidence_text(result)
                or (
                    "书单" in primary_evidence_text(result)
                    and "参考" in primary_evidence_text(result)
                )
            ]
        anchors = reliable_source_anchors(query)
        if not anchors:
            explicit_terms = explicit_query_formula_terms(query)
            if not explicit_terms:
                return results
            return [
                result
                for result in results
                if all(
                    literal_product_safe_term_in_text(term, primary_evidence_text(result))
                    for term in explicit_terms
                )
            ]
        formula_anchors = [anchor for anchor in anchors if anchor in KNOWN_FORMULA_ANCHORS]
        return [
            result
            for result in results
            if any(
                evidence_contains_source_anchors(text, anchors)
                for text in source_primary_evidence_texts(result)
            )
            and not (
                formula_anchors
                and evidence_has_longer_formula_topic(
                    primary_evidence_text(result),
                    formula_anchors,
                )
            )
        ]
    elif intent == "clinical":
        query_core_terms = set(query_core_entity_terms(query))
        if {"有汗", "无汗"} <= query_core_terms:
            sweat_comparison_results: list[tuple[int, dict[str, object]]] = []
            for result in results:
                evidence = primary_evidence_text(result)
                snippet = sweat_formula_comparison_excerpt(evidence)
                if snippet:
                    quality = sum(
                        term in snippet
                        for term in ("营卫", "自汗", "恶寒", "怕冷", "身痛", "骨节", "喘")
                    )
                    sweat_comparison_results.append((quality, result))
            if sweat_comparison_results:
                return [
                    result
                    for _, result in sorted(
                        sweat_comparison_results,
                        key=lambda item: (
                            -item[0],
                            -float(item[1].get("score", 0.0)),
                            str(item[1].get("paragraph_id", "")),
                        ),
                    )
                ]
        query_formulas = reliable_formula_anchors(query)
        if query_formulas:
            formula_focused = [
                result
                for result in results
                if any(
                    evidence_contains_source_anchors(text, query_formulas)
                    for text in source_primary_evidence_texts(result)
                )
            ]
            if formula_focused:
                return formula_focused
        query_clues = set(canonical_clinical_clues(query))
        clinical_filtered: list[dict[str, object]] = []
        for result in results:
            if not is_clinical_relevant_result(result):
                continue
            evidence = primary_evidence_text(result)
            evidence_formulas = set(known_formula_terms_in_evidence(evidence))
            formula_match = bool(
                query_formulas and any(formula in evidence_formulas for formula in query_formulas)
            )
            clue_match = bool(query_clues & set(canonical_clinical_clues(evidence)))
            if formula_match or clue_match:
                clinical_filtered.append(result)
        formula_filtered = [
            result for result in clinical_filtered if has_clinical_formula_evidence(result)
        ]
        return formula_filtered or clinical_filtered
    elif (
        intent == "general"
        and "学习主线" in normalize_query_text(query)
        and "胸痹" in query_core_entity_terms(query)
    ):
        chapter_results = [
            result
            for result in results
            if "胸痹" in primary_evidence_text(result) and "第九篇" in primary_evidence_text(result)
        ]
        if chapter_results:
            return chapter_results
        return [result for result in results if "胸痹" in primary_evidence_text(result)]
    elif (
        intent == "general"
        and "春夏秋冬" in normalize_query_text(query)
        and "养生" in normalize_query_text(query)
    ):
        return [
            result
            for result in results
            if (
                any(
                    "长夏" in sentence and "节气" in sentence
                    for sentence in split_sentences(primary_evidence_text(result))
                )
                or all(
                    term in primary_evidence_text(result)
                    for term in ("春天", "肝脏", "夏天", "心脏", "秋天", "肺脏", "冬天", "肾脏")
                )
            )
        ]
    else:
        core_terms = query_core_entity_terms(query)
        if not core_terms:
            return results
        require_all = query_requires_all_core_terms(query, intent)
        filtered = []
        for result in results:
            evidence = normalize_query_text(primary_evidence_text(result))
            matches = [term for term in core_terms if normalize_query_text(term) in evidence]
            if (require_all and len(matches) == len(core_terms)) or (not require_all and matches):
                filtered.append(result)
        return filtered


def is_dosage_relevant_result(result: dict[str, object]) -> bool:
    text = primary_evidence_text(result)
    has_anchor = "一钱" in text or "1钱" in text
    has_measure = bool(MEASURE_TERM_RE.search(text))
    has_context = any(term in text for term in ("剂量", "换算", "度量衡", "比例", "汉制", "今制"))
    if "大约一钱的量" in text or "大约1钱的量" in text:
        return has_context and "比例" in text
    if has_anchor and (has_measure or has_context):
        return True
    if "比例" in text and any(term in text for term in ("方", "汤", "剂量", "处方")):
        return True
    return False


def collect_matched_knowledge_units(results: list[dict[str, object]]) -> list[dict[str, object]]:
    units: list[dict[str, object]] = []
    seen: set[str] = set()
    for result in results:
        for unit in result.get("matched_knowledge_units", []) or []:
            key = "|".join(
                [
                    str(unit.get("unit_type", "")),
                    str(unit.get("subject", "")),
                    str(unit.get("predicate", "")),
                    str(unit.get("object", "")),
                    str(unit.get("evidence_quote", "")),
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            enriched = dict(unit)
            source_path = public_source_path(result.get("source_path", ""))
            page_start = result.get("page_start")
            enriched.setdefault("paragraph_id", result.get("paragraph_id", ""))
            enriched["source_path"] = public_source_path(enriched.get("source_path") or source_path)
            enriched.setdefault("title", result.get("title", ""))
            enriched.setdefault("page_start", page_start)
            enriched.setdefault("page_end", result.get("page_end", page_start))
            if source_path and page_start:
                enriched.setdefault("label", f"{Path(source_path).name} p{page_start}")
            units.append(enriched)
    return units


def mermaid_label(text: str, max_chars: int = 42) -> str:
    cleaned = re.sub(r"[\[\]{}\"<>|]", " ", normalize_whitespace(text))
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1] + "…"


def build_differentiation_flow(
    query: str,
    guide_nodes: list[dict[str, object]],
) -> dict[str, object]:
    if not guide_nodes:
        return {"format": "mermaid", "mermaid": "", "text_steps": []}
    unique_nodes: list[dict[str, object]] = []
    seen_labels: set[tuple[str, str]] = set()
    for node in guide_nodes:
        label = normalize_whitespace(str(node.get("label", "")))
        badge = normalize_whitespace(str(node.get("badge") or node.get("node_type") or ""))
        key = (badge, label)
        if not label or key in seen_labels:
            continue
        seen_labels.add(key)
        unique_nodes.append(node)
    if not unique_nodes:
        return {"format": "mermaid", "mermaid": "", "text_steps": []}
    primary = unique_nodes[0]
    lines = [
        "flowchart TD",
        f'  A["问题线索: {mermaid_label(query)}"] --> B["导图定位: {mermaid_label(str(primary.get("path", "")))}"]',
    ]
    text_steps = [
        f"问题线索：{normalize_whitespace(query)}",
        f"导图定位：{primary.get('path', primary.get('label', ''))}",
    ]
    previous = "B"
    for index, node in enumerate(unique_nodes[:4], start=1):
        node_id = f"C{index}"
        label = f"{node.get('badge') or node.get('node_type')}: {node.get('label')}"
        lines.append(f'  {previous} --> {node_id}["{mermaid_label(str(label))}"]')
        text_steps.append(f"{node.get('badge') or node.get('node_type')}：{node.get('label')}")
        previous = node_id
    lines.append(f'  {previous} --> Z["核对 PDF 原文依据"]')
    text_steps.append("核对 PDF 原文依据")
    return {
        "format": "mermaid",
        "mermaid": "\n".join(lines),
        "text_steps": text_steps,
    }


def build_followup_questions(
    query: str,
    intent: str,
    guide_nodes: list[dict[str, object]],
    related_knowledge_units: list[dict[str, object]],
) -> list[str]:
    if intent != "clinical":
        return []

    def clue_terms(text: str) -> list[str]:
        return direct_present_terms(text, CLINICAL_EVIDENCE_CLUE_TERMS)

    items = clue_terms(normalize_query_text(query))
    for node in guide_nodes[:6]:
        label = normalize_whitespace(str(node.get("label", "")))
        items.extend(clue_terms(str(node.get("content", ""))))
        items.extend(clue_terms(str(node.get("path", ""))))
        if label:
            items.append(label)
    for unit in related_knowledge_units[:6]:
        unit_text = "\n".join(
            str(unit.get(field, ""))
            for field in ("subject", "predicate", "object", "evidence_quote")
        )
        items.extend(clue_terms(unit_text))
    items = [item for item in dedupe_keep_order(items) if item][:6]
    return [f"还需要进一步核对“{item}”吗？" for item in items]


def collect_gram_values(results: list[dict[str, object]]) -> list[str]:
    def extract_conversion_values(text: str) -> list[str]:
        values: list[str] = []
        anchor_patterns = (
            r"(?:一钱|1钱)\s*(?:等于|是|约|算|当|大概|大约)?\s*(\d+(?:\.\d+)?\s*克)",
            r"(?:一钱|1钱)[^。！？!?；;，,]{0,16}?(\d+(?:\.\d+)?\s*克)",
        )
        for pattern in anchor_patterns:
            values.extend(re.findall(pattern, text))
        if ("一钱的量" in text or "1钱的量" in text) and any(
            marker in text for marker in ("也就是说", "按照比例", "加起来是")
        ):
            anchor_offsets = [
                offset for offset in (text.find("一钱的量"), text.find("1钱的量")) if offset >= 0
            ]
            if anchor_offsets:
                anchor_offset = min(anchor_offsets)
                values.extend(re.findall(r"\d+(?:\.\d+)?\s*克", text[anchor_offset:]))

        for marker in ("误解成", "当作", "算作"):
            offset = text.find(marker)
            if offset >= 0:
                fragment = re.split(r"[，,。！？!?；;]", text[offset:], maxsplit=1)[0]
                values.extend(re.findall(r"\d+(?:\.\d+)?\s*克", fragment))
        return dedupe_keep_order(values)

    def is_conversion_context(text: str) -> bool:
        markers = (
            "一钱等于",
            "1钱等于",
            "一钱是",
            "1钱是",
            "一钱约",
            "1钱约",
            "一钱算",
            "1钱算",
            "等于多少克",
            "换算",
            "剂量换算",
        )
        if any(marker in text for marker in markers):
            return True
        if (
            "大约一钱的量" in text
            or "一钱的量" in text
            or "大约1钱的量" in text
            or "1钱的量" in text
        ) and not any(marker in text for marker in ("也就是说", "按照比例", "加起来是")):
            return False
        return ("一钱" in text or "1钱" in text) and "克" in text

    values: list[str] = []
    for result in results:
        for text in source_primary_evidence_texts(result):
            for sentence in split_sentences(text):
                if is_conversion_context(sentence):
                    values.extend(extract_conversion_values(sentence))
    return dedupe_keep_order(values)


def collect_formula_names(results: list[dict[str, object]], query: str = "") -> list[str]:
    query_formulas = reliable_formula_anchors(query)
    grounded_query_formulas = [
        formula
        for formula in query_formulas
        if any(
            source_anchor_matches_evidence(formula, text)
            for result in results
            for text in source_primary_evidence_texts(result)
        )
    ]
    if grounded_query_formulas:
        return grounded_query_formulas
    names: list[str] = []
    for result in results:
        names.extend(known_formula_terms_in_evidence(primary_evidence_text(result)))
    return dedupe_keep_order(names)


def with_formula_dosage_safety(notice: str) -> str:
    notice = notice.strip()
    if FORMULA_DOSAGE_SAFETY_NOTICE in notice:
        return notice
    if not notice:
        return FORMULA_DOSAGE_SAFETY_NOTICE
    return f"{notice} {FORMULA_DOSAGE_SAFETY_NOTICE}"


def emergency_notice_for_query(query: str) -> str:
    normalized = normalize_query_text(query)
    return (
        EMERGENCY_SAFETY_NOTICE
        if any(normalize_query_text(term) in normalized for term in EMERGENCY_QUERY_TERMS)
        else ""
    )


def combine_safety_notices(*notices: str) -> str:
    return " ".join(dedupe_keep_order(notice for notice in notices if notice.strip()))


def rag_capability_gap(query: str, db_path: Path) -> str:
    """Refuse known out-of-corpus tasks instead of borrowing unrelated paragraphs."""
    normalized = normalize_query_text(query)
    if any(term in normalized for term in RAG_LEARNING_ROUTE_TERMS):
        return (
            "当前 RAG 资产是 PDF 原文检索库，不包含用户学习路线编排层。"
            "请改用主项目轻量模式的 references/learning-entry.md 和 references/lesson-map.md。"
        )
    if not any(term in normalized for term in RAG_TIANJI_QUERY_TERMS):
        return ""
    if not db_path.is_file():
        return ""
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT DISTINCT source_path FROM paragraphs").fetchall()
    except sqlite3.DatabaseError:
        return ""
    sources = "\n".join(str(row[0]) for row in rows)
    if "天纪" in sources:
        return ""
    return (
        "当前 RAG PDF 语料不包含《天纪》课程，不能用其他中医课程的相似段落替代回答。"
        "请改用主项目轻量模式的 references/tianji.md 及天纪截图证据。"
    )


def capability_gap_answer(query: str, message: str) -> dict[str, object]:
    return {
        "query": query,
        "intent": detect_answer_intent(query),
        "answer": message,
        "answer_sections": {
            "summary": message,
            "key_points": [],
            "citation_count": 0,
            "has_context_navigation": False,
            "linked_reference_count": 0,
        },
        "citations": [],
        "related_knowledge_units": [],
        "safety_notice": emergency_notice_for_query(query),
        "results": [],
        "capability_gap": True,
        "linked_reference_materials": [],
        "reference_secondary_included": False,
        "rerank": {"model": "none", "degraded_feature": "", "error": ""},
        "related_guide_nodes": [],
        "differentiation_flow": {"text_steps": [], "mermaid": ""},
        "followup_questions": [],
    }


def _citation_detail_points(
    citations: list[dict[str, object]],
    limit: int = 4,
) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for citation in citations[:limit]:
        index = citation.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            continue
        quote = clean_guide_evidence_text(str(citation.get("evidence_quote", "")))
        quote = evidence_quote(quote, max_chars=280)
        if not quote:
            continue
        points.append(
            {
                "text": quote,
                "citation_indices": [index],
                "source_label": str(citation.get("label", "")),
            }
        )
    return points


def _render_detailed_answer(
    summary: str,
    detail_points: list[dict[str, object]],
) -> str:
    lines: list[str] = []
    for offset, point in enumerate(detail_points, start=1):
        text = normalize_whitespace(str(point.get("text", "")))
        indices = [
            index
            for index in point.get("citation_indices", []) or []
            if isinstance(index, int) and not isinstance(index, bool)
        ]
        refs = "、".join(f"[{index}]" for index in indices)
        if text:
            lines.append(f"{offset}. {text}{refs}")
    if not lines:
        return summary
    return f"{summary}\n\n详细依据：\n" + "\n".join(lines)


def synthesize_pdf_rag_answer(
    query: str,
    results: list[dict[str, object]],
    max_citations: int = 6,
) -> dict[str, object]:
    intent = detect_answer_intent(query)
    emergency_notice = emergency_notice_for_query(query)
    relevant_results = filter_results_for_intent(query, intent, results)
    if intent == "source_lookup" and not reliable_source_anchors(query):
        explicit_terms = explicit_query_formula_terms(query)
        if explicit_terms:
            relevant_results = sorted(
                relevant_results,
                key=lambda result: not any(
                    literal_product_safe_term_in_text(term, str(result.get("text", "")).strip())
                    for term in explicit_terms
                ),
            )
    citations = build_citations(
        relevant_results,
        max_citations=max_citations,
        intent=intent,
        query=query,
    )
    related_knowledge_units = collect_matched_knowledge_units(relevant_results)[:12]
    cited = citations if intent == "dosage" else citations[:3]
    citation_refs = "、".join(f"[{citation['index']}]" for citation in cited)

    if not relevant_results or not citations:
        if intent == "clinical":
            safety_notice = with_formula_dosage_safety(
                "课程资料不能替代诊断；这里不直接给个人处方、剂量或治疗建议。"
            )
        elif intent == "dosage" or (
            intent == "source_lookup"
            and (reliable_formula_anchors(query) or explicit_query_formula_terms(query))
        ):
            safety_notice = with_formula_dosage_safety(
                "这是课程资料整理和出处检索，不是个人用药剂量建议。"
            )
        else:
            safety_notice = ""
        insufficient_summary = "当前知识库没有检索到足够可靠的原文证据。"
        insufficient_answer = (
            f"{insufficient_summary}建议换用更具体的方名、药名、症状或原文短语再查。"
        )
        normalized_query = normalize_query_text(query)
        if "上中下三品" in normalized_query or {
            "上品",
            "中品",
            "下品",
        } <= set(query_core_entity_terms(query)):
            insufficient_summary = (
                "当前默认主课程语料没有检索到同时解释上、中、下三品分类的可靠原文。"
            )
            insufficient_answer = (
                f"{insufficient_summary}关联参考资料只有在用户明确使用 `--include-references` "
                "时才可检索，并且必须标为“关联参考资料（非倪海厦著作）”；"
                "因此这里不从外部常识或参考书拼出分类答案。"
            )
        if emergency_notice:
            insufficient_answer = f"{emergency_notice}\n\n{insufficient_answer}"
            safety_notice = combine_safety_notices(emergency_notice, safety_notice)
        return {
            "query": query,
            "intent": intent,
            "answer": insufficient_answer,
            "answer_sections": {
                "summary": insufficient_summary,
                "key_points": [],
                "citation_count": 0,
                "has_context_navigation": False,
            },
            "citations": [],
            "related_knowledge_units": [],
            "safety_notice": safety_notice,
        }

    detail_points: list[dict[str, object]] = []
    if intent == "dosage":
        grams = collect_gram_values(relevant_results)
        gram_text = "、".join(grams) if grams else "检索结果中未形成稳定克数列表"
        answer = (
            f"根据当前 PDF 原文证据，“一钱”的说法不是单一固定值，已检索到：{gram_text}。"
            f"证据见 {citation_refs}。"
            "课程资料同时提示古今度量衡、抓药语境、煎煮方法和方中比例都会影响理解，"
            "不能只抽出一个克数孤立使用。"
        )
        results_by_paragraph = {
            str(result.get("paragraph_id", "")): result for result in relevant_results
        }
        for citation in citations:
            result = results_by_paragraph.get(str(citation.get("paragraph_id", "")))
            if result is None:
                continue
            values = collect_gram_values([result])
            if values:
                point_text = (
                    f"该段给出或讨论的一钱数值线索：{'、'.join(values)}；需结合原段语境理解。"
                )
            elif "比例" in primary_evidence_text(result):
                point_text = "该段强调方中比例也是理解一钱用量时需要保留的原文语境。"
            else:
                continue
            detail_points.append(
                {
                    "text": point_text,
                    "citation_indices": [citation["index"]],
                    "source_label": citation["label"],
                }
            )
        safety_notice = with_formula_dosage_safety(
            "这是课程资料整理和出处检索，不是个人用药剂量建议。"
        )
    elif intent == "source_lookup":
        if is_reference_material_query(query):
            titles = dedupe_keep_order(
                normalize_whitespace(title)
                for result in relevant_results
                for title in re.findall(r"《([^》\n]{1,60})》", primary_evidence_text(result))
                if normalize_whitespace(title)
            )[:12]
            title_text = "、".join(f"《{title}》" for title in titles) or "原文所列书目"
            locations = "；".join(
                f"{citation['label']}[{citation['index']}]" for citation in citations[:4]
            )
            answer = (
                f"课程原文在 {locations} 的书单段落中提到：{title_text}。"
                "证据以课程原文为准；当前已入库且有显式关系证据的外部书籍，会在下方作为关联资料单独标明。"
            )
            first_citation_index = citations[0]["index"] if citations else 1
            detail_points = [
                {
                    "text": "课程把这一段明确称为“开八本书”的书单，并说明这些书可以拿来参考。",
                    "citation_indices": [first_citation_index],
                    "source_label": citations[0]["label"] if citations else "",
                },
                {
                    "text": "课程建议先把《伤寒论》的条辨和处方读熟，再进入《金匮》相关学习。",
                    "citation_indices": [first_citation_index],
                    "source_label": citations[0]["label"] if citations else "",
                },
            ]
            safety_notice = ""
        else:
            anchors = answer_anchor_terms(query)
            topic = "、".join(anchors[:3]) or normalize_query_text(query).rstrip("。！？!?；;，,")
            locations = "；".join(
                f"{citation['label']}[{citation['index']}]" for citation in citations[:4]
            )
            answer = (
                f"关于“{topic}”，当前检索到的原文位置是：{locations}。下面按来源列出详细原文依据。"
            )
            has_formula_content = bool(
                reliable_formula_anchors(query) or explicit_query_formula_terms(query)
            ) or any(
                known_formula_terms_in_evidence(text)
                for result in relevant_results
                for text in source_primary_evidence_texts(result)
            )
            safety_notice = (
                with_formula_dosage_safety("这是原文出处定位和课程整理，不是个人用药建议。")
                if has_formula_content
                else ""
            )
    elif intent == "clinical":
        formulas = collect_formula_names(relevant_results, query=query)[:8]
        formula_text = "、".join(formulas) if formulas else "未稳定抽取到方名"
        focus_clues = clinical_evidence_clues(normalize_query_text(query))
        focus_text = "、".join(focus_clues) if focus_clues else "问题中描述的症状"
        citation_sentence = f"可核对原文证据 {citation_refs}。" if citation_refs else ""
        citation_evidence = "\n".join(
            str(citation.get("evidence_quote", "")) for citation in citations
        )
        sweat_comparison = (
            {"有汗", "无汗"} <= set(query_core_entity_terms(query))
            and "桂枝汤" in citation_evidence
            and "麻黄汤" in citation_evidence
            and any(term in citation_evidence for term in ("自汗", "汗出", "有汗"))
            and "无汗" in citation_evidence
        )
        if sweat_comparison:
            answer = (
                "按当前检索到的课程原文，可先核对“汗”的分水岭："
                "有汗或汗出，并见营卫不和一侧，核对桂枝汤证；"
                "无汗，并见怕冷、身痛、喘等线索一侧，核对麻黄汤证。"
                f"{citation_sentence}这只是课程方证学习线索，不能据此为真实病人自行选方。"
            )
            detail_points = _citation_detail_points(citations)
        else:
            answer = (
                "这个问题含有具体病人信息，我不直接给个人处方。"
                f"问题焦点是：{focus_text}。按课程资料检索，相关原文中出现的方名包括：{formula_text}。"
                f"{citation_sentence}若用于真实病人，需要由合格医师面诊辨证。"
            )
            detail_points = [
                {
                    "text": (
                        f"课程原文中可核对到的方名为：{formula_text}；"
                        f"与本次问题相关的症状焦点为：{focus_text}。"
                    ),
                    "citation_indices": [citation["index"] for citation in citations[:3]],
                    "source_label": "；".join(str(citation["label"]) for citation in citations[:3]),
                }
            ]
        if emergency_notice:
            answer = f"{emergency_notice}\n\n{answer}"
        safety_notice = combine_safety_notices(
            emergency_notice,
            with_formula_dosage_safety(
                "课程资料不能替代诊断；这里不直接给个人处方、剂量或治疗建议。"
            ),
        )
    elif (
        intent == "comparison"
        and {"桂枝汤", "麻黄汤"} <= set(query_core_entity_terms(query))
        and any(
            "桂枝汤" in str(citation.get("evidence_quote", ""))
            and "麻黄汤" in str(citation.get("evidence_quote", ""))
            and any(
                clue in str(citation.get("evidence_quote", "")) for clue in ("自汗", "汗出", "有汗")
            )
            and "无汗" in str(citation.get("evidence_quote", ""))
            for citation in citations
        )
    ):
        answer = (
            "按当前检索到的课程原文，首要分水岭是汗："
            "桂枝汤放在发热自汗、营卫不和一侧；"
            "麻黄汤放在无汗，且身痛、恶寒较重一侧。"
            f"证据见 {citation_refs}。"
        )
        safety_notice = with_formula_dosage_safety("这是课程方证比较，不是个人选方或用药建议。")
    elif (
        intent == "general"
        and "学习主线" in normalize_query_text(query)
        and "胸痹" in query_core_entity_terms(query)
        and any("第九篇" in str(citation.get("evidence_quote", "")) for citation in citations)
    ):
        answer = (
            "当前 RAG 原文能可靠确认的学习起点是《金匮》第九篇"
            "“胸痹心痛短气病脉证并治”；当前证据不足以自动补写一套完整学习路线。"
            f"证据见 {citation_refs}。"
        )
        safety_notice = "这是课程章节定位，不是心血管疾病诊断或治疗建议。"
    elif (
        intent == "general"
        and "合称" in normalize_query_text(query)
        and {"合谷", "太冲"} <= set(query_core_entity_terms(query))
        and any("四关" in str(citation.get("evidence_quote", "")) for citation in citations)
    ):
        answer = f"根据当前检索到的课程原文，合谷与太冲合称“四关”；课程中也称同时取用为“开四关”。证据见 {citation_refs}。"
        safety_notice = "这是课程术语和原文定位，不是针灸操作指导；请勿自行针刺。"
    elif (
        intent == "general"
        and "春夏秋冬" in normalize_query_text(query)
        and "养生" in normalize_query_text(query)
    ):
        long_summer_citation = next(
            (
                citation
                for citation in citations
                if "长夏" in str(citation.get("evidence_quote", ""))
            ),
            None,
        )
        organ_citation = next(
            (
                citation
                for citation in citations
                if all(
                    term in str(citation.get("evidence_quote", ""))
                    for term in ("春天", "肝脏", "夏天", "心脏", "秋天", "肺脏", "冬天", "肾脏")
                )
            ),
            None,
        )
        supported_points: list[str] = []
        detail_points = []
        for citation, point in (
            (
                organ_citation,
                "课程原文把春、夏、秋、冬依次联系到肝、心、肺、肾。",
            ),
            (
                long_summer_citation,
                "课程还把四季之间的节气交换阶段称为“长夏”。",
            ),
        ):
            if not citation:
                continue
            supported_points.append(f"{point}[{citation['index']}]")
            detail_points.append(
                {
                    "text": clean_guide_evidence_text(str(citation.get("evidence_quote", ""))),
                    "citation_indices": [citation["index"]],
                    "source_label": str(citation.get("label", "")),
                }
            )
        supported_text = "".join(supported_points) or "当前只检索到零散的四时相关段落。"
        answer = (
            f"当前 RAG 原文能直接支持的对应关系是：{supported_text}"
            "但现有证据没有完整列出四季分别应采取的养生行动，"
            "所以这里不补写一张看似完整、实际无原文支撑的四季养生表。"
        )
        safety_notice = ""
    else:
        points = "；".join(
            evidence_quote(str(citation.get("evidence_quote", "")), max_chars=160)
            for citation in citations[:3]
            if str(citation.get("evidence_quote", "")).strip()
        )
        citation_sentence = f"证据见 {citation_refs}。" if citation_refs else ""
        answer = f"根据当前检索结果，相关原文要点包括：{points}。{citation_sentence}"
        has_formula_content = bool(
            reliable_formula_anchors(query) or explicit_query_formula_terms(query)
        ) or any(
            known_formula_terms_in_evidence(primary_evidence_text(result))
            for result in relevant_results
        )
        safety_notice = (
            with_formula_dosage_safety("这是课程原文比较，不是个人用药建议。")
            if has_formula_content
            else ""
        )

    if not detail_points:
        detail_points = _citation_detail_points(citations)
    summary = answer
    answer = _render_detailed_answer(summary, detail_points)
    has_context_navigation = any(bool(citation.get("context_navigation")) for citation in citations)

    return {
        "query": query,
        "intent": intent,
        "answer": answer,
        "answer_sections": {
            "summary": summary,
            "key_points": detail_points,
            "citation_count": len(citations),
            "has_context_navigation": has_context_navigation,
        },
        "citations": citations,
        "related_knowledge_units": related_knowledge_units,
        "safety_notice": safety_notice,
        "results": results,
    }


TRACE_MAX_QUERY_CHARS = 500
TRACE_MAX_PLAN_ITEMS = 8
TRACE_MAX_OBSERVATIONS_PER_QUERY = 12
TRACE_MAX_SELECTED_IDS = 50
TRACE_CHANNELS = frozenset({"vector", "text", "knowledge"})
TRACE_MAX_LATENCY_MS = 3_600_000.0


def _safe_trace_string(value: object, *, max_chars: int) -> str:
    from .rerank import sanitize_rerank_error

    return sanitize_rerank_error(value, max_chars=max_chars)


def _bounded_latency_ms(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return round(max(0.0, min(parsed, TRACE_MAX_LATENCY_MS)), 3)


def _trace_phase_start(enabled: bool) -> float | None:
    if not enabled:
        return None
    try:
        value = float(time.perf_counter())
    except Exception:
        return None
    return value if math.isfinite(value) else None


def _trace_phase_finish(
    latency_ms: dict[str, float],
    phase: str,
    started: float | None,
) -> None:
    if started is None:
        return
    try:
        finished = float(time.perf_counter())
    except Exception:
        return
    elapsed = _bounded_latency_ms((finished - started) * 1000.0)
    latency_ms[phase] = _bounded_latency_ms(latency_ms[phase] + elapsed)


def _trace_dict_get(mapping: dict[str, object], key: str, default: object = None) -> object:
    try:
        return dict.get(mapping, key, default)
    except Exception:
        return default


def _trace_channels(result: dict[str, object]) -> list[str]:
    channels: set[str] = set()
    raw_sources = _trace_dict_get(result, "retrieval_sources")
    if type(raw_sources) in {list, tuple}:
        channels.update(
            source
            for source in raw_sources[:12]
            if isinstance(source, str) and source in TRACE_CHANNELS
        )
    raw_ranks = _trace_dict_get(result, "channel_ranks")
    if isinstance(raw_ranks, dict):
        for channel in TRACE_CHANNELS:
            rank = _trace_dict_get(raw_ranks, channel)
            if isinstance(rank, int) and not isinstance(rank, bool) and 0 < rank <= 1_000_000:
                channels.add(channel)
    return sorted(channels)


def _trace_query_plan(
    plan: list[str],
    results: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: list[list[dict[str, object]]] = [[] for _ in plan[:TRACE_MAX_PLAN_ITEMS]]
    for result in results[:TRACE_MAX_SELECTED_IDS]:
        paragraph_id = _safe_trace_string(
            _trace_dict_get(result, "paragraph_id", ""),
            max_chars=120,
        )
        raw_observations = _trace_dict_get(result, "rewrite_observations")
        if type(raw_observations) not in {list, tuple}:
            continue
        for raw in raw_observations[:16]:
            if not isinstance(raw, dict):
                continue
            rewrite_index = _trace_dict_get(raw, "rewrite_index")
            rank = _trace_dict_get(raw, "rank")
            if (
                isinstance(rewrite_index, int)
                and not isinstance(rewrite_index, bool)
                and 1 <= rewrite_index <= len(grouped)
                and isinstance(rank, int)
                and not isinstance(rank, bool)
                and 0 < rank <= 1_000_000
                and len(grouped[rewrite_index - 1]) < TRACE_MAX_OBSERVATIONS_PER_QUERY
            ):
                grouped[rewrite_index - 1].append(
                    {
                        "paragraph_id": paragraph_id,
                        "rank": rank,
                        "channels": _trace_channels(result),
                    }
                )
    return [
        {
            "query": _safe_trace_string(query, max_chars=TRACE_MAX_QUERY_CHARS),
            "observations": grouped[index],
        }
        for index, query in enumerate(plan[:TRACE_MAX_PLAN_ITEMS])
    ]


def answer_pdf_rag(
    query: str,
    db_path: Path,
    limit: int = 8,
    mode: str = "hybrid",
    embedding: str = "auto",
    model: str = "BAAI/bge-m3",
    batch_size: int = 32,
    embedding_backend: SparseHashEmbeddingBackend | DenseEmbeddingBackend | None = None,
    reranker_backend: object | None = None,
    reranker: str = "none",
    rerank_model: str | None = None,
    trace_enabled: bool = False,
    include_reference_secondary: bool = False,
) -> dict[str, object]:
    validate_runtime_limit(limit, "limit", MAX_PUBLIC_ANSWER_LIMIT)
    if reranker not in {"auto", "none", "siliconflow"}:
        raise ValueError(f"unsupported reranker: {reranker}")
    if not isinstance(trace_enabled, bool):
        raise TypeError("trace_enabled must be a boolean")
    if not isinstance(include_reference_secondary, bool):
        raise TypeError("include_reference_secondary must be a boolean")
    latency_ms = {
        "planning": 0.0,
        "retrieval": 0.0,
        "rerank": 0.0,
        "guide": 0.0,
        "synthesis": 0.0,
    }
    db_path = db_path.expanduser().resolve()
    capability_gap = rag_capability_gap(query, db_path)
    if capability_gap:
        return capability_gap_answer(query, capability_gap)
    if embedding_backend is not None:
        store = LocalVectorStore(db_path, embedding_backend=embedding_backend)
    elif mode in {"text", "knowledge", "graph"}:
        store = LocalVectorStore(db_path)
    else:
        backend = create_embedding_backend_for_db(
            db_path,
            embedding=embedding,
            model=model,
            batch_size=batch_size,
        )
        store = LocalVectorStore(db_path, embedding_backend=backend)
    candidate_limit = max(limit * 4, 16)
    phase_started = _trace_phase_start(trace_enabled)
    intent = detect_answer_intent(query)
    initial_plan = [query] if mode == "graph" else build_query_plan(query, intent=intent)
    _trace_phase_finish(latency_ms, "planning", phase_started)
    phase_started = _trace_phase_start(trace_enabled)
    search_options = {"include_reference_secondary": True} if include_reference_secondary else {}
    results = run_query_plan_search(
        store,
        initial_plan,
        limit=candidate_limit,
        mode=mode,
        intent=intent,
        **search_options,
    )
    initial_results = results
    _trace_phase_finish(latency_ms, "retrieval", phase_started)
    phase_started = _trace_phase_start(trace_enabled)
    skip_followup_expansion = bool(query_core_entity_terms(query)) and intent in {
        "general",
        "comparison",
        "source_lookup",
    }
    followup_plan = (
        []
        if mode == "graph" or skip_followup_expansion
        else [
            planned_query
            for planned_query in build_query_plan(query, intent=intent, seed_results=results)
            if planned_query not in initial_plan
        ]
    )
    _trace_phase_finish(latency_ms, "planning", phase_started)
    followup_results: list[dict[str, object]] = []
    if followup_plan:
        phase_started = _trace_phase_start(trace_enabled)
        followup_results = run_query_plan_search(
            store,
            followup_plan,
            limit=candidate_limit,
            mode=mode,
            intent=intent,
            **search_options,
        )
        results = fuse_query_rewrites(
            [results, followup_results], limit=max(candidate_limit * 2, 32)
        )
        _trace_phase_finish(latency_ms, "retrieval", phase_started)
    phase_started = _trace_phase_start(trace_enabled)
    intent_results = filter_results_for_intent(query, intent, results)
    _trace_phase_finish(latency_ms, "retrieval", phase_started)
    rerank_outcome = None
    rerank_limit = min(len(intent_results), max(limit * 3, 12))
    phase_started = _trace_phase_start(trace_enabled)
    if reranker_backend is not None:
        rerank_outcome = reranker_backend.rerank(query, intent_results, limit=rerank_limit)
    elif reranker == "siliconflow" or (reranker == "auto" and siliconflow_api_key_available()):
        from .rerank import SiliconFlowReranker

        rerank_outcome = SiliconFlowReranker(model=rerank_model).rerank(
            query,
            intent_results,
            limit=rerank_limit,
        )
    if rerank_outcome is not None:
        from .rerank import snapshot_rerank_outcome

        rerank_outcome = snapshot_rerank_outcome(
            rerank_outcome,
            limit=rerank_limit,
        )
        intent_results = rerank_outcome.results
    _trace_phase_finish(latency_ms, "rerank", phase_started)
    phase_started = _trace_phase_start(trace_enabled)
    results = select_diverse_results(intent_results, limit=limit, intent=intent)
    results = enrich_results_with_evidence_context(db_path, results)
    _trace_phase_finish(latency_ms, "retrieval", phase_started)
    phase_started = _trace_phase_start(trace_enabled)
    answer = synthesize_pdf_rag_answer(query, results)
    answer["reference_secondary_included"] = include_reference_secondary
    linked_materials = linked_reference_materials(
        db_path,
        list(answer.get("citations", []) or []),
    )
    answer["linked_reference_materials"] = linked_materials
    answer_sections = answer.get("answer_sections")
    if isinstance(answer_sections, dict):
        answer_sections["linked_reference_count"] = len(linked_materials)
    answer["rerank"] = (
        {
            "model": rerank_outcome.model,
            "degraded_feature": rerank_outcome.degraded_feature,
            "error": rerank_outcome.error,
        }
        if rerank_outcome is not None
        else {"model": "none", "degraded_feature": "", "error": ""}
    )
    guide_query_parts = [
        query,
        str(answer.get("answer", "")),
        " ".join(
            str(unit.get("subject", "")) + " " + str(unit.get("object", ""))
            for unit in answer.get("related_knowledge_units", []) or []
        ),
    ]
    _trace_phase_finish(latency_ms, "synthesis", phase_started)
    phase_started = _trace_phase_start(trace_enabled)
    related_guide_nodes = (
        store.search_guide_nodes(" ".join(guide_query_parts), limit=8)
        if intent == "clinical"
        else []
    )
    _trace_phase_finish(latency_ms, "guide", phase_started)
    phase_started = _trace_phase_start(trace_enabled)
    answer["related_guide_nodes"] = related_guide_nodes
    answer["differentiation_flow"] = build_differentiation_flow(query, related_guide_nodes)
    answer["followup_questions"] = build_followup_questions(
        query,
        intent,
        related_guide_nodes,
        list(answer.get("related_knowledge_units", []) or []),
    )
    _trace_phase_finish(latency_ms, "synthesis", phase_started)
    if trace_enabled:
        selected_ids = [
            _safe_trace_string(
                _trace_dict_get(result, "paragraph_id", ""),
                max_chars=120,
            )
            for result in results[:TRACE_MAX_SELECTED_IDS]
        ]
        selected_ids = [paragraph_id for paragraph_id in selected_ids if paragraph_id]
        retrieval_channels = sorted(
            {
                channel
                for result in results[:TRACE_MAX_SELECTED_IDS]
                for channel in _trace_channels(result)
            }
        )
        model_value = rerank_outcome.model if rerank_outcome is not None else "none"
        degraded_value = rerank_outcome.degraded_feature if rerank_outcome is not None else ""
        answer["trace"] = {
            "normalized_query": _safe_trace_string(
                normalize_query_text(query),
                max_chars=TRACE_MAX_QUERY_CHARS,
            ),
            "intent": _safe_trace_string(intent, max_chars=40),
            "query_plan": _trace_query_plan(initial_plan, initial_results),
            "followup_plan": _trace_query_plan(followup_plan, followup_results),
            "retrieval_channels": retrieval_channels,
            "selected_paragraph_ids": selected_ids,
            "reranker": model_value,
            "degraded_features": [degraded_value] if degraded_value else [],
            "latency_ms": {
                phase: _bounded_latency_ms(value) for phase, value in latency_ms.items()
            },
        }
    return answer


def source_catalog_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def load_build_source_catalog(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid source catalog") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("documents"), list):
        raise ValueError("invalid source catalog documents")
    entries: dict[str, dict[str, Any]] = {}
    for raw in payload["documents"]:
        if not isinstance(raw, dict):
            raise ValueError("invalid source catalog document")
        filename = raw.get("ingest_filename") or raw.get("filename")
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise ValueError("invalid source catalog filename")
        key = source_catalog_key(filename)
        if key in entries:
            raise ValueError("duplicate source catalog filename")
        excluded = raw.get("exclude_pages", [])
        if not isinstance(excluded, list) or any(
            not isinstance(page, int) or isinstance(page, bool) or page < 1 for page in excluded
        ):
            raise ValueError("invalid source catalog exclude_pages")
        strip_patterns = raw.get("strip_text_patterns", [])
        if not isinstance(strip_patterns, list) or any(
            not isinstance(pattern, str) or not pattern for pattern in strip_patterns
        ):
            raise ValueError("invalid source catalog strip_text_patterns")
        strip_regexes = raw.get("strip_text_regexes", [])
        if not isinstance(strip_regexes, list) or any(
            not isinstance(pattern, str) or not pattern for pattern in strip_regexes
        ):
            raise ValueError("invalid source catalog strip_text_regexes")
        try:
            for pattern in strip_regexes:
                re.compile(pattern)
        except re.error as exc:
            raise ValueError("invalid source catalog strip_text_regex") from exc
        relation_evidence_ids = raw.get("relation_evidence_ids", [])
        quality_flags = raw.get("quality_flags", [])
        if not isinstance(relation_evidence_ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in relation_evidence_ids
        ):
            raise ValueError("invalid source catalog relation_evidence_ids")
        if not isinstance(quality_flags, list) or any(
            not isinstance(item, str) or not item.strip() for item in quality_flags
        ):
            raise ValueError("invalid source catalog quality_flags")
        entries[key] = raw
    return entries


def load_build_reference_link_evidence(path: Path | None) -> list[dict[str, object]]:
    if path is None:
        return []
    try:
        payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid source catalog") from exc
    raw_evidence = payload.get("course_evidence") if isinstance(payload, dict) else None
    if raw_evidence is None:
        return []
    if not isinstance(raw_evidence, list):
        raise ValueError("invalid source catalog course_evidence")
    evidence: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for raw in raw_evidence:
        if not isinstance(raw, dict):
            raise ValueError("invalid source catalog course evidence")
        evidence_id = raw.get("evidence_id")
        source_path = raw.get("logical_source_path")
        page = raw.get("page")
        quote = raw.get("evidence_quote")
        normalized_evidence_id = evidence_id.strip() if isinstance(evidence_id, str) else ""
        if (
            not normalized_evidence_id
            or normalized_evidence_id in seen_ids
            or not isinstance(source_path, str)
            or not source_path.startswith("pdfs/")
            or Path(source_path).name == ""
            or isinstance(page, bool)
            or not isinstance(page, int)
            or page < 1
            or not isinstance(quote, str)
            or not quote.strip()
        ):
            raise ValueError("invalid source catalog course evidence")
        seen_ids.add(normalized_evidence_id)
        evidence.append(
            {
                "evidence_id": normalized_evidence_id,
                "logical_source_path": f"pdfs/{Path(source_path).name}",
                "page": page,
                "evidence_quote": normalize_whitespace(quote)[:800],
            }
        )
    return evidence


def clean_pdf_extracted_text(text: str, source_policy: dict[str, Any]) -> str:
    cleaned = text
    for pattern in source_policy.get("strip_text_patterns", []):
        cleaned = cleaned.replace(str(pattern), "")
    for pattern in source_policy.get("strip_text_regexes", []):
        cleaned = re.sub(str(pattern), "", cleaned)
    if source_policy.get("strip_tilde_page_markers"):
        cleaned = re.sub(r"~\s*\d+\s*~", "", cleaned)
    return clean_text(cleaned)


def extract_pdf_paragraphs(
    pdf_path: Path,
    max_chars: int = 900,
    source_policy: dict[str, Any] | None = None,
    logical_source_path: str | None = None,
) -> list[ParsedParagraph]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for PDF extraction. Install package: PyMuPDF"
        ) from exc

    pdf_path = pdf_path.expanduser().resolve()
    doc_id = stable_id(pdf_path.name, pdf_path.stat().st_size)
    stored_source_path = logical_source_path or str(pdf_path)
    excluded_pages = set((source_policy or {}).get("exclude_pages", []))
    source_policy = source_policy or {}
    paragraphs: list[ParsedParagraph] = []
    with fitz.open(pdf_path) as doc:
        for page_index, page in enumerate(doc, start=1):
            if page_index in excluded_pages:
                continue
            blocks = page.get_text("blocks")
            block_texts = []
            for block in blocks:
                text = clean_pdf_extracted_text(str(block[4]), source_policy)
                text = re.sub(r"^\s*\d+\s*$", "", text).strip()
                if len(text) >= 20:
                    block_texts.append(text)
            page_text = clean_pdf_extracted_text(
                "\n".join(block_texts) or page.get_text("text"),
                source_policy,
            )
            for paragraph_index, paragraph_text in enumerate(
                split_long_text_to_paragraphs(page_text, max_chars=max_chars), start=1
            ):
                paragraph_id = stable_id(doc_id, page_index, paragraph_index, paragraph_text[:80])
                paragraphs.append(
                    ParsedParagraph(
                        paragraph_id=paragraph_id,
                        doc_id=doc_id,
                        source_path=stored_source_path,
                        title=f"{pdf_path.stem} p{page_index}",
                        page_start=page_index,
                        page_end=page_index,
                        text=paragraph_text,
                    )
                )
    return paragraphs


def build_pdf_vector_store(
    pdf_dir: Path,
    out_dir: Path,
    window_size: int = 6,
    overlap: int = 2,
    dims: int = 2048,
    embedding: str = "siliconflow",
    model: str = "BAAI/bge-m3",
    batch_size: int = 32,
    unit_types: set[str] | None = None,
    trace_dir: Path | None = None,
    source_catalog_path: Path | None = None,
    portable_source_paths: bool = False,
) -> dict[str, int | str]:
    pdf_dir = pdf_dir.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    pdf_paths = sorted(list(pdf_dir.glob("*.pdf")) + list(pdf_dir.glob("*.PDF")))
    if not pdf_paths:
        raise FileNotFoundError(f"No PDF files found in {pdf_dir}")
    source_catalog = load_build_source_catalog(source_catalog_path)
    reference_link_evidence = load_build_reference_link_evidence(source_catalog_path)

    embedding_backend = create_embedding_backend(
        embedding=embedding,
        dims=dims,
        model=model,
        batch_size=batch_size,
    )
    store = LocalVectorStore(out_dir / "rag.sqlite", dims=dims, embedding_backend=embedding_backend)
    store.recreate()
    all_paragraphs: list[ParsedParagraph] = []
    all_units: list[RetrievalUnit] = []
    manifest = []
    document_events: list[dict[str, object]] = []
    for pdf_path in pdf_paths:
        source_policy = source_catalog.get(source_catalog_key(pdf_path.name), {})
        logical_source_path = f"pdfs/{pdf_path.name}" if portable_source_paths else None
        paragraphs = extract_pdf_paragraphs(
            pdf_path,
            source_policy=source_policy,
            logical_source_path=logical_source_path,
        )
        units = build_retrieval_units(paragraphs, window_size=window_size, overlap=overlap)
        if unit_types:
            units = [unit for unit in units if unit.unit_type in unit_types]
        store.insert_paragraphs(paragraphs)
        store.insert_units(units)
        all_paragraphs.extend(paragraphs)
        all_units.extend(units)
        document_manifest: dict[str, object] = {
            "source_path": logical_source_path or str(pdf_path),
            "size_bytes": pdf_path.stat().st_size,
            "paragraphs": len(paragraphs),
            "retrieval_units": len(units),
        }
        for key in (
            "source_layer",
            "relation_type",
            "authorship",
            "edition_verification",
            "exclude_pages",
            "strip_text_patterns",
            "strip_text_regexes",
            "strip_tilde_page_markers",
            "relation_evidence_ids",
            "quality_flags",
        ):
            if key in source_policy:
                document_manifest[key] = source_policy[key]
        manifest.append(document_manifest)
        document_events.append(
            {
                "source_path": logical_source_path or str(pdf_path),
                "size_bytes": pdf_path.stat().st_size,
                "paragraphs": len(paragraphs),
                "retrieval_units": len(units),
                "unit_types": sorted({unit.unit_type for unit in units}),
                "excluded_pages": list(source_policy.get("exclude_pages", [])),
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    store_meta = store.read_meta()
    vector_dim = int(store_meta.get("vector_dim", store_meta.get("dims", dims)))
    trace_stats = write_build_traces(
        trace_dir=trace_dir or (out_dir / "traces"),
        pdf_dir=pdf_dir,
        out_dir=out_dir,
        embedding_name=embedding_backend.name,
        vector_kind=embedding_backend.vector_kind,
        window_size=window_size,
        overlap=overlap,
        unit_types=unit_types or {"paragraph", "question", "sentence", "window"},
        paragraphs=all_paragraphs,
        units=all_units,
        document_events=document_events,
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "pdf_dir": "external://pdf-sources" if portable_source_paths else str(pdf_dir),
                "store": "rag.sqlite" if portable_source_paths else str(store.db_path),
                "embedding": embedding_backend.name,
                "embedding_backend": embedding_backend.name,
                "vector_kind": embedding_backend.vector_kind,
                "dims": vector_dim,
                "vector_dim": vector_dim,
                "window_size": window_size,
                "overlap": overlap,
                "unit_types": sorted(unit_types)
                if unit_types
                else ["paragraph", "question", "sentence", "window"],
                "trace_dir": "traces" if portable_source_paths else trace_stats["trace_dir"],
                "documents": manifest,
                "reference_link_evidence": reference_link_evidence,
                "paragraphs": len(all_paragraphs),
                "retrieval_units": len(all_units),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    stats = store.stats()
    stats["manifest"] = str(out_dir / "manifest.json")
    stats.update(trace_stats)
    return stats


def augment_pdf_vector_store_questions(
    db_path: Path,
    embedding: str = "auto",
    model: str = "BAAI/bge-m3",
    batch_size: int = 32,
    embedding_backend: SparseHashEmbeddingBackend | DenseEmbeddingBackend | None = None,
) -> dict[str, int | str]:
    db_path = db_path.expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Vector store does not exist: {db_path}")

    backend = embedding_backend or create_embedding_backend_for_db(
        db_path,
        embedding=embedding,
        model=model,
        batch_size=batch_size,
    )
    store = LocalVectorStore(db_path, embedding_backend=backend)
    with store.connect() as conn:
        paragraph_rows = conn.execute(
            """
            SELECT paragraph_id, doc_id, source_path, title, page_start, page_end, text
            FROM paragraphs
            ORDER BY doc_id, page_start, paragraph_id
            """
        ).fetchall()

    paragraphs = [
        ParsedParagraph(
            paragraph_id=row["paragraph_id"],
            doc_id=row["doc_id"],
            source_path=row["source_path"],
            title=row["title"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            text=row["text"],
        )
        for row in paragraph_rows
    ]
    question_units = build_question_retrieval_units(paragraphs)

    with store.connect() as conn:
        conn.execute("DELETE FROM retrieval_units WHERE unit_type = 'question'")
    store.insert_units(question_units)
    _update_manifest_after_question_augment(db_path)

    stats = store.stats()
    stats["question_units"] = len(question_units)
    return stats


def _update_manifest_after_question_augment(db_path: Path) -> None:
    manifest_path = db_path.parent / "manifest.json"
    if not manifest_path.exists():
        return

    with LocalVectorStore(db_path).connect() as conn:
        total_units = conn.execute("SELECT COUNT(*) FROM retrieval_units").fetchone()[0]
        total_paragraphs = conn.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0]
        unit_types = [
            row[0]
            for row in conn.execute(
                "SELECT unit_type FROM retrieval_units GROUP BY unit_type ORDER BY unit_type"
            ).fetchall()
        ]
        document_rows = conn.execute(
            """
            SELECT p.source_path, COUNT(DISTINCT p.paragraph_id), COUNT(u.unit_id)
            FROM paragraphs p
            LEFT JOIN retrieval_units u ON u.paragraph_id = p.paragraph_id
            GROUP BY p.source_path
            """
        ).fetchall()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["paragraphs"] = total_paragraphs
    manifest["retrieval_units"] = total_units
    manifest["unit_types"] = unit_types

    document_counts = {
        row[0]: {"paragraphs": int(row[1]), "retrieval_units": int(row[2])} for row in document_rows
    }
    documents = []
    for document in manifest.get("documents", []):
        source_path = document.get("source_path")
        if source_path in document_counts:
            document = {**document, **document_counts[source_path]}
        documents.append(document)
    if documents:
        manifest["documents"] = documents

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _update_manifest_after_text_index(db_path: Path, text_index: str, rows: int) -> None:
    manifest_path = db_path.parent / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["text_index"] = text_index
    manifest["text_index_rows"] = rows
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _update_manifest_after_knowledge_units(
    db_path: Path,
    rows: int,
    unit_types: dict[str, int],
    trace_path: Path | None,
) -> None:
    manifest_path = db_path.parent / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["knowledge_units"] = rows
    manifest["knowledge_unit_types"] = unit_types
    manifest["knowledge_extractor_version"] = KNOWLEDGE_EXTRACTOR_VERSION
    if trace_path is not None:
        manifest["knowledge_trace"] = str(trace_path)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def create_embedding_backend(
    embedding: str,
    dims: int = 2048,
    model: str = "BAAI/bge-m3",
    batch_size: int = 32,
) -> SparseHashEmbeddingBackend | DenseEmbeddingBackend:
    if embedding == "sparse":
        return SparseHashEmbeddingBackend(dims=dims)
    if embedding == "siliconflow":
        return SiliconFlowEmbeddingBackend(model=model, batch_size=batch_size)
    if embedding in {"local", "local-bge-m3", "bge-m3-local"}:
        return LocalBgeM3EmbeddingBackend(model=model, batch_size=batch_size)
    raise ValueError(f"unsupported embedding backend: {embedding}")


def siliconflow_api_key_available() -> bool:
    load_dotenv_if_present()
    return bool(os.getenv("SILICONFLOW_API_KEY", "").strip())


def create_embedding_backend_for_db(
    db_path: Path,
    embedding: str = "auto",
    dims: int = 2048,
    model: str = "BAAI/bge-m3",
    batch_size: int = 32,
) -> SparseHashEmbeddingBackend | DenseEmbeddingBackend:
    if embedding != "auto":
        return create_embedding_backend(embedding, dims=dims, model=model, batch_size=batch_size)
    probe = LocalVectorStore(db_path, dims=dims)
    meta = probe.read_meta()
    stored_embedding = meta.get("embedding", "")
    if stored_embedding.startswith("siliconflow:"):
        stored_model = stored_embedding.split(":", 1)[1] or model
        if not siliconflow_api_key_available():
            return LocalBgeM3EmbeddingBackend(model=stored_model, batch_size=batch_size)
        return SiliconFlowEmbeddingBackend(model=stored_model, batch_size=batch_size)
    if stored_embedding.startswith("local-bge-m3:"):
        stored_model = stored_embedding.split(":", 1)[1] or model
        return LocalBgeM3EmbeddingBackend(model=stored_model, batch_size=batch_size)
    return SparseHashEmbeddingBackend(dims=int(meta.get("dims", dims)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and search a local PDF vector store.")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build a local SQLite vector store from PDFs")
    build.add_argument("--pdf-dir", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--window-size", type=int, default=6)
    build.add_argument("--overlap", type=int, default=2)
    build.add_argument("--dims", type=int, default=2048)
    build.add_argument(
        "--embedding",
        choices=["sparse", "siliconflow", "local-bge-m3"],
        default="siliconflow",
    )
    build.add_argument("--model", default="BAAI/bge-m3")
    build.add_argument("--batch-size", type=int, default=32)
    build.add_argument(
        "--unit-types",
        default="sentence,window,paragraph,question",
        help="Comma-separated retrieval unit types to embed.",
    )
    build.add_argument("--trace-dir", type=Path, default=None)

    search = sub.add_parser("search", help="search a built PDF vector store")
    search.add_argument("query")
    search.add_argument("--db", type=Path, required=True)
    search.add_argument("--limit", type=int, default=5)
    search.add_argument(
        "--mode", choices=["hybrid", "vector", "text", "knowledge"], default="hybrid"
    )
    search.add_argument(
        "--embedding",
        choices=["auto", "sparse", "siliconflow", "local-bge-m3"],
        default="auto",
    )
    search.add_argument("--model", default="BAAI/bge-m3")
    search.add_argument("--batch-size", type=int, default=32)

    augment_questions = sub.add_parser(
        "augment-questions",
        help="add question retrieval units to an existing vector store",
    )
    augment_questions.add_argument("--db", type=Path, required=True)
    augment_questions.add_argument(
        "--embedding",
        choices=["auto", "sparse", "siliconflow", "local-bge-m3"],
        default="auto",
    )
    augment_questions.add_argument("--model", default="BAAI/bge-m3")
    augment_questions.add_argument("--batch-size", type=int, default=32)

    text_index = sub.add_parser("rebuild-text-index", help="rebuild the FTS original-text index")
    text_index.add_argument("--db", type=Path, required=True)

    knowledge = sub.add_parser("rebuild-knowledge-units", help="extract grounded knowledge units")
    knowledge.add_argument("--db", type=Path, required=True)
    knowledge.add_argument("--trace-dir", type=Path, default=None)

    args = parser.parse_args(argv)
    if args.command == "build":
        stats = build_pdf_vector_store(
            pdf_dir=args.pdf_dir,
            out_dir=args.out,
            window_size=args.window_size,
            overlap=args.overlap,
            dims=args.dims,
            embedding=args.embedding,
            model=args.model,
            batch_size=args.batch_size,
            unit_types=parse_unit_types(args.unit_types),
            trace_dir=args.trace_dir,
        )
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    if args.command == "search":
        if args.mode == "text":
            store = LocalVectorStore(args.db)
        else:
            backend = create_embedding_backend_for_db(
                args.db,
                embedding=args.embedding,
                model=args.model,
                batch_size=args.batch_size,
            )
            store = LocalVectorStore(args.db, embedding_backend=backend)
        results = store.search(args.query, limit=args.limit, mode=args.mode)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    if args.command == "augment-questions":
        stats = augment_pdf_vector_store_questions(
            args.db,
            embedding=args.embedding,
            model=args.model,
            batch_size=args.batch_size,
        )
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    if args.command == "rebuild-text-index":
        store = LocalVectorStore(args.db)
        print(json.dumps(store.rebuild_text_index(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "rebuild-knowledge-units":
        store = LocalVectorStore(args.db)
        trace_dir = args.trace_dir or (args.db.parent / "traces")
        print(
            json.dumps(
                store.rebuild_knowledge_units(trace_dir=trace_dir), ensure_ascii=False, indent=2
            )
        )
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


def parse_unit_types(value: str) -> set[str]:
    allowed = {"sentence", "window", "paragraph", "question"}
    unit_types = {item.strip() for item in value.split(",") if item.strip()}
    unknown = unit_types - allowed
    if unknown:
        raise ValueError(f"unsupported unit types: {', '.join(sorted(unknown))}")
    return unit_types or allowed


if __name__ == "__main__":
    raise SystemExit(main())
