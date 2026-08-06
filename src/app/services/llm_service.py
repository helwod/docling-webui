import json
import re
from openai import AsyncOpenAI
from app.repositories.setting_repo import SettingRepo


def _clean_json_text(s: str) -> str:
    """修复 LLM 常见 JSON 瑕疵：尾随逗号、// 行注释、/* */ 块注释。"""
    s = re.sub(r",(\s*[}\]])", r"\1", s)          # 对象/数组尾部的尾随逗号
    s = re.sub(r"//[^\n]*", "", s)                # 行注释
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)  # 块注释
    return s.strip()


def _clean_ocr_md(text: str) -> str:
    """清理注入 LLM 提示词的 OCR Markdown：去掉空行与 Markdown 格式标记，保留可读文本与表格数据。

    处理规则：
    - 丢弃空行/纯空白行
    - 丢弃表格分隔行（如 |---|---|，仅由 |、-、:、空格构成）
    - 去掉标题 # 标记、加粗/斜体 ** *、行内代码 `、引用 >、列表符号 - * + 等语法标记，保留其文字
    - 链接 [text](url) / 图片 ![alt](url) 仅保留文字，丢弃 url
    - 保留表格数据行中的 | 列分隔（用于区分列），不破坏数据结构
    """
    if not text:
        return ""
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue  # 空行/纯空白行
        # 去掉 HTML 注释（如 OCR 中夹在标签与值之间的 <!-- image --> 图片占位）
        s = re.sub(r"<!--.*?-->", "", s).strip()
        if not s:
            continue
        # 表格分隔行：仅含 |、-、:、空格
        if "-" in s and re.match(r"^\|?[\s:|-]+\|?$", s):
            continue
        # 去掉行首标题 # 号
        s = re.sub(r"^#{1,6}\s*", "", s)
        # 去掉行首列表符号 - * + （后接空白）
        s = re.sub(r"^([-*+])\s+", "", s)
        # 去掉引用 >
        s = re.sub(r"^>\s*", "", s)
        # 去掉加粗/斜体/行内代码标记
        s = s.replace("**", "").replace("__", "").replace("`", "")
        s = re.sub(r"(?<!\*)\*(?!\*)", "", s)
        # 图片/链接：![alt](url) 或 [text](url) -> 保留文字
        s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
        s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
        out.append(s)
    return "\n".join(out)


def _strip_cell_label(value: str, header: str) -> str:
    """兜底：判断单元格值是否「纯字段标签而非有效数据」，若是则留空，否则仅剥离标签前缀。

    规则：
    - 若值剥离后等于字段名本身（如 header="甲方"、value="甲方"），说明这只是标签、没有数据 → 返回 ""。
    - 若值以『字段名（+可选括号注释）+ 分隔符』开头，去掉该前缀，仅留数据
      （如 "甲方：某某公司" -> "某某公司"；"甲方（盖章）：某某公司" -> "某某公司"；"甲方：：某某" -> "某某"）。
    - 若剥离前缀后无任何内容（只是标签没有数据），返回 ""。
    - 仅在能明确识别『字段名 + 分隔符』时才剥离，避免误删合法数据。
    """
    if not value or not header:
        return value
    v = value.strip()
    h = header.strip()
    if not h:
        return v
    # 值本身就是字段名（纯标签、无数据）→ 视为无效数据，留空
    if v == h:
        return ""
    # 整串为「字段名（+可选括号注释）+ 可选分隔符」即到头、无数据 → 纯标签，留空
    # 例："甲方（盖章）"、"甲方："、"合同编号（见下）" 等
    pure = re.compile(r"^\s*" + re.escape(h) + r"(?:（[^）]*）|\([^)]*\))?\s*[:：\-－–—=]*\s*$")
    if pure.match(v):
        return ""
    # 字段名 + 可选括号注释(（盖章）/ (签名) 等) + 一个或多个分隔符(:：:-=等)
    pat = re.compile(r"^\s*" + re.escape(h) + r"(?:（[^）]*）|\([^)]*\))?\s*[:：\-－–—=]+\s*")
    m = pat.match(v)
    if m:
        rest = v[m.end():].strip()
        # 剥离后无内容 → 只是标签、没有数据 → 留空
        return rest if rest else ""
    return v


# OCR 误插入空格主要出现在 CJK（中文/中文标点/全角字符）与字母/数字之间，
# 以及被空格拆开的连字符、纯数字串内部。范围覆盖常用汉字、扩展 A、兼容汉字、
# CJK 标点与全角字符。
_CJK = r"\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3000-\u303f\uff00-\uffef"
_ADDR_RE = re.compile(r"地址|住址|addr", re.IGNORECASE)


