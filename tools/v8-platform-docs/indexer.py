"""
Скрипт индексации документации платформы 1С:Предприятие из файлов HBK.
Распаковывает статьи из shcntx_ru.hbk, shquery_ru.hbk, shlang_ru.hbk, mngdsgn_ru.hbk
и сохраняет их в базу SQLite с поддержкой полнотекстового поиска FTS5.
"""

import sys
import os
import struct
import io
import zipfile
import re
import html
import sqlite3
import time

def read_v8_document(f, start_offset: int) -> bytes:
    """Читает составной документ из контейнера V8 по цепочке блоков."""
    curr = start_offset
    buf = bytearray()
    first = True
    total_len = 0
    while curr != 0x7fffffff:
        f.seek(curr)
        hdr1 = f.read(2)  # \r\n
        hdr2 = f.readline()
        parts = hdr2.strip().split()
        if len(parts) < 3:
            break
        d_len = int(parts[0], 16)
        p_len = int(parts[1], 16)
        next_p = int(parts[2], 16)
        if first:
            total_len = d_len
            first = False
        chunk = f.read(p_len)
        buf.extend(chunk)
        curr = next_p
    return bytes(buf[:total_len])

def extract_zip_from_hbk(hbk_path: str) -> zipfile.ZipFile | None:
    """Извлекает внутренний ZIP-архив FileStorage из файла .hbk."""
    if not os.path.exists(hbk_path):
        return None
    with open(hbk_path, 'rb') as f:
        toc = read_v8_document(f, 16)
        num = len(toc) // 12
        for i in range(num):
            h_off, b_off, _ = struct.unpack('<3I', toc[i*12:(i+1)*12])
            if b_off == 0x7fffffff:
                continue
            hdr_doc = read_v8_document(f, h_off)
            name = hdr_doc[20:].decode('utf-16le', errors='ignore').rstrip('\x00')
            if name == 'FileStorage':
                body = read_v8_document(f, b_off)
                return zipfile.ZipFile(io.BytesIO(body))
    return None

def parse_html_article(html_text: str, file_path: str, book: str) -> dict | None:
    """Парсит HTML-статью документации 1С и извлекает метаданные и чистый текст."""
    if not html_text or '<html' not in html_text.lower():
        return None

    # Извлечение заголовка pagetitle
    pagetitle_m = re.search(r'(?i)<h1[^>]*class=["\']?V8SH_pagetitle["\']?[^>]*>(.*?)</h1>', html_text)
    if not pagetitle_m:
        h1_m = re.search(r'(?i)<h1[^>]*>(.*?)</h1>', html_text)
        title_raw = h1_m.group(1) if h1_m else ""
    else:
        title_raw = pagetitle_m.group(1)

    title = html.unescape(re.sub(r'<[^>]+>', '', title_raw)).strip()
    if not title:
        title = os.path.splitext(os.path.basename(file_path))[0]

    # Объект (V8SH_title)
    obj_m = re.search(r'(?i)<p[^>]*class=["\']?V8SH_title["\']?[^>]*>(.*?)</p>', html_text)
    obj_raw = html.unescape(re.sub(r'<[^>]+>', '', obj_m.group(1))).strip() if obj_m else ""

    # Подзаголовок / действие (V8SH_heading)
    heading_m = re.search(r'(?i)<p[^>]*class=["\']?V8SH_heading["\']?[^>]*>(.*?)</p>', html_text)
    heading_raw = html.unescape(re.sub(r'<[^>]+>', '', heading_m.group(1))).strip() if heading_m else ""

    # Версия
    ver_m = re.search(r'(?i)<p[^>]*class=["\']?V8SH_versionInfo["\']?[^>]*>(.*?)</p>', html_text)
    if not ver_m:
        ver_m = re.search(r'(?i)<p[^>]*class=["\']?not_used["\']?[^>]*>(.*?)</p>', html_text)
    version_str = html.unescape(re.sub(r'<[^>]+>', '', ver_m.group(1))).strip() if ver_m else ""

    # Доступность (контекст выполнения)
    ctx_m = re.search(r'(?i)Доступность:?\s*</p>\s*<p>(.*?)</p>', html_text)
    context_str = html.unescape(re.sub(r'<[^>]+>', '', ctx_m.group(1))).strip() if ctx_m else ""

    # Синтаксис
    syntax_matches = re.findall(r'(?i)<p[^>]*class=["\']?V8SH_chapter["\']?[^>]*>Синтаксис:?</p>\s*(.*?)(?=<p[^>]*class=["\']?V8SH_chapter|$)', html_text, re.DOTALL)
    syntax_list = []
    for sm in syntax_matches:
        clean_s = html.unescape(re.sub(r'<[^>]+>', '', sm)).strip()
        if clean_s:
            syntax_list.append(clean_s)
    syntax_str = "\n".join(syntax_list)

    # Тип элемента
    item_type = "other"
    if "/methods/" in file_path:
        item_type = "method"
    elif "/properties/" in file_path:
        item_type = "property"
    elif "/constructors/" in file_path:
        item_type = "constructor"
    elif "/events/" in file_path:
        item_type = "event"
    elif book == "shquery":
        item_type = "query"
    elif book == "shlang":
        item_type = "language"
    elif obj_raw and not heading_raw:
        item_type = "type"

    # Разбор имен RU / EN
    # Обычно формат: "ИмяМетода (MethodName)" или "ТипОбъекта.ИмяМетода (ObjectType.MethodName)"
    name_ru, name_en = "", ""
    parent_ru, parent_en = "", ""

    target_name = heading_raw if heading_raw else title
    name_match = re.match(r'^(.*?)\s*\((.*?)\)$', target_name)
    if name_match:
        name_ru = name_match.group(1).strip()
        name_en = name_match.group(2).strip()
    else:
        name_ru = target_name

    if obj_raw:
        obj_match = re.match(r'^(.*?)\s*\((.*?)\)$', obj_raw)
        if obj_match:
            parent_ru = obj_match.group(1).strip()
            parent_en = obj_match.group(2).strip()
        else:
            parent_ru = obj_raw

    # Конвертация статьи в аккуратный Markdown
    md_content = html_to_markdown(html_text)

    return {
        "book": book,
        "path": file_path,
        "title": title,
        "name_ru": name_ru,
        "name_en": name_en,
        "parent_ru": parent_ru,
        "parent_en": parent_en,
        "item_type": item_type,
        "syntax": syntax_str,
        "context": context_str,
        "version_since": version_str,
        "description": md_content
    }

