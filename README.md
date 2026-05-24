# txt-cleaner-cn / 中文 TXT 清理工具

This workspace contains a Python script for cleaning and formatting novel-style
TXT files.

本工作区用于批量清理和整理小说类 TXT 文件，包括编码、广告、网页残留、
论坛回复信息、乱码损坏行和基础排版。

## Directory Layout / 目录结构

```text
.
├── original_txt/       # Original TXT files, kept untouched / 原始 TXT，保持不动
├── cleaned/            # Cleaned UTF-8 TXT output / 清理后的 UTF-8 输出
├── clean_txt.py        # Batch cleanup script / 批处理脚本
├── rules.json          # Cleanup rules and profiles / 清理规则和模式
├── clean_report.csv    # Latest cleanup report / 最新清理报告
└── README.md
```

Non-TXT files such as PDF and DOCX are not processed by the script.

脚本只处理 `.txt` 文件，不处理 PDF、DOCX 等非 TXT 文件。

## Recommended Command / 推荐命令

Run the full cleanup and formatting flow:

运行完整清理和格式整理：

```powershell
python clean_txt.py --root original_txt --output-dir ..\cleaned --report ..\clean_report.csv --profile join
```

This reads from `original_txt/`, writes fresh cleaned files to `cleaned/`, and
updates `clean_report.csv`.

该命令会从 `original_txt/` 读取原始文件，重新生成 `cleaned/` 输出，并更新
`clean_report.csv`。

## Preview Only / 只预览不写入

Use `--dry-run` to generate only the report without writing output files:

使用 `--dry-run` 只生成报告，不写入清理后的文件：

```powershell
python clean_txt.py --root original_txt --output-dir ..\cleaned --report ..\clean_report.csv --profile join --dry-run
```

## Profiles / 清理模式

`safe`
: Minimal cleanup. Fixes encoding, removes obvious ads and noise. Does not
  aggressively format text.
  最保守模式。修正编码，删除明显广告和噪声，不主动做强排版。

`normal`
: Default cleanup. Removes ads, web residue, forum noise, normalizes punctuation,
  and applies paragraph indentation.
  默认清理。删除广告、网页残留、论坛噪声，统一部分标点，并整理段首缩进。

`format`
: Adds safer formatting cleanup, including adjacent duplicate line removal.
  Does not merge hard-wrapped lines.
  在 `normal` 基础上增加较安全的排版清理，例如删除相邻重复行，不合并断行。

`join`
: Recommended current profile. Includes `format` behavior and also merges
  likely hard-wrapped lines.
  当前推荐模式。包含 `format` 行为，并合并疑似硬换行造成的断行。

`aggressive`
: Strongest mode. Also normalizes chapter lines. Use only after checking output.
  最强模式。还会进一步规范章节行，建议检查输出后再长期使用。

## What The Script Cleans / 清理内容

- Encoding detection: `utf-8-sig`, `utf-8`, `gb18030`, `big5`
- Output encoding: UTF-8
- BOM, control characters, zero-width characters
- Common ads, URLs, emails, site watermarks
- Obfuscated ads such as `01bz`, `第一版主小说站`, mixed full-width punctuation
- HTML/CSS leftovers such as `span style=size: 15px`
- Broken web markup such as bad `target="blank"` fragments
- Forum metadata blocks such as UID, Rank, reading permission, status, reply bars
- Inline forum residue such as `本帖最后由...编辑`, rating records, toolbox text
- Repeated-letter damaged lines such as `eeeeeeeeeeee`
- Empty numbered section headers left after damaged content is removed
- Extra blank lines
- Adjacent duplicate lines
- Hard-wrapped paragraphs, when using `join`
- Long one-line files that use embedded full-width spaces as paragraph breaks

中文对应：

- 自动识别编码：`utf-8-sig`、`utf-8`、`gb18030`、`big5`
- 输出统一为 UTF-8
- 清理 BOM、控制字符、零宽字符
- 清理常见广告、网址、邮箱、站点水印
- 清理变形广告，例如 `01bz`、`第一版主小说站`、混合全角符号广告
- 清理 HTML/CSS 残留，例如 `span style=size: 15px`
- 清理损坏网页标记，例如坏掉的 `target="blank"` 片段
- 清理论坛用户信息块，例如 UID、Rank、阅读权限、状态、回复工具栏
- 清理行内论坛残留，例如 `本帖最后由...编辑`、评分记录、工具栏文字
- 清理重复字母损坏行，例如 `eeeeeeeeeeee`
- 删除损坏内容清理后留下的空编号标题
- 压缩多余空行
- 删除相邻重复行
- 在 `join` 模式下合并疑似硬换行段落
- 拆分使用全角空格伪装段落的超长单行文件

## Report Columns / 报告字段

`clean_report.csv` records one row per input TXT file.

`clean_report.csv` 每个输入 TXT 文件对应一行记录。

Important columns:

重要字段：

```text
encoding
original_bytes
cleaned_bytes
original_lines
cleaned_lines
ad_lines_removed
inline_ads_removed
noise_lines_removed
markup_removed
forum_lines_removed
duplicate_lines_removed
joined_lines
embedded_paragraphs_split
blank_lines_collapsed
mojibake_repaired
changed
skipped
warnings
```

Common warnings:

常见 `warnings`：

```text
decode_fallback_utf8_replace
replacement_char_found
repeated_letter_damage_removed
empty_numbered_section_removed
starts_at_numbered_section_326
```

For example, `starts_at_numbered_section_326` means the cleaned file appears to
start from section 326, so the original file may be incomplete or a later volume.

例如 `starts_at_numbered_section_326` 表示清理后的文件疑似从第 326 节开始，
原始文件可能是残本、分卷文件，或者前文缺失。

## Regenerating From Scratch / 从头重新生成

To regenerate `cleaned/` from the untouched originals:

从未改动的 `original_txt/` 重新生成 `cleaned/`：

```powershell
Remove-Item -LiteralPath cleaned -Recurse -Force
New-Item -ItemType Directory -Path cleaned
python clean_txt.py --root original_txt --output-dir ..\cleaned --report ..\clean_report.csv --profile join
```

## Notes / 注意事项

- Keep `original_txt/` as the source of truth.
- Edit `rules.json` when new ads or formatting residue are found.
- Prefer `--dry-run` after changing rules, then inspect `clean_report.csv`.
- When a file is reported as starting from a high section number, check whether
  another fuller version already exists in `cleaned/`.
- The script skips `cleaned/`, `joined_preview/`, `__pycache__/`, and backup
  folders when scanning.

中文说明：

- 保留 `original_txt/` 作为唯一原始来源。
- 发现新的广告、网页残留或排版垃圾时，优先改 `rules.json` 或脚本规则。
- 修改规则后建议先用 `--dry-run`，再查看 `clean_report.csv`。
- 如果报告显示文件从很大的章节编号开始，先检查 `cleaned/` 里是否已有更完整版本。
- 扫描时脚本会跳过 `cleaned/`、`joined_preview/`、`__pycache__/` 和备份目录。