def _normalize_spaces(value):
    """规范化 OCR 在字段名 / 字段值中【误插入】的无意义空格与换行，保留有意义空格。

    规则：
    - 去掉 OCR 排版折行产生的换行符：源文档常把同一字段（尤其地址）折成 2~3 行，
      换行只是排版伪分隔——先统一替换为空格（CJK 相邻时空格随后会被去掉；英文相邻时保留为词间隔），
      再折叠连续空格，避免字段值里混入换行/多行（如 "北京\n海淀" -> "北京 海淀" -> "北京海淀"）。
    - 去掉 CJK（中文 / 中文标点 / 全角字符）之间的空格，以及 CJK 与 ASCII 之间的空格
      （如 "一 万 圆 整" -> "一万圆整"；"金额 12000" -> "金额12000"）；
    - 去掉由连字符串接的「字母/数字 - 字母/数字」之间被拆开的空格
      （如 "HT - 2024 - 001" -> "HT-2024-001"）；
    - 去掉纯数字 / 数字+*掩码 串内部被拆开的空格
      （如 "4305 23***** 4314" -> "430523*****4314"）；
    - 去掉千分位逗号两侧被拆开的空格（仅当逗号两侧都是数字，如 "12, 500.00" -> "12,500.00"），
      不误伤英文 "Room 502, No.5"（逗号后是字母）。
    - 保留英文单词之间的空格（有意义的分隔，如 "Contract No. 2024"）。
    """
    if not isinstance(value, str) or not value:
        return value
    s = value
    # 0) 换行 -> 空格（折行合并），再折叠因折行产生的连续空格
    s = re.sub(r"\r\n|\r|\n", " ", s)
    s = re.sub(r" {2,}", " ", s)
    # 1) CJK 与任意字符之间、CJK 与 CJK 之间的空格
    s = re.sub(rf"\s+(?=[{_CJK}])", "", s)   # 空格后接 CJK
    s = re.sub(rf"(?<=[{_CJK}])\s+", "", s)  # CJK 后接空格
    # 2) 连字符两侧被空格分开的「字母/数字 - 字母/数字」
    s = re.sub(r"([A-Za-z0-9])\s*-\s*([A-Za-z0-9])", r"\1-\2", s)
    # 3) 纯数字 / 数字+* 串内部的空格
    s = re.sub(r"(?<=[0-9*])\s+(?=[0-9*])", "", s)
    # 3b) 千分位逗号两侧被 OCR 拆开的空格（如 "12, 500.00" -> "12,500.00"），
    #     仅当逗号【两侧都是数字】才压缩，绝不误伤英文 "Room 502, No.5"（逗号后是字母）。
    s = re.sub(r"(?<=[0-9])\s*,\s*(?=[0-9])", ",", s)
    return s.strip()


def _normalize_result(result):
    """对 LLM 返回的 tables 做兜底清洗：
    1) 去掉单元格值里重复出现的字段名/标签前缀（_strip_cell_label）；
    2) 去掉 OCR 在字段名与字段值中【误插入】的无意义空格（_normalize_spaces），
       保持中文连写、编号/日期/金额原貌，仅保留原文有意义的分隔。
    表头同样去空格，并重映射 dict 行的键，保持 headers 与 row 对齐。
    """
    if isinstance(result, dict):
        tables = result.get("tables")
        if isinstance(tables, list):
            for t in tables:
                if not isinstance(t, dict):
                    continue
                headers = t.get("headers") or []
                rows = t.get("rows") or []
                if not headers or not rows:
                    continue
                # 表头去无意义空格（headers 与 row 键需同步更新）
                new_headers = [_normalize_spaces(h) for h in headers]
                for row in rows:
                    if isinstance(row, dict):
                        new_row = {}
                        for old_h, new_h in zip(headers, new_headers):
                            val = row.get(old_h)
                            if isinstance(val, str):
                                norm = _normalize_spaces(val)
                                # 地址字段（中文）强制去空格：中文地址一律连写，不留空格
                                if _ADDR_RE.search(new_h) and re.search(_CJK, norm):
                                    norm = norm.replace(" ", "")
                                val = _strip_cell_label(norm, new_h)
                            new_row[new_h] = val
                        # 保留不在 headers 中的其它键（保险）
                        for k, v in row.items():
                            if k not in headers:
                                new_row[_normalize_spaces(k) if isinstance(k, str) else k] = v
                        row.clear()
                        row.update(new_row)
                        t["headers"] = new_headers
                    elif isinstance(row, (list, tuple)):
                        for idx, h in enumerate(new_headers):
                            if idx < len(row) and isinstance(row[idx], str):
                                norm = _normalize_spaces(row[idx])
                                if _ADDR_RE.search(h) and re.search(_CJK, norm):
                                    norm = norm.replace(" ", "")
                                row[idx] = _strip_cell_label(norm, h)
                        t["headers"] = new_headers
    return result

