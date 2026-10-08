"""
MCP-сервер документации платформы 1С:Предприятие (Синтакс-Помощник).
Работает по протоколу MCP (stdio) и предоставляет доступ к полной официальной документации
установленной платформы 1С:Предприятие (версия 8.5.4 / 8.3).
"""

import os
import sys
import sqlite3
import re
from typing import Optional
from mcp.server.mcpserver import MCPServer

# Путь к локальной базе SQLite
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v8_platform_docs.db")

server = MCPServer("v8-platform-docs")

def get_db_connection():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"База данных документации 1С не найдена по пути: {DB_PATH}. "
            f"Запустите indexer.py для генерации базы."
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def sanitize_fts_query(query: str) -> str:
    """Очищает строку запроса для безопасного использования в SQLite FTS5 MATCH."""
    # Удаляем служебные операторы FTS кроме букв, цифр и подчеркивания
    cleaned = re.sub(r'[^\w\sа-яА-ЯёЁ]', ' ', query)
    tokens = cleaned.strip().split()
    if not tokens:
        return ""
    # Ищем слова с префиксным совпадением (token*)
    return " ".join(f'"{t}"*' for t in tokens)

@server.tool()
def search_syntax(query: str, category: Optional[str] = None, limit: int = 10) -> str:
    """
    Полнотекстовый поиск по Синтакс-Помощнику 1С:Предприятие.
    
    Параметры:
      query: Поисковый запрос (например: "HTTPСоединение", "НайтиФайлы", "КОНЕЦПЕРИОДА", "ПрочитатьJSON").
      category: Опциональный фильтр по типу ('method', 'property', 'constructor', 'type', 'event', 'query', 'language').
      limit: Максимальное количество результатов (по умолчанию 10).
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # Сначала пробуем точное совпадение по имени объекта или метода
    exact_params = [query.strip(), query.strip(), query.strip()]
    type_filter_clause = "AND a.item_type = ?" if category else ""
    if category:
        exact_params.append(category)

    cur.execute(f"""
    SELECT a.id, a.book, a.title, a.item_type, a.parent_ru, a.parent_en, a.name_ru, a.name_en, a.syntax, a.context, a.version_since
    FROM articles a
    WHERE (a.name_ru = ? COLLATE NOCASE OR a.name_en = ? COLLATE NOCASE OR a.title LIKE ? || '%')
    {type_filter_clause}
    LIMIT {limit}
    """, exact_params)
    exact_rows = cur.fetchall()

    rows = list(exact_rows)
    seen_ids = {r["id"] for r in rows}

    # Если точных совпадений меньше limit, дополняем FTS5-поиском
    if len(rows) < limit:
        fts_query = sanitize_fts_query(query)
        if fts_query:
            fts_params = [fts_query]
            if category:
                fts_params.append(category)
            cur.execute(f"""
            SELECT a.id, a.book, a.title, a.item_type, a.parent_ru, a.parent_en, a.name_ru, a.name_en, a.syntax, a.context, a.version_since
            FROM articles_fts f
            JOIN articles a ON a.id = f.rowid
            WHERE articles_fts MATCH ?
            {type_filter_clause}
            ORDER BY rank
            LIMIT {limit * 2}
            """, fts_params)
            for r in cur.fetchall():
                if r["id"] not in seen_ids:
                    rows.append(r)
                    seen_ids.add(r["id"])
                    if len(rows) >= limit:
                        break

    conn.close()

    if not rows:
        return f"По запросу '{query}' ничего не найдено в документации платформы 1С."

    lines = [f"### Результаты поиска по запросу `{query}` (найдено {len(rows)}):", ""]
    for r in rows:
        kind = f"[{r['item_type']}]" if r["item_type"] else ""
        parent = f"`{r['parent_ru']}` -> " if r["parent_ru"] else ""
        lines.append(f"#### {kind} {parent}**{r['title']}** (ID: `{r['id']}`)")
        if r["syntax"]:
            lines.append("```bsl")
            lines.append(r["syntax"])
            lines.append("```")
        info_parts = []
        if r["context"]:
            info_parts.append(f"**Доступность:** {r['context']}")
        if r["version_since"]:
            info_parts.append(f"**Версия:** {r['version_since']}")
        if info_parts:
            lines.append(" • ".join(info_parts))
        lines.append("")

    lines.append("---")
    lines.append("*Для детального просмотра статьи используйте `get_article(id)`.*")
    return "\n".join(lines)

@server.tool()
def get_article(article_id: int) -> str:
    """
    Получить полный текст статьи документации по ее ID.
    
    Параметры:
      article_id: Числовой идентификатор статьи (из результатов поиска `search_syntax`).
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return f"Статья с ID `{article_id}` не найдена."

    return row["description"].lstrip('\ufeff').strip()

