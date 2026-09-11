#!/usr/bin/env python3
"""Batch clean TXT files in the current workspace.

The default mode is conservative: cleaned files are written to ./cleaned and
the original files are left untouched.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


SCRIPT_NAME = Path(sys.executable).name if getattr(sys, "frozen", False) else Path(__file__).name

def _resolve_default_rules() -> Path:
    if getattr(sys, "frozen", False):
        # Check adjacent to executable first
        exe_rules = Path(sys.executable).parent / "rules.json"
        if exe_rules.exists():
            return exe_rules
        # Fall back to bundled resource in PyInstaller _MEIPASS
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and (Path(meipass) / "rules.json").exists():
            return Path(meipass) / "rules.json"
    return Path(__file__).with_name("rules.json")

DEFAULT_RULES = _resolve_default_rules()
DEFAULT_OUTPUT_DIR = "cleaned"


@dataclass
class Stats:
    path: str
    output_path: str = ""
    encoding: str = ""
    original_bytes: int = 0
    cleaned_bytes: int = 0
    original_lines: int = 0
    cleaned_lines: int = 0
    ad_lines_removed: int = 0
    inline_ads_removed: int = 0
    noise_lines_removed: int = 0
    markup_removed: int = 0
    forum_lines_removed: int = 0
    duplicate_lines_removed: int = 0
    joined_lines: int = 0
    embedded_paragraphs_split: int = 0
    blank_lines_collapsed: int = 0
    mojibake_repaired: bool = False
    changed: bool = False
    skipped: str = ""
    warnings: list[str] = field(default_factory=list)


def load_rules(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def compile_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def decode_bytes(data: bytes) -> tuple[str, str, list[str]]:
    warnings: list[str] = []
    candidates: list[tuple[int, int, str, str]] = []
    encodings = ["utf-8-sig", "utf-8", "gb18030", "big5"]

    for enc in encodings:
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        score = text_quality_score(text)
        candidates.append((score, -encodings.index(enc), enc, text))

    if not candidates:
        text = data.decode("utf-8", errors="replace")
        warnings.append("decode_fallback_utf8_replace")
        return text, "utf-8-replace", warnings

    candidates.sort(reverse=True)
    _score, _order, enc, text = candidates[0]
    if "\ufffd" in text:
        warnings.append("replacement_char_found")
    return text, enc, warnings


def text_quality_score(text: str) -> int:
    if not text:
        return 0

    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
    bad_markers = sum(text.count(s) for s in ("�", "锟", "銆", "绗?", "鈥", "€", "\x00"))
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\r\n\t")
    return cjk * 3 + printable - bad_markers * 20 - controls * 10


def maybe_repair_mojibake(text: str) -> tuple[str, bool]:
    markers = sum(text.count(s) for s in ("銆", "绗?", "鈥", "€", "锛", "锟", "闂", "鍦"))
    if markers < 5:
        return text, False

    try:
        repaired = text.encode("gb18030", errors="strict").decode("utf-8", errors="strict")
    except UnicodeError:
        return text, False

    if text_quality_score(repaired) > text_quality_score(text) + 100:
        return repaired, True
    return text, False


def normalize_basic_text(text: str) -> str:
    text = text.replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)
    return text


def remove_markup_residue(text: str, rules: dict, stats: Stats) -> str:
    for pattern in compile_patterns(rules.get("markup_patterns", [])):
        text, count = pattern.subn("", text)
        stats.markup_removed += count
    return text


def split_embedded_paragraphs(text: str, stats: Stats) -> str:
    result: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if len(stripped) < 180 or stripped.count("　　") < 2:
            result.append(line)
            continue

        parts = [part.strip() for part in re.split(r"　{2,}", stripped) if part.strip()]
        if len(parts) <= 1:
            result.append(line)
            continue

        # Avoid exploding table-like or code-like text; this is aimed at prose that
        # used full-width indentation as paragraph separators inside one physical line.
        cjk_parts = sum(1 for part in parts if re.search(r"[\u4e00-\u9fff]", part))
        if cjk_parts < max(2, len(parts) // 2):
            result.append(line)
            continue

        result.extend("　　" + part.lstrip("　 ") for part in parts)
        stats.embedded_paragraphs_split += len(parts) - 1
    return "\n".join(result)


def fold_for_ad_detection(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).lower()
    replacements = {
        "。": ".",
        "．": ".",
        "点": ".",
        "説": "说",
        "說": "说",
        "壹": "一",
        "苐": "第",
        "ｗ": "w",
        "Ｗ": "w",
    }
    for old, new in replacements.items():
        folded = folded.replace(old, new)
    return re.sub(r"[\s　'\"‘’“”~～`!！@#$￥%^&*()（）_\-+=|\\/{}\[\]【】:：;；,<，>。.?？·]+", "", folded)


def is_obfuscated_ad_line(line: str) -> bool:
    folded = fold_for_ad_detection(line)
    if not folded:
        return False
    compact_len = len(folded)
    markers = (
        "01bz",
        "www01bz",
        "第一版主小说站",
        "第一版主小说网",
        "版主小说网",
        "版主小说站",
        "搜第一版主小说站",
        "diyibanzhu",
    )
    if not any(marker in folded for marker in markers):
        return False
    slogan_markers = ("读精彩", "搜第一版主小说站", "第一版主小说站官网", "第一版主小说网")
    return compact_len <= 80 or any(marker in folded for marker in slogan_markers)


def clean_filename(name: str, filename_patterns: list[re.Pattern[str]]) -> str:
    stem = Path(name).stem
    suffix = Path(name).suffix
    for pattern in filename_patterns:
        stem = pattern.sub("", stem)
    stem = re.sub(r"[\s._-]+$", "", stem).strip()
    return (stem or Path(name).stem) + suffix


def unique_output_path(path: Path, used_outputs: set[Path]) -> Path:
    candidate = path
    index = 2
    while candidate.resolve() in used_outputs:
        candidate = path.with_name(f"{path.stem}__{index}{path.suffix}")
        index += 1
    used_outputs.add(candidate.resolve())
    return candidate


def is_chapter_line(line: str, chapter_patterns: list[re.Pattern[str]]) -> bool:
    stripped = line.strip()
    if len(stripped) > 60:
        return False
    return any(p.match(stripped) for p in chapter_patterns)


def normalize_chapter_line(line: str, chapter_patterns: list[re.Pattern[str]]) -> str:
    stripped = line.strip()
    for pattern in chapter_patterns:
        match = pattern.match(stripped)
        if not match:
            continue
        if len(match.groups()) >= 3 and match.group(1).startswith("第"):
            title = match.group(3).strip()
            return f"{match.group(1)} {title}".rstrip()
        if match.group(1).isdigit():
            number = int(match.group(1))
            title = match.group(2).strip()
            return f"第{number:03d}章 {title}".rstrip()
    return stripped


def normalize_punctuation(line: str) -> str:
    table = str.maketrans({
        "﹐": "，",
        "､": "、",
        "﹑": "、",
        "﹒": "。",
        "．": "。",
        "﹗": "！",
        "﹖": "？",
        "：": "：",
    })
    line = line.translate(table)
    line = re.sub(r"[ \t]+([，。！？、；：）」』》])", r"\1", line)
    line = re.sub(r"([（「『《])[ \t]+", r"\1", line)
    line = re.sub(r"([一-龥])\s+([，。！？、；：])", r"\1\2", line)
    line = re.sub(r"([，。！？、；：]){2,}", lambda m: m.group(0)[0], line)
    return line


def should_indent(line: str, chapter_patterns: list[re.Pattern[str]]) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if is_chapter_line(stripped, chapter_patterns):
        return False
    if re.match(r"^[┏┓┗┛┃━╔╗╚╝║═]", stripped):
        return False
    if re.match(r"^[A-Za-z0-9_./:-]{4,}$", stripped):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", stripped))


def looks_like_repeated_letter_damage(line: str) -> bool:
    stripped = line.strip()
    if not re.search(r"[\u4e00-\u9fff]", stripped):
        return False
    return bool(re.search(r"([A-Za-z])\1{12,}", stripped))


def remove_duplicate_lines(lines: list[str], stats: Stats) -> list[str]:
    result: list[str] = []
    previous = None
    repeat_count = 0
    for line in lines:
        key = line.strip()
        if key and key == previous:
            repeat_count += 1
            if repeat_count >= 1:
                stats.duplicate_lines_removed += 1
                continue
        else:
            repeat_count = 0
        result.append(line)
        previous = key if key else None
    return result


def leading_decorative_title_key(line: str) -> str | None:
    stripped = line.strip()
    match = re.match(r"^☆、【([^】]{1,80})】\s*[（(][^）)]{1,30}[）)]\s*$", stripped)
    return match.group(1).strip() if match else None


def remove_stale_leading_titles(
    lines: list[str], chapter_patterns: list[re.Pattern[str]], stats: Stats
) -> list[str]:
    scan_limit = min(len(lines), 20)
    title_indices: dict[str, list[int]] = {}

    for index in range(scan_limit):
        stripped = lines[index].strip()
        if not stripped:
            continue

        key = leading_decorative_title_key(stripped)
        if key:
            title_indices.setdefault(key, []).append(index)
            continue

        if looks_like_metadata_line(stripped) or re.match(r"^【[^】]{1,80}】$", stripped):
            continue

        if is_chapter_line(stripped, chapter_patterns) or len(stripped) > 80:
            break

    stale = {
        index
        for indices in title_indices.values()
        if len(indices) > 1
        for index in indices[:-1]
    }
    if not stale:
        return lines

    stats.duplicate_lines_removed += len(stale)
    return [line for index, line in enumerate(lines) if index not in stale]


def is_forum_action_line(line: str) -> bool:
    stripped = line.strip()
    return ("查看資料" in stripped or "查看资料" in stripped) and ("引用回覆" in stripped or "引用回复" in stripped)


def is_forum_floor_line(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}[：:]\d{2}\s+#\d+\s*$", stripped))


def is_forum_profile_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    patterns = (
        r"^UID\s+\d+",
        r"^Rank[：:]\s*\d+",
        r"^精华\s+\d+",
        r"^積分\s+\d+",
        r"^积分\s+\d+",
        r"^帖子\s+\d+",
        r"^阅读权限\s+\d+",
        r"^閱讀權限\s+\d+",
        r"^注册\s+\d{4}-\d{1,2}-\d{1,2}",
        r"^註冊\s+\d{4}-\d{1,2}-\d{1,2}",
        r"^状态\s+(离线|在线)",
        r"^狀態\s+(離線|在線)",
        r"^\[\s*本帖最后由.+编辑\s*\]$",
        r"^\[\s*本帖最後由.+編輯\s*\]$",
        r"^原帖由.+发表",
        r"^原帖由.+發表",
        r"^发表于\s+.+",
        r"^發表於\s+.+",
        r"^(论坛元老|論壇元老|新手上路|注册会员|註冊會員|高级会员|高級會員|中级会员|中級會員)$",
    )
    return any(re.match(pattern, stripped) for pattern in patterns)


def remove_inline_forum_residue(line: str, stats: Stats) -> str:
    patterns = (
        r"\[\s*本帖最后由[^\]]+?编辑\s*\]",
        r"\[\s*本帖最後由[^\]]+?編輯\s*\]",
        r"本帖最后由\S+?于\d{4}-\d{1,2}-\d{1,2}\s*\d{1,2}[：:]\d{2}\s*(AM|PM)?编辑",
        r"本帖最近评分记录.*$",
        r"引用\s+使用道具\s+报告\s+回复\s+TOP.*$",
        r"引用\s+使用道具\s+報告\s+回覆\s+TOP.*$",
        r"放入宝箱.*$",
        r"已有\s*\d+\s*人把本帖放入宝箱.*$",
        r"^.*?UID\s*\d+.*?(状态\s*离线|状态\s*在线|狀態\s*離線|狀態\s*在線)",
    )
    original = line
    for pattern in patterns:
        line, count = re.subn(pattern, "", line, flags=re.IGNORECASE)
        stats.forum_lines_removed += count
    if line != original:
        line = line.strip()
    return line


def remove_forum_noise(lines: list[str], stats: Stats) -> list[str]:
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if is_forum_floor_line(line):
            stats.forum_lines_removed += 1
            i += 1
            continue

        if is_forum_action_line(line):
            stats.forum_lines_removed += 1
            i += 1
            # Drop the compact user card that usually follows the action bar.
            while i < len(lines):
                current = lines[i]
                stripped = current.strip()
                if not stripped or is_forum_profile_line(current):
                    stats.forum_lines_removed += 1
                    i += 1
                    continue
                if i + 1 < len(lines) and is_forum_profile_line(lines[i + 1]):
                    stats.forum_lines_removed += 1
                    i += 1
                    continue
                break
            continue

        if is_forum_profile_line(line) and line.strip():
            stats.forum_lines_removed += 1
            i += 1
            continue

        line = remove_inline_forum_residue(line, stats)
        if not line.strip():
            i += 1
            continue
        result.append(line)
        i += 1
    return result


def is_sentence_end(line: str) -> bool:
    return bool(re.search(r"[。！？!?；;：:」』》)”）…]$", line.rstrip()))


def looks_like_metadata_line(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^(作者|字数|標題|标题|内容简介|【内容简介】)\s*[：:]", stripped))


def should_join_hard_wrap(prev: str, current: str, chapter_patterns: list[re.Pattern[str]]) -> bool:
    left = prev.strip()
    right = current.strip()
    if not left or not right:
        return False
    if is_chapter_line(left, chapter_patterns) or is_chapter_line(right, chapter_patterns):
        return False
    if looks_like_metadata_line(left) or looks_like_metadata_line(right):
        return False
    if is_sentence_end(left):
        return False
    if re.match(r"^[“\"「『《【（(]", right):
        return False
    if not re.search(r"[\u4e00-\u9fff]", left + right):
        return False
    if len(left) < 4:
        return False
    return True


def join_broken_lines(lines: list[str], chapter_patterns: list[re.Pattern[str]], stats: Stats) -> list[str]:
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            if result:
                next_index = i + 1
                while next_index < len(lines) and not lines[next_index].strip():
                    next_index += 1
                if next_index < len(lines) and should_join_hard_wrap(result[-1], lines[next_index], chapter_patterns):
                    stats.blank_lines_collapsed += next_index - i
                    i = next_index
                    continue
            result.append(line)
            i += 1
            continue
        if not result or is_chapter_line(stripped, chapter_patterns):
            result.append(line)
            i += 1
            continue
        prev = result[-1].rstrip()
        if not prev.strip():
            result.append(line)
            i += 1
            continue
        if should_join_hard_wrap(prev, line, chapter_patterns):
            result[-1] = prev + stripped
            stats.joined_lines += 1
        else:
            result.append(line)
        i += 1
    return result


def collapse_blank_lines(lines: list[str], stats: Stats) -> list[str]:
    result: list[str] = []
    blank_count = 0
    for line in lines:
        if line.strip():
            blank_count = 0
            result.append(line)
            continue
        blank_count += 1
        if blank_count <= 1:
            result.append("")
        else:
            stats.blank_lines_collapsed += 1
    while result and not result[0].strip():
        result.pop(0)
        stats.blank_lines_collapsed += 1
    while result and not result[-1].strip():
        result.pop()
        stats.blank_lines_collapsed += 1
    return result


def tidy_chapter_spacing(lines: list[str], chapter_patterns: list[re.Pattern[str]]) -> list[str]:
    result: list[str] = []
    for line in lines:
        if is_chapter_line(line, chapter_patterns):
            if result and result[-1].strip():
                result.append("")
            result.append(line.strip())
            result.append("")
        else:
            result.append(line)
    return collapse_blank_lines(result, Stats(path="chapter_spacing"))


def first_numbered_section(line: str) -> int | None:
    stripped = line.strip()
    match = re.match(r"^([0-9]{1,4})[、.．:：\s　-]+", stripped)
    if match:
        return int(match.group(1))
    match = re.match(r"^第([0-9]{1,4})[章节回卷部集篇]", stripped)
    if match:
        return int(match.group(1))
    return None


def add_structural_warnings(lines: list[str], stats: Stats) -> None:
    for line in lines[:120]:
        number = first_numbered_section(line)
        if number is None:
            continue
        if number > 20:
            stats.warnings.append(f"starts_at_numbered_section_{number}")
        return


def remove_empty_numbered_sections(lines: list[str], stats: Stats) -> list[str]:
    result: list[str] = []
    i = 0
    while i < len(lines):
        if first_numbered_section(lines[i]) is None:
            result.append(lines[i])
            i += 1
            continue

        next_index = i + 1
        while next_index < len(lines) and not lines[next_index].strip():
            next_index += 1

        if next_index < len(lines) and first_numbered_section(lines[next_index]) is not None:
            stats.noise_lines_removed += next_index - i
            if "empty_numbered_section_removed" not in stats.warnings:
                stats.warnings.append("empty_numbered_section_removed")
            i = next_index
            continue

        result.append(lines[i])
        i += 1
    return result


def clean_text(text: str, rules: dict, profile_name: str, stats: Stats) -> str:
    profile = rules["profiles"][profile_name]
    ad_patterns = compile_patterns(rules.get("ad_line_patterns", []))
    inline_ad_patterns = compile_patterns(rules.get("inline_ad_patterns", []))
    noise_patterns = compile_patterns(rules.get("noise_line_patterns", []))
    chapter_patterns = compile_patterns(rules.get("chapter_patterns", []))

    text = normalize_basic_text(text)
    text, repaired = maybe_repair_mojibake(text)
    stats.mojibake_repaired = repaired
    text = normalize_basic_text(text)
    text = remove_markup_residue(text, rules, stats)
    text = split_embedded_paragraphs(text, stats)
    stats.original_lines = text.count("\n") + (1 if text else 0)

    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.replace("\t", "    ").rstrip()
        line = re.sub(r"[ 　]+$", "", line)

        stripped = line.strip()
        if profile["remove_ads"] and stripped:
            if any(p.search(stripped) for p in noise_patterns):
                stats.noise_lines_removed += 1
                continue
            if looks_like_repeated_letter_damage(stripped):
                stats.noise_lines_removed += 1
                if "repeated_letter_damage_removed" not in stats.warnings:
                    stats.warnings.append("repeated_letter_damage_removed")
                continue
            if any(p.search(stripped) for p in ad_patterns) or is_obfuscated_ad_line(stripped):
                stats.ad_lines_removed += 1
                continue
            for pattern in inline_ad_patterns:
                new_line, count = pattern.subn("", line)
                if count:
                    stats.inline_ads_removed += count
                    line = new_line.rstrip()

        if profile["normalize_punctuation"]:
            line = normalize_punctuation(line)

        line = re.sub(r"\bspan\s+\d+\s*px", "", line, flags=re.IGNORECASE)

        if profile["normalize_chapters"] and is_chapter_line(line, chapter_patterns):
            line = normalize_chapter_line(line, chapter_patterns)

        if profile["indent_paragraphs"] and should_indent(line, chapter_patterns):
            line = "　　" + line.strip().lstrip("　 ")
        else:
            line = line.strip() if is_chapter_line(line, chapter_patterns) else line

        lines.append(line)

    if profile["join_broken_lines"]:
        lines = join_broken_lines(lines, chapter_patterns, stats)
    if profile["remove_duplicate_lines"]:
        lines = remove_duplicate_lines(lines, stats)
        lines = remove_stale_leading_titles(lines, chapter_patterns, stats)
    lines = remove_forum_noise(lines, stats)

    lines = collapse_blank_lines(lines, stats)
    lines = tidy_chapter_spacing(lines, chapter_patterns)
    lines = remove_empty_numbered_sections(lines, stats)
    lines = collapse_blank_lines(lines, stats)
    add_structural_warnings(lines, stats)
    cleaned = "\n".join(lines).rstrip() + "\n"
    stats.cleaned_lines = cleaned.count("\n")
    return cleaned


def iter_txt_files(root: Path, single_file: Path | None, output_dir: Path) -> Iterable[Path]:
    if single_file:
        yield single_file
        return

    ignored_dirs = {output_dir.resolve(), root.joinpath("__pycache__").resolve(), root.joinpath("joined_preview").resolve()}
    for path in root.rglob("*.txt"):
        resolved_parent = path.parent.resolve()
        if any(resolved_parent == d or d in resolved_parent.parents for d in ignored_dirs):
            continue
        if any(part.startswith("backup_") for part in path.parts):
            continue
        if path.name == SCRIPT_NAME:
            continue
        yield path


def write_report(report_path: Path, rows: list[Stats]) -> None:
    fields = [
        "path",
        "output_path",
        "encoding",
        "original_bytes",
        "cleaned_bytes",
        "original_lines",
        "cleaned_lines",
        "ad_lines_removed",
        "inline_ads_removed",
        "noise_lines_removed",
        "markup_removed",
        "forum_lines_removed",
        "duplicate_lines_removed",
        "joined_lines",
        "embedded_paragraphs_split",
        "blank_lines_collapsed",
        "mojibake_repaired",
        "changed",
        "skipped",
        "warnings",
    ]
    with report_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for stats in rows:
            row = {field: getattr(stats, field) for field in fields}
            row["warnings"] = ";".join(stats.warnings)
            writer.writerow(row)


def make_backup_dir(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / f"backup_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    return backup_dir


def process_file(
    path: Path,
    root: Path,
    output_dir: Path,
    rules: dict,
    profile: str,
    dry_run: bool,
    in_place: bool,
    backup_dir: Path | None,
    used_outputs: set[Path],
) -> Stats:
    stats = Stats(path=str(path))
    data = path.read_bytes()
    stats.original_bytes = len(data)
    text, encoding, warnings = decode_bytes(data)
    stats.encoding = encoding
    stats.warnings.extend(warnings)

    cleaned = clean_text(text, rules, profile, stats)
    output_bytes = cleaned.encode("utf-8")
    stats.cleaned_bytes = len(output_bytes)
    stats.changed = output_bytes != data

    filename_patterns = compile_patterns(rules.get("filename_strip_patterns", []))
    relative = path.relative_to(root) if path.is_relative_to(root) else Path(path.name)
    output_name = clean_filename(relative.name, filename_patterns)

    if in_place:
        output_path = path
    else:
        output_path = unique_output_path(output_dir / relative.parent / output_name, used_outputs)
    stats.output_path = str(output_path)

    if dry_run:
        return stats

    if in_place:
        if backup_dir is None:
            raise RuntimeError("backup_dir is required for in-place mode")
        backup_path = backup_dir / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_path)
        path.write_bytes(output_bytes)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(output_bytes)

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean novel-style TXT files.")
    parser.add_argument("--root", default=".", help="Workspace root. Defaults to current directory.")
    parser.add_argument("--rules", default=str(DEFAULT_RULES), help="Path to rules.json.")
    parser.add_argument("--profile", choices=["safe", "normal", "format", "join", "aggressive"], default="normal")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory for cleaned files.")
    parser.add_argument("--file", help="Process only one TXT file.")
    parser.add_argument("--dry-run", action="store_true", help="Generate report only; do not write cleaned files.")
    parser.add_argument("--in-place", action="store_true", help="Overwrite originals after creating a backup directory.")
    parser.add_argument("--report", default="clean_report.csv", help="CSV report path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    rules_path = Path(args.rules).resolve()
    output_dir = (root / args.output_dir).resolve()
    report_path = (root / args.report).resolve()
    single_file = Path(args.file).resolve() if args.file else None

    if not rules_path.exists():
        print(f"Rules file not found: {rules_path}", file=sys.stderr)
        return 2
    if single_file and not single_file.exists():
        print(f"TXT file not found: {single_file}", file=sys.stderr)
        return 2

    rules = load_rules(rules_path)
    files = list(iter_txt_files(root, single_file, output_dir))
    backup_dir = None if args.dry_run or not args.in_place else make_backup_dir(root)
    rows: list[Stats] = []
    used_outputs: set[Path] = set()

    for path in files:
        try:
            rows.append(process_file(path, root, output_dir, rules, args.profile, args.dry_run, args.in_place, backup_dir, used_outputs))
        except Exception as exc:  # Keep batch processing moving and report the failed file.
            rows.append(Stats(path=str(path), skipped=type(exc).__name__, warnings=[str(exc)]))

    write_report(report_path, rows)

    changed = sum(1 for row in rows if row.changed)
    repaired = sum(1 for row in rows if row.mojibake_repaired)
    removed_ads = sum(row.ad_lines_removed + row.inline_ads_removed for row in rows)
    mode = "dry-run" if args.dry_run else ("in-place" if args.in_place else f"output: {output_dir}")
    print(f"Processed {len(rows)} txt file(s), changed {changed}, repaired mojibake {repaired}, removed ad hits {removed_ads}.")
    print(f"Mode: {mode}")
    print(f"Report: {report_path}")
    if backup_dir:
        print(f"Backup: {backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