# LLM 角色定义默认值（用户可在「设置」中覆盖）。
# 这就是所有 LLM 调用共用的【公共抽取口径】：身份 + 照抄原文 + 标签/值判断 + 按值类型判断字段归属 + 示例。
# 各任务的 *_SYSTEM_PROMPT 只保留自己特有的目标与输出格式，运行时由 _system_with_role() 拼成
# 「角色定义 + 任务指令」，避免规则在多处重复、改一处即四处生效。
DEFAULT_LLM_ROLE = """你是一个严谨、专业的文档与表格数据助手。
你的专长是分析经过 OCR 处理的文本 / Markdown 内容，从中准确识别并抽取结构化的业务字段数据。

统一口径（以下规则适用于你承担的所有任务）：
1. 使用有意义的中文业务字段名（例如：合同编号、签订日期、甲方、金额），不要使用 "col1/col2" 这类通用名称。
2. 关键要求——字段的值必须严格按照源 OCR 文本中的写法照搬，不要重新格式化、归一化或"修正"：
   - 日期、数字、金额、编号等保持原文写法
     （例如写 "2024.1.5" 不要写 "2024-01-05"；写 "HT-2024-001" 不要写 "HT2024001"；写 "12,500.00" 不要写 "12500"）。
   - 中文大写数字保持原文（例如 "壹万圆整" 保持 "壹万圆整"）。
   - 仅当来源明确给出计算或合计时才计算/推导数值，否则保留原文照抄。
   - 注意：『保持原文写法』指保持源 OCR 中【真实】的写法，不包括 OCR 识别时【误插入】的无意义空格：
     例如 OCR 把 "HT-2024-001" 识别成 "HT - 2024 - 001"、把 "430523********4314" 识别成 "4305 23***** 4314"、
     把 "壹万圆整" 识别成 "一 万 圆 整"、把 "12,500.00" 识别成 "12, 500.00"，这些多余空格都【不是】真实写法，
     抽取时应直接去掉（连写为 HT-2024-001 / 430523********4314 / 壹万圆整 / 12,500.00）。
     即：凡是 OCR 在字母/数字/中文之间【无故插入】的空格都应去掉；只有原文【本来就有】的有意义空格（如英文单词间隔）才保留。
     同理，源文档常因排版把同一字段（尤其是【地址】）折成 2~3 行，那些【换行符只是排版折行、不是真实分隔】——
     抽取时应把折行的各部分【合并为同一行、去掉换行】，行尾/行间的多余空格一并去掉
     （如地址原文 "北京市海淀区\n中关村大街1号\nxx室" 应合并为 "北京市海淀区中关村大街1号xx室"），
     绝不要把换行符带进字段值。
     （系统也会对抽取结果做一道后处理：自动去掉换行与这类无意义空格，双保险。）
3. 【核心】提取每个值时，必须先判断它「是不是有效数据」，再决定写什么：
   - 区分两类内容：
     · 字段标签（不是数据）：字段名、表头、行标题、带冒号的行首，例如 "合同编号"、"甲方（盖章）："、"签订日期"、"金额（大写）"。它们是占位/说明，不是可填写的事实。
     · 字段值（是有效数据）：标签对应的一条具体业务事实，例如 "HT-2024-001"、"某某公司"、"2024.1.5"、"壹万圆整"。
   - 单元格【只能填"值"】，绝不可把标签本身、表头文字、或 "甲方：某某公司" 这种带标签前缀的整串当作值。
   - 若原文某字段【只有标签、没有对应数据】（例如 "甲方：" 后面空白，或某行只有标题），该单元格【留空 ""】，不要把标签再写回去。
   - 不要把纯说明/装饰性文字当作值，例如 "注：……"、"详见第X页"、"以下空白"、"（盖章处）"、"说明："。
   - 判断标准：问自己"这串文字是不是一个具体的、可填写的事实？"——是才写进值；若它只是字段名或说明，则不是有效数据，留空。
   - 字段值只承载「该字段自身属性」：绝不要把【不属于该字段属性】的内容塞进字段。具体：
     · 不要把说明、备注、与表格无关的文字写进字段值；
     · 不要把多个字段的内容拼接到同一个字段里（若原文把多项写在同处，应拆分为各自对应的字段，而非全部塞进某一个）；
     · 若某段文字明显属于另一个已有字段，归入那个字段，而不是放进当前字段；
     · 若某段文字无法归类到任何字段（如纯章节标题、与表格无关的正文），不要强行塞入字段，忽略即可。
4. 【核心·按值的类型与业务含义判断字段归属】不要只会套用示例里的固定字段；要能根据「值的类型与业务含义」自主推断它属于哪个字段：
   - 识别值的种类：看这串文字【本身长什么样、代表什么业务事实】，而不是死记示例中的字段。常见类型：
     · 日期类：含 年/月/日 或形如 2024.1.5 / 2024-01-05 / 2024年3月20日 / 二〇二四年 → 归入日期字段（签订日期 / 出生 / 日期 等）。
     · 编号 / 证件号类：字母+数字组合或长串数字，如 HT-2024-001、430523********4314、No.2024001 → 归入编号类字段（合同编号 / 证书编号 / 公民身份号码 等）。
     · 金额类：含 元/圆/万/¥/$ 或千分位/小数，如 12,500.00、壹万圆整、¥3,000 → 归入金额字段（金额 / 价款 / 金额（大写） 等）。
     · 名称类：具体人名或公司/组织名（张三、某某有限公司）→ 归入名称字段（姓名 / 甲方 / 乙方 等）。
     · 地址类：含 省/市/区/县/路/号/村/组 等 → 归入地址字段（住址 / 地址 等）。地址在源文档里常因排版折成 2~3 行、且 OCR/排版会在中间插入空格，抽取时务必【合并为一行、并去掉所有多余空格，写成连续字符串】——例如原文 "北京市东城区景山前街4号 紫禁城敬事房" 必须写成 "北京市东城区景山前街4号紫禁城敬事房"，【中文地址中不得保留任何空格】；仅当整段地址确为英文（如 "Room 502, No.5 Apple Street"）时才保留必要的词间隔空格。
     · 电话类：11 位手机号或带区号固话 → 归入电话字段（联系电话 / 手机 等）。
   - 当某段文字没有明确标签、或标签与示例不同（如合同里写「供方」而非「甲方」、写「买受人」而非「乙方」）时，依据【值的类型与上下文】把它归入语义最匹配的业务字段，并为该字段起一个合理的中文业务名。
   - 要点：字段识别靠「这个值是什么」，不是「示例里有没有」。任何新文档都要用这套通用方法推断字段，不要只会认示例中的那几种。
5. 不得编造、不得臆测：原文中没有的信息一律留空 ""，绝不推测填充。
6. 与用户交流时使用简体中文，条理清晰、简明扼要。

示例（输入 → 正确抽取结果，以下示例数据已脱敏）：
下面是一段清理后的 OCR 文本——注意它的标签与值【分行】、有的【连写无分隔符】、有的标签与值之间【夹着图片占位】：

姓名
张**（示例）
性别男
民族汉
出生19**年*月**日
住址
××省××县××镇××村××组（示例）
公民身份号码
（图片占位）
430523********4314

应抽取为：
{"姓名": "张**（示例）", "性别": "男", "民族": "汉", "出生": "19**年*月**日", "住址": "××省××县××镇××村××组（示例）", "公民身份号码": "430523********4314"}

该示例体现的要点（务必遵守）：
- 标签与值分行时，把上一行/上一字段名对应的下一行内容作为该字段的值（如 "姓名" 对应 "张**（示例）"）。
- 标签与值连写无分隔符时也要正确拆分："性别男" → 字段"性别"=值"男"；"民族汉" → "民族"="汉"；"出生19**年*月**日" → "出生"="19**年*月**日"。值里【不得】残留字段名。
- 标签与值之间夹着的图片占位（如（图片占位）、image、<!-- image -->）一律忽略，直接取其后的真实数据作为值（如 "公民身份号码" 对应 "430523********4314"）。
- 值只承载该字段自身属性，不要把住址、说明等无关内容塞进其它字段。
（该示例仅演示一种文档；遇到合同、发票、证书、报表等其它类型文档，请按上文『按值的类型判断字段归属』通用方法识别字段，不要只会套用示例字段。）

以上规则定义了你处理文档数据的【统一口径】。每次具体任务的目标、组织方式与输出格式，以随后给出的【任务指令】为准；当本次任务是普通对话问答时，按对话要求自然作答即可，无需输出 JSON。"""