@server.tool()
def get_type_info(type_name: str) -> str:
    """
    Получить сводную карточку типа платформы 1С (список методов, свойств, конструкторов).
    
    Параметры:
      type_name: Имя типа (например: "HTTPСоединение", "ТаблицаЗначений", "Запрос", "Массив").
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # Ищем саму статью о типе
    cur.execute("""
    SELECT * FROM articles
    WHERE (name_ru = ? COLLATE NOCASE OR name_en = ? COLLATE NOCASE)
      AND (parent_ru IS NULL OR parent_ru = '' OR item_type = 'type')
    ORDER BY id
    LIMIT 1
    """, (type_name.strip(), type_name.strip()))
    type_row = cur.fetchone()

    # Ищем методы и свойства типа
    cur.execute("""
    SELECT name_ru, name_en, item_type, syntax, context, version_since
    FROM articles
    WHERE (parent_ru = ? COLLATE NOCASE OR parent_en = ? COLLATE NOCASE)
    ORDER BY item_type, name_ru
    """, (type_name.strip(), type_name.strip()))
    members = cur.fetchall()
    conn.close()

    if not type_row and not members:
        return f"Тип `{type_name}` не найден в документации платформы 1С."

    lines = [f"# Тип платформы: {type_row['title'] if type_row else type_name}", ""]
    if type_row:
        if type_row["version_since"]:
            lines.append(f"*{type_row['version_since']}*")
        if type_row["context"]:
            lines.append(f"**Доступность:** {type_row['context']}\n")

    # Группировка членов типа
    constructors = [m for m in members if m["item_type"] == "constructor"]
    methods = [m for m in members if m["item_type"] == "method"]
    properties = [m for m in members if m["item_type"] == "property"]
    events = [m for m in members if m["item_type"] == "event"]

    if constructors:
        lines.append("## Конструкторы")
        for c in constructors:
            syn = f" — `{c['syntax']}`" if c["syntax"] else ""
            lines.append(f"- **{c['name_ru']}** ({c['name_en']}){syn}")
        lines.append("")

    if methods:
        lines.append(f"## Методы ({len(methods)})")
        for m in methods:
            syn = f" — `{m['syntax']}`" if m["syntax"] else ""
            ctx = f" *[{m['context']}]*" if m["context"] else ""
            lines.append(f"- **{m['name_ru']}** ({m['name_en']}){syn}{ctx}")
        lines.append("")

    if properties:
        lines.append(f"## Свойства ({len(properties)})")
        for p in properties:
            ctx = f" *[{p['context']}]*" if p["context"] else ""
            lines.append(f"- **{p['name_ru']}** ({p['name_en']}){ctx}")
        lines.append("")

    if events:
        lines.append(f"## События ({len(events)})")
        for e in events:
            lines.append(f"- **{e['name_ru']}** ({e['name_en']})")
        lines.append("")

    return "\n".join(lines)

@server.tool()
def get_method_info(method_name: str, type_name: Optional[str] = None) -> str:
    """
    Получить детальное описание метода или глобальной функции платформы 1С
    (синтаксис, параметры, типы, возвращаемое значение, контекст выполнения).
    
    Параметры:
      method_name: Имя метода или функции (например: "Найти", "Получить", "ПрочитатьJSON", "Формат").
      type_name: Опциональное имя типа/объекта (например: "HTTPСоединение", "ТаблицаЗначений").
    """
    conn = get_db_connection()
    cur = conn.cursor()

    if type_name:
        cur.execute("""
        SELECT * FROM articles
        WHERE (name_ru = ? COLLATE NOCASE OR name_en = ? COLLATE NOCASE)
          AND (parent_ru = ? COLLATE NOCASE OR parent_en = ? COLLATE NOCASE)
          AND item_type = 'method'
        LIMIT 1
        """, (method_name.strip(), method_name.strip(), type_name.strip(), type_name.strip()))
    else:
        cur.execute("""
        SELECT * FROM articles
        WHERE (name_ru = ? COLLATE NOCASE OR name_en = ? COLLATE NOCASE)
          AND item_type IN ('method', 'other')
        ORDER BY CASE WHEN parent_ru = 'Глобальный контекст' THEN 0 ELSE 1 END, id
        LIMIT 1
        """, (method_name.strip(), method_name.strip()))

    row = cur.fetchone()
    conn.close()

    if not row:
        target = f"{type_name}.{method_name}" if type_name else method_name
        return f"Метод `{target}` не найден в документации платформы."

    return row["description"].lstrip('\ufeff').strip()

@server.tool()
def get_query_help(keyword: str) -> str:
    """
    Получить справку по языку запросов 1С:Предприятие (конструкции, операторы, встроенные функции запросов).
    
    Параметры:
      keyword: Ключевое слово или функция языка запросов (например: "КОНЕЦПЕРИОДА", "ПОЛНОЕ СОЕДИНЕНИЕ", "ВЫРАЗИТЬ", "DATEDIFF", "ИТОГИ").
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # Точный поиск по имени
    cur.execute("""
    SELECT * FROM articles
    WHERE book = 'shquery'
      AND (name_ru = ? COLLATE NOCASE OR name_en = ? COLLATE NOCASE OR title LIKE '%' || ? || '%')
    LIMIT 1
    """, (keyword.strip(), keyword.strip(), keyword.strip()))
    row = cur.fetchone()

    if not row:
        # FTS5 поиск в shquery
        fts_q = sanitize_fts_query(keyword)
        cur.execute("""
        SELECT a.* FROM articles_fts f
        JOIN articles a ON a.id = f.rowid
        WHERE articles_fts MATCH ? AND a.book = 'shquery'
        LIMIT 1
        """, (fts_q,))
        row = cur.fetchone()

    conn.close()

    if not row:
        return f"Справка по конструкции языка запросов '{keyword}' не найдена."

    return row["description"].lstrip('\ufeff').strip()