def html_to_markdown(html_text: str) -> str:
    """Преобразует HTML-документ справки 1С в структурированный Markdown."""
    text = re.sub(r'(?is)<head.*?>.*?</head>', '', html_text)
    text = re.sub(r'(?is)<style.*?>.*?</style>', '', text)
    text = re.sub(r'(?is)<script.*?>.*?</script>', '', text)

    text = re.sub(r'(?i)<h1[^>]*>(.*?)</h1>', r'\n# \1\n', text)
    text = re.sub(r'(?i)<p class=["\']?V8SH_title["\']?[^>]*>(.*?)</p>', r'\n**Объект:** \1\n', text)
    text = re.sub(r'(?i)<p class=["\']?V8SH_heading["\']?[^>]*>(.*?)</p>', r'\n## \1\n', text)
    text = re.sub(r'(?i)<p class=["\']?V8SH_chapter["\']?[^>]*>(.*?)</p>', r'\n### \1\n', text)

    text = re.sub(r'(?i)<div class=["\']?V8SH_rubric["\']?[^>]*>', r'\n- **Параметр:** ', text)
    text = re.sub(r'(?i)<p class=["\']?V8SH_versionInfo["\']?[^>]*>(.*?)</p>', r'\n*Версия:* \1\n', text)
    text = re.sub(r'(?i)<p class=["\']?not_used["\']?[^>]*>(.*?)</p>', r'\n*\1*\n', text)

    text = re.sub(r'(?i)<br\s*/?>', '\n', text)
    text = re.sub(r'(?i)</p>', '\n', text)
    text = re.sub(r'(?i)</div>', '\n', text)
    text = re.sub(r'(?i)</li>', '\n', text)
    text = re.sub(r'(?i)<li[^>]*>', '- ', text)
    text = re.sub(r'(?i)<hr[^>]*>', '\n---\n', text)

    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)

    # Удаляем BOM и служебную ссылку "Методическая информация" в конце
    text = text.lstrip('\ufeff').strip()
    text = re.sub(r'Методическая информация\s*$', '', text).strip()
    # Сжатие множественных переводов строк
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def build_database(bin_dir: str, db_path: str):
    """Индексирует книги справки и сохраняет в SQLite базу."""
    books = [
        ("shcntx", "shcntx_ru.hbk"),
        ("shquery", "shquery_ru.hbk"),
        ("shlang", "shlang_ru.hbk"),
        ("mngdsgn", "mngdsgn_ru.hbk"),
    ]

    print(f"Создание базы данных: {db_path}")
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        book TEXT,
        path TEXT,
        title TEXT,
        name_ru TEXT,
        name_en TEXT,
        parent_ru TEXT,
        parent_en TEXT,
        item_type TEXT,
        syntax TEXT,
        context TEXT,
        version_since TEXT,
        description TEXT
    );
    """)

    cur.execute("""
    CREATE INDEX idx_name_ru ON articles(name_ru);
    """)
    cur.execute("""
    CREATE INDEX idx_name_en ON articles(name_en);
    """)
    cur.execute("""
    CREATE INDEX idx_parent_ru ON articles(parent_ru);
    """)
    cur.execute("""
    CREATE INDEX idx_parent_en ON articles(parent_en);
    """)
    cur.execute("""
    CREATE INDEX idx_item_type ON articles(item_type);
    """)

    # FTS5 полнотекстовый поиск
    cur.execute("""
    CREATE VIRTUAL TABLE articles_fts USING fts5(
        title,
        name_ru,
        name_en,
        parent_ru,
        parent_en,
        syntax,
        description,
        content='articles',
        content_rowid='id',
        tokenize='unicode61'
    );
    """)

    cur.execute("""
    CREATE TRIGGER articles_ai AFTER INSERT ON articles BEGIN
        INSERT INTO articles_fts(rowid, title, name_ru, name_en, parent_ru, parent_en, syntax, description)
        VALUES (new.id, new.title, new.name_ru, new.name_en, new.parent_ru, new.parent_en, new.syntax, new.description);
    END;
    """)

    total_articles = 0
    t0 = time.time()

    for book_id, hbk_name in books:
        full_path = os.path.join(bin_dir, hbk_name)
        if not os.path.exists(full_path):
            print(f"Пропуск (файл не найден): {full_path}")
            continue

        print(f"Обработка книги '{book_id}' ({hbk_name})...")
        t_book = time.time()
        zf = extract_zip_from_hbk(full_path)
        if not zf:
            print(f"Не удалось извлечь ZIP из {hbk_name}")
            continue

        # Обрабатываем все файлы, которые не являются графикой, стилями или шаблонами
        file_list = [fn for fn in zf.namelist() if not fn.lower().endswith(('.png', '.jpg', '.gif', '.st', '.bmp', '.ico', '.css', '.js'))]
        count_book = 0

        batch = []
        for fn in file_list:
            try:
                raw_bytes = zf.read(fn)
                raw_html = raw_bytes.decode('utf-8', errors='ignore')
                if '<html' not in raw_html.lower():
                    continue
                art = parse_html_article(raw_html, fn, book_id)
                if not art:
                    continue

                batch.append((
                    art["book"],
                    art["path"],
                    art["title"],
                    art["name_ru"],
                    art["name_en"],
                    art["parent_ru"],
                    art["parent_en"],
                    art["item_type"],
                    art["syntax"],
                    art["context"],
                    art["version_since"],
                    art["description"]
                ))
                count_book += 1

                if len(batch) >= 1000:
                    cur.executemany("""
                    INSERT INTO articles (book, path, title, name_ru, name_en, parent_ru, parent_en, item_type, syntax, context, version_since, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch)
                    batch = []
            except Exception as e:
                pass

        if batch:
            cur.executemany("""
            INSERT INTO articles (book, path, title, name_ru, name_en, parent_ru, parent_en, item_type, syntax, context, version_since, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)

        conn.commit()
        total_articles += count_book
        print(f"  -> Сохранено {count_book} статей за {time.time() - t_book:.1f} сек.")

    # Оптимизация индекса FTS
    print("Оптимизация FTS5 индекса...")
    cur.execute("INSERT INTO articles_fts(articles_fts) VALUES('optimize');")
    conn.commit()
    conn.close()

    db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    print(f"\nИндексация успешно завершена за {time.time() - t0:.1f} сек!")
    print(f"Всего статей в базе: {total_articles}")
    print(f"Размер базы данных: {db_size_mb:.2f} МБ")

if __name__ == "__main__":
    default_bin = r"C:\Program Files\1cv8\8.5.4.1878\bin"
    target_bin = sys.argv[1] if len(sys.argv) > 1 else default_bin
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_db = os.path.join(script_dir, "v8_platform_docs.db")

    build_database(target_bin, target_db)