# 历史遗留的一句话旧角色（早期版本的 DEFAULT_LLM_ROLE）。
# 旧版角色只描述身份、不含抽取口径；而现在各任务指令已精简为「目标+输出格式」，
# 若沿用旧角色会导致抽取规则整体丢失，故识别到旧值时自动回退到新的 DEFAULT_LLM_ROLE。
LEGACY_LLM_ROLE = (
    "你是一个严谨、专业的文档与表格数据助理。"
    "你擅长从 OCR 识别的文本中准确抽取结构化字段信息；回答用户问题时使用简体中文、"
    "条理清晰、简明扼要；在抽取或修正数据时严格照实、不编造、不臆测。"
)


def _is_legacy_role(role: str) -> bool:
    """判断设置中存的角色是否为历史遗留的一句话旧角色（需回退到新默认角色）。"""
    if not role:
        return True
    r = "".join(role.split())  # 忽略空白差异
    return r == "".join(LEGACY_LLM_ROLE.split())


# 重构前曾被「整段写入数据库」的旧 SYSTEM_PROMPT 识别标记：身份与任务指令片段混在一起，
# 并非用户自定义的纯口径。这类角色若被继续当作「自定义角色」使用，会与各任务指令里的
# 同名片段（如「下面会给你多份文档…」）重复。识别到即回退到新的 DEFAULT_LLM_ROLE（纯口径）。
_OLD_ROLE_MARKERS = ("下面会给你多份文档", "你是一个表格数据提取助手", "只输出【一张】表格")


def _is_old_full_prompt(role: str) -> bool:
    """判断设置中存的角色是否为『重构前被整段写入的旧的 SYSTEM_PROMPT』（含任务指令片段）。"""
    if not role:
        return False
    return any(m in role for m in _OLD_ROLE_MARKERS)


def resolve_llm_role(raw) -> str:
    """解析生效的「LLM 角色定义」：为空 / 历史遗留一句话旧角色 / 重构前被整段写入的旧
    SYSTEM_PROMPT（含任务指令片段）时，均回退到 DEFAULT_LLM_ROLE。

    供 chat.py / config.py 复用，避免多处重复同一套回退口径。
    """
    role = (raw or "").strip()
    if not role or _is_legacy_role(role) or _is_old_full_prompt(role):
        return DEFAULT_LLM_ROLE
    return role


# 字段值「空格 / 换行」处理的统一可执行条款。
# 它同时存在于：① 共享角色 DEFAULT_LLM_ROLE（规则 #2 例外条款 + 地址 bullet），保证所有任务（含对话）遵循；
# ② 下面的各任务指令，作为自包含的一条——因为落库 / 展示的「生成表格提示词」只含任务指令（不含角色），
# 若不在此写明，用户看到的表格生成 prompt 就会缺空格处理；且当用户自定义了不含该规则的纯角色时，任务指令仍能兜底。
_SPACE_HANDLING_RULE = (
    "【强制 · 空格与换行处理，违反即算错误】OCR 常在字母 / 数字 / 中文之间误插空格，"
    "或因排版把同一字段（尤其是地址）折成多行。你必须严格遵守："
    "① 一律去掉这些【误插的无意义空格】与【换行符】，把折行字段合并成一行；"
    "② 中文与中文、中文与数字 / 字母之间【绝不允许出现任何空格】（含全角空格 \\u3000）；"
    "③ 中文地址写成连续字符串、不得保留任何空格，例如："
    "\"4号 紫禁城敬事房\" → \"4号紫禁城敬事房\"、"
    "\"白 田村\" → \"白田村\"、"
    "\"北京市东城区景山前街4号 紫禁城敬事房\" → \"北京市东城区景山前街4号紫禁城敬事房\"；"
    "④ 千分位逗号两侧若是空格也一并去掉（\"12, 500.00\" → \"12,500.00\"）；"
    "⑤ 仅保留原文【本就有】的有意义空格（如纯英文 \"Room 502, No.5 Apple Street\" 的单词间隔）。"
    "输出前请逐字段自检：每个字段值里是否混入了不该有的空格 / 换行，有则去掉再输出。"
)