@server.tool()
def check_compatibility(feature_or_method: str, type_name: Optional[str] = None) -> str:
    """
    Проверить версию платформы, в которой появилась языковая конструкция/метод,
    а также доступные контексты выполнения (Клиент, Сервер, Мобильный клиент).
    
    Параметры:
      feature_or_method: Имя метода, типа или конструкции (например: "ВызватьHTTPМетодАсинх", "СтрокаJSON").
      type_name: Опциональный тип-родитель.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    if type_name:
        cur.execute("""
        SELECT title, parent_ru, name_ru, name_en, syntax, context, version_since
        FROM articles
        WHERE (name_ru = ? COLLATE NOCASE OR name_en = ? COLLATE NOCASE)
          AND (parent_ru = ? COLLATE NOCASE OR parent_en = ? COLLATE NOCASE)
        LIMIT 1
        """, (feature_or_method.strip(), feature_or_method.strip(), type_name.strip(), type_name.strip()))
    else:
        cur.execute("""
        SELECT title, parent_ru, name_ru, name_en, syntax, context, version_since
        FROM articles
        WHERE (name_ru = ? COLLATE NOCASE OR name_en = ? COLLATE NOCASE OR title LIKE ? || '%')
        LIMIT 1
        """, (feature_or_method.strip(), feature_or_method.strip(), feature_or_method.strip()))

    row = cur.fetchone()
    conn.close()

    if not row:
        return f"Элемент '{feature_or_method}' не найден в базе документации."

    ver = row["version_since"] or "Доступен в базовых версиях 8.0+"
    ctx = row["context"] or "Не указано / Универсальный"

    res = [
        f"### Проверка совместимости для: `{row['title']}`",
        f"- **Появление в версии:** {ver}",
        f"- **Контексты исполнения:** {ctx}",
    ]
    if row["syntax"]:
        res.append(f"- **Синтаксис:** `{row['syntax']}`")
    return "\n".join(res)

if __name__ == "__main__":
    server.run(transport="stdio")