SYSTEM_PROMPT = (
    """【任务指令 · 单文件表格抽取】
分析下面这份经过 OCR 处理的 Markdown 内容，并将其中的结构化表格数据提取为 JSON 格式。

"""
    + _SPACE_HANDLING_RULE + "\n\n"
    + """1. 只提取表格数据，忽略非表格内容（如正文段落、说明、注记、页眉页脚）。
2. 每一行对应一个 JSON 对象，放入数组中。
3. 字段名与取值口径遵循上文【统一口径】。
4. 若未找到任何表格，返回空数组。
5. 只返回合法的 JSON，不要附带任何解释说明。

输出格式：
{
  "tables": [
    {
      "table_index": 0,
      "headers": ["字段1", "字段2", ...],
      "rows": [
        {"字段1": "原文值1", "字段2": "原文值2", ...},
        ...
      ]
    }
  ]
}"""
)

USER_PROMPT_TEMPLATE = """以下是 OCR 处理后的 Markdown 内容：

{ocr_md_content}

请将上述内容中的所有表格提取为结构化 JSON 格式。"""

BATCH_SYSTEM_PROMPT = (
    """【任务指令 · 批次汇总表】
下面会给你多份文档（它们的 OCR 文本）。你的任务是把【所有文档】整理成【一张】结构化表格。

"""
    + _SPACE_HANDLING_RULE + "\n\n"
    + """1. 只输出【一张】表格。
2. 每一行对应【一份】输入文档，且顺序与给出的顺序一致
   （DOCUMENT 1 → 第 1 行，DOCUMENT 2 → 第 2 行，……）。
3. 所有行使用【一致】的列名；选择能最好地概括各文档共有业务字段的列名。
   字段名与取值口径遵循上文【统一口径】。
4. 若某份文档缺少某个字段，该单元格留空（""），不得编造数据。
5. 只返回合法的 JSON，不要附带任何解释说明，格式如下：
{
  "tables": [
    {
      "title": "批次汇总",
      "headers": ["字段1", "字段2", ...],
      "rows": [ {"字段1": "原文值1", "字段2": "原文值2"}, ... ]
    }
  ]
}

（每份文档都按【统一口径】识别字段、各生成一行，再组合进同一张表。）"""
)

BATCH_USER_TEMPLATE = """下面是 {n} 份文档，每份以 "===== DOCUMENT {{i}} =====" 分隔。

{documents}

请将这 {n} 份文档整理成一张表格，每份文档一行，保持原有顺序。
若某份文档没有可提取的字段，仍要为它生成一行（含文件名），其余单元格留空。"""


REGEN_SYSTEM_PROMPT = (
    """【任务指令 · 按修正指令重新生成汇总表】
你会得到【当前的汇总表 JSON】和【各文件的原始 OCR 文本】。用户会给出一条修正指令
（例如：补全缺失字段、统一字段写法、修正某一列的不一致数据、按业务规则核对等）。

你的任务：依据指令，对照原始 OCR 文本重新生成【汇总表 JSON】，尽量补全缺失、修正差异。

"""
    + _SPACE_HANDLING_RULE + "\n\n"
    + """1. 只输出【一张】表，每行对应一个文件，且文件顺序与输入 file_order 保持一致。
2. 对照原始 OCR 补全缺失字段、修正明显错误 / 不一致：
   - 同一字段在不同文件写法不一（如 "甲方" 有的写全称有的写简称），按指令或最完整的原文统一；
   - 日期 / 金额 / 编号格式异常或被截断，依据 OCR 原文修正，不要臆造；
   - 缺失的单元格，若 OCR 中确有该信息则补全，否则留空 ""。
3. 字段名与取值口径遵循上文【统一口径】（严格照抄 OCR 原文写法、值里不写字段名、不编造）。
4. 只返回合法 JSON，不要附带任何解释说明，格式如下：
{
  "tables": [
    {
      "title": "批次汇总",
      "headers": ["字段1", "字段2", ...],
      "rows": [ {"字段1": "原文值1", "字段2": "原文值2"}, ... ]
    }
  ]
}"""
)


# ---- 汇总表文档块构建 / 失败返回 / 落库 等共用辅助（消除 batches.py / task_poller 重复）----

def _build_doc_blocks(files: list) -> tuple:
    """把文件列表整理成注入 LLM 的 DOCUMENT 文档块（清理后 OCR + 文件名标记），
    同时返回与输入顺序一致的 file_order（文件 id 列表）。
    """
    docs, file_order = [], []
    for i, f in enumerate(files, 1):
        content = (f.get("ocr_md_content") or "").strip()
        if not content or f.get("ocr_status") != "completed":
            content = f"[OCR 未完成或失败：{f.get('original_filename')}]"
        else:
            # 过滤空行与 Markdown 格式标记，降低提示词噪声与 token 占用
            content = _clean_ocr_md(content)
        docs.append(
            f"===== DOCUMENT {i} (文件名: {f.get('original_filename')}) =====\n{content}"
        )
        file_order.append(f.get("id"))
    return docs, file_order


def _fail(error: str, prompt: str, raw_reply, file_order: list) -> dict:
    """构造统一的失败返回字典（替代散落在 format_batch_table / regenerate_batch_table 的 8 处重复）。"""
    return {
        "success": False,
        "error": error,
        "prompt": prompt,
        "raw_reply": raw_reply,
        "file_order": file_order,
    }


async def persist_batch_table(batch_repo, batch_id: str, result: dict) -> dict:
    """把 LLM 汇总表结果统一落库（消除 batches.py / task_poller 三处重复的成功/跳过/失败分支）。

    返回 {"skipped": bool, "success": bool}，供调用方决定响应 / 日志。
    """
    if result.get("skipped"):
        await batch_repo.update_batch_table(batch_id, None)
        return {"skipped": True, "success": False}
    if result.get("success"):
        await batch_repo.update_batch_table(
            batch_id,
            json.dumps(result["result"], ensure_ascii=False),
            prompt=result.get("prompt"),
            reply=result.get("raw_reply"),
        )
        return {"skipped": False, "success": True}
    await batch_repo.update_batch_table(
        batch_id,
        json.dumps(
            {"error": result.get("error", "汇总表生成失败")}, ensure_ascii=False
        ),
        prompt=result.get("prompt"),
        reply=result.get("raw_reply"),
    )
    return {"skipped": False, "success": False}


class LLMService:
    def __init__(self, setting_repo: SettingRepo):
        self.setting_repo = setting_repo

    async def _system_with_role(self, base_prompt: str) -> str:
        """把「LLM 角色定义」前置到任务指令，组成完整的系统提示词。

        角色定义即【公共抽取口径】，base_prompt 为各任务特有的目标与输出格式。
        读取设置中的 llm_role；为空（未设置）或仍是历史遗留的一句话旧角色时，
        回退到 DEFAULT_LLM_ROLE —— 否则精简后的任务指令会因缺少公共口径而丢失抽取规则。
        """
        role = (await self.setting_repo.get("llm_role") or "").strip()
        if not role or _is_legacy_role(role) or _is_old_full_prompt(role):
            role = DEFAULT_LLM_ROLE
        return f"{role}\n\n{base_prompt}"

    async def _get_credentials(self, model_override=None, base_url_override=None, api_key_override=None):
        """解析当前生效的 key/base_url/model，支持调用方传入覆盖（用于『先测后存』）。"""
        api_key = api_key_override or (await self.setting_repo.get("llm_api_key")) or ""
        if not api_key:
            # Fall back to env variable
            from app.config import settings
            api_key = settings.llm_api_key
        base_url = base_url_override or (await self.setting_repo.get("llm_base_url")) or "https://api.openai.com/v1"
        model = model_override or (await self.setting_repo.get("llm_model")) or "gpt-4o-mini"
        return api_key, base_url, model

    def _build_client(self, api_key: str, base_url: str):
        return AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def _stream_chat(self, client, model, messages, timeout=60, response_format=None):
        """统一用流式调用。

        部分 OpenAI 兼容端点（如某些本地/私有化部署）即便未请求流式也会强制
        以 SSE(text/event-stream) 返回，标准 client 在非流式模式下会把响应体
        作为原始字符串返回，导致 response.choices 报
        "'str' object has no attribute 'choices'"。

        强制 stream=True 可让 SDK 正确解析 SSE 分块，再拼接 delta.content。
        这对普通非流式端点同样兼容。
        """
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "timeout": timeout,
            "stream": True,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        stream = await client.chat.completions.create(**kwargs)
        content = ""
        async for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                content += piece
        return content

    async def _chat_json(self, client, model, messages, timeout=60):
        """容错调用 LLM 取 JSON 文本。

        部分私有/本地 OpenAI 兼容端点（如自建 vLLM、部分国产模型网关）不支持
        response_format={"type":"json_object"}，直接传该参数会让调用报错/返回空，
        导致「接受 LLM 返回数据失败」。
        这里先尝试 json_object 模式；若抛异常则自动降级为普通模式（只靠 prompt
        约束 + _extract_json 解析），最大化对各类端点的兼容性。
        返回 (content, error)：error 为 None 表示已拿到响应（content 可能为空，由调用方判断）。
        """
        last_err = None
        for rf in ({"type": "json_object"}, None):
            try:
                content = await self._stream_chat(
                    client, model, messages=messages, timeout=timeout, response_format=rf
                )
                return content, None
            except Exception as e:
                last_err = str(e)
        return None, last_err

    @staticmethod
    def _extract_json(text):
        """从 LLM 返回文本中提取 JSON，容错策略（依次尝试）：

        1. 直接 json.loads（模型已返回纯净 JSON）；
        2. 剥离 markdown 代码围栏 ```json ... ``` / ``` ... ```（围栏可在文本任意位置）
           —— 用非贪婪匹配只取围栏内内容，避免尾注里的花括号污染；
        3. 在围栏内容 / 全文里截取第一个 `{`→最后一个 `}`（或 `[`→`]`）；
        4. 对截取片段做常见瑕疵修复（尾随逗号、`//` 行注释、`/* */` 块注释）后再次解析。
        """
        text = (text or "").strip()

        def _try_parse(s):
            s = s.strip()
            if not s:
                return None
            try:
                return json.loads(s)
            except Exception:
                pass
            try:
                return json.loads(_clean_json_text(s))
            except Exception:
                return None

        # 1) 直接解析
        r = _try_parse(text)
        if r is not None:
            return r

        # 2) 剥离 markdown 围栏（语言名可有可无；内容任意字符，非贪婪）
        m = re.search(r"```[ \t]*[a-zA-Z]*[ \t]*\n?(.*?)\n?[ \t]*```", text, re.DOTALL)
        if m:
            fenced = m.group(1).strip()
            r = _try_parse(fenced)
            if r is not None:
                return r

        # 3) 兜底：截取第一个 { 到最后一个 }（优先对象）；否则 [ 到 ]
        for open_c, close_c in (("{", "}"), ("[", "]")):
            start = text.find(open_c)
            end = text.rfind(close_c)
            if start != -1 and end != -1 and end > start:
                frag = text[start : end + 1]
                r = _try_parse(frag)
                if r is not None:
                    return r

        raise ValueError("LLM 返回内容中未找到合法 JSON")

    async def extract_tables(self, ocr_md_content: str, model_override: str = None) -> dict:
        if not ocr_md_content or not ocr_md_content.strip():
            return {"success": True, "skipped": True, "result": {"tables": []}}

        # Format arbitrary OCR content into a structured table (no markdown-table gate).
        api_key, base_url, model = await self._get_credentials(model_override)
        if not api_key or api_key == "your-api-key-here":
            return {"success": False, "error": "LLM API key not configured"}

        client = self._build_client(api_key, base_url)

        system_content = await self._system_with_role(SYSTEM_PROMPT)
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
                ocr_md_content=_clean_ocr_md(ocr_md_content)
            )},
        ]
        content, llm_err = await self._chat_json(client, model, messages=messages, timeout=60)
        if llm_err:
            return {"success": False, "error": f"LLM call failed: {llm_err}"}
        if not content:
            return {"success": False, "error": "Empty LLM response"}

        try:
            result = self._extract_json(content)
            result = _normalize_result(result)  # 兜底：去标签前缀 + 去 OCR 无意义空格
            return {
                "success": True,
                "skipped": False,
                "result": result,
                "model": model,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"LLM 返回无法解析为 JSON：{str(e)}",
                "raw_reply": content,
            }

    async def chat(self, messages: list[dict], model_override: str = None, timeout: int = 90) -> str:
        """多轮对话：messages 为 [{role, content}] 列表（含 system/user/assistant）。

        复用统一流式调用；返回拼接后的助手回复文本。
        """
        api_key, base_url, model = await self._get_credentials(model_override)
        if not api_key or api_key == "your-api-key-here":
            raise ValueError("LLM API key 未配置")
        client = self._build_client(api_key, base_url)
        return await self._stream_chat(client, model, messages=messages, timeout=timeout)

    async def list_models(self, base_url_override=None, api_key_override=None) -> list[str]:
        """调用 OpenAI 兼容 /models 端点，返回模型 id 列表（升序）。"""
        api_key, base_url, _ = await self._get_credentials(
            base_url_override=base_url_override, api_key_override=api_key_override
        )
        if not api_key or api_key == "your-api-key-here":
            raise ValueError("LLM API key 未配置，无法获取模型列表")
        client = self._build_client(api_key, base_url)
        try:
            resp = await client.models.list()
            ids = [m.id for m in resp.data]
            return sorted(ids)
        except Exception as e:
            raise RuntimeError(f"获取模型列表失败：{e}")

    async def test_connection(self, model_override=None, base_url_override=None, api_key_override=None) -> dict:
        """发一个最小 chat 请求验证 key / base_url / model 是否可用。"""
        api_key, base_url, model = await self._get_credentials(
            model_override, base_url_override, api_key_override
        )
        if not api_key or api_key == "your-api-key-here":
            return {"ok": False, "error": "LLM API key 未配置"}
        client = self._build_client(api_key, base_url)
        import time
        start = time.monotonic()
        try:
            sample = await self._stream_chat(
                client,
                model,
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
                timeout=30,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            sample = (sample or "").strip()
            return {"ok": True, "model": model, "latency_ms": latency_ms, "sample": sample}
        except Exception as e:
            return {"ok": False, "error": f"LLM 连接测试失败：{e}"}

    async def format_batch_table(self, files: list[dict]) -> dict:
        """把所有文件的 OCR 内容整理成一张汇总表：每行对应一个文件。

        返回 {"success", "result": {"tables":[...], "file_order":[...]}, "model"}。
        file_order 与输入顺序一致，便于前端按 file_id 定位行。
        """
        if not files:
            return {"success": True, "skipped": True, "result": {"tables": []}, "file_order": []}

        docs, file_order = _build_doc_blocks(files)

        user_prompt = BATCH_USER_TEMPLATE.format(
            n=len(files), documents="\n\n".join(docs)
        )
        # 实际发给 LLM 的 system（含公共角色定义 role）；落库/展示的「发起的提示词」只保留
        # 本次任务指令（BATCH_SYSTEM_PROMPT），避免把冗长的共享角色定义（DEFAULT_LLM_ROLE）
        # 重复塞进会话生成记录与展示——role 已在会话 system 头部统一注入，无需再重复呈现。
        system_prompt = await self._system_with_role(BATCH_SYSTEM_PROMPT)
        prompt_text = f"[SYSTEM]\n{BATCH_SYSTEM_PROMPT}\n\n[USER]\n{user_prompt}"

        api_key, base_url, model = await self._get_credentials()
        if not api_key or api_key == "your-api-key-here":
            return _fail("LLM API key not configured", prompt_text, None, file_order)

        client = self._build_client(api_key, base_url)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        content, llm_err = await self._chat_json(client, model, messages=messages, timeout=120)
        raw_reply = content  # 记录「回复」的原始响应（未解析 JSON 前）
        if llm_err:
            return _fail(f"LLM call failed: {llm_err}", prompt_text, None, file_order)
        if not content:
            return _fail("Empty LLM response", prompt_text, raw_reply, file_order)
        try:
            result = self._extract_json(content)
            result = _normalize_result(result)  # 兜底：去标签前缀 + 去 OCR 无意义空格
            result["file_order"] = file_order
            return {
                "success": True,
                "skipped": False,
                "result": result,
                "model": model,
                "prompt": prompt_text,
                "raw_reply": raw_reply,
                "file_order": file_order,
            }
        except Exception as e:
            return _fail(f"LLM 返回无法解析为 JSON：{str(e)}", prompt_text, content, file_order)

    async def regenerate_batch_table(
        self,
        existing_table: dict,
        files: list[dict],
        instruction: str,
        model_override: str = None,
    ) -> dict:
        """根据用户的修正指令 + 原始 OCR，重新生成批次汇总表。

        与 format_batch_table 的区别：已有汇总表也作为输入上下文之一，让 LLM 对照
        原始 OCR 补全缺失字段、修正数据差异 / 不一致，而不是从零提取。
        返回 {"success", "result": {"tables":[...], "file_order":[...]}, "model", "prompt", "raw_reply"}。
        """
        if not isinstance(existing_table, dict):
            return {
                "success": False,
                "error": "现有汇总表为空，无法据此重新生成",
                "file_order": [],
            }
        tables = existing_table.get("tables") or []
        if not tables:
            return {
                "success": False,
                "error": "现有汇总表无数据行，无法据此重新生成",
                "file_order": [],
            }
        file_order = existing_table.get("file_order") or []

        # 原始 OCR 文档（清理后），与 format_batch_table 同格式
        docs, _ = _build_doc_blocks(files)

        existing_json = json.dumps(existing_table, ensure_ascii=False)
        user_prompt = (
            "下面是【当前的汇总表 JSON】（每行 = 一个文件，file_order 为该批次文件顺序）：\n\n"
            f"{existing_json}\n\n"
            "下面是【各文件的原始 OCR 文本】，用于核对 / 补全：\n\n"
            f"{chr(10).join(docs)}\n\n"
            f"用户指令：{instruction}\n\n"
            "请依据上述指令，对照原始 OCR 重新生成【汇总表 JSON】。要求：\n"
            "① 仍只输出【一张】表，每行对应一个文件，文件顺序与上面 file_order 一致；\n"
            "② 对照 OCR 补全缺失字段、修正明显错误 / 不一致（例如同一字段在不同文件写法不一、日期或金额格式异常）；\n"
            "③ 单元格值严格照抄 OCR 原文写法（含中文大写数字、原编号 / 日期格式），不要把字段名写进值，不要编造；\n"
            "④ 字段名使用中文业务名称，所有行列名一致；\n"
            "⑤ 只返回合法 JSON，不要附带解释说明。"
        )
        # 同上：落库/展示的「发起的提示词」只保留任务指令（REGEN_SYSTEM_PROMPT），不含共享角色定义
        system_prompt = await self._system_with_role(REGEN_SYSTEM_PROMPT)
        prompt_text = f"[SYSTEM]\n{REGEN_SYSTEM_PROMPT}\n\n[USER]\n{user_prompt}"

        api_key, base_url, model = await self._get_credentials(model_override)
        if not api_key or api_key == "your-api-key-here":
            return _fail("LLM API key not configured", prompt_text, None, file_order)

        client = self._build_client(api_key, base_url)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        content, llm_err = await self._chat_json(client, model, messages=messages, timeout=120)
        raw_reply = content
        if llm_err:
            return _fail(f"LLM call failed: {llm_err}", prompt_text, None, file_order)
        if not content:
            return _fail("Empty LLM response", prompt_text, raw_reply, file_order)
        try:
            result = self._extract_json(content)
            result = _normalize_result(result)  # 兜底：去标签前缀 + 去 OCR 无意义空格
            # 保住 file_order 映射（行 -> 文件），避免重新生成后行与文件错乱
            if not result.get("file_order") and file_order:
                result["file_order"] = file_order
            return {
                "success": True,
                "skipped": False,
                "result": result,
                "model": model,
                "prompt": prompt_text,
                "raw_reply": raw_reply,
                "file_order": result.get("file_order", file_order),
            }
        except Exception as e:
            return _fail(f"LLM 返回无法解析为 JSON：{str(e)}", prompt_text, content, file_order)
