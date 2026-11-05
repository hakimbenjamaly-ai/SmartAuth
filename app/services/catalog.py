"""إدارة التصنيفات والدول والمدن والجهات (كلها من قاعدة البيانات)."""
from __future__ import annotations

from ..core.permissions import MANAGE_ENTITIES, SEARCH, VIEW_ENTITIES, require
from ..core.textnorm import normalize_ar, sql_like_ar
from . import BaseService

ENTITY_FIELDS = ("category_id", "name", "name_en", "country_id", "city_id",
                 "address", "phone", "email", "notes", "is_active")


class CatalogService(BaseService):
    # ------------------------------------------------------------ categories
    @require(VIEW_ENTITIES)
    def categories(self, active_only: bool = True):
        q = "SELECT c.*, (SELECT COUNT(*) FROM entities e WHERE e.category_id=c.id) AS n FROM categories c"
        if active_only:
            q += " WHERE c.is_active=1"
        return self.db.query(q + " ORDER BY sort_order, name")

    @require(MANAGE_ENTITIES)
    def add_category(self, name: str, sort_order: int = 100) -> int:
        cid = self.db.insert("INSERT INTO categories(name,sort_order) VALUES (?,?)",
                             (name.strip(), sort_order))
        self.audit("category_add", f"category:{cid}", name)
        return cid

    @require(MANAGE_ENTITIES)
    def update_category(self, cid: int, name: str | None = None, sort_order: int | None = None,
                        is_active: int | None = None) -> None:
        for col, v in (("name", name), ("sort_order", sort_order), ("is_active", is_active)):
            if v is not None:
                self.db.execute(f"UPDATE categories SET {col}=? WHERE id=?", (v, cid))
        self.audit("category_update", f"category:{cid}")

    @require(MANAGE_ENTITIES)
    def delete_category(self, cid: int) -> None:
        if self.db.scalar("SELECT COUNT(*) FROM entities WHERE category_id=?", (cid,)):
            raise ValueError("لا يمكن حذف تصنيف يحتوي على جهات. انقل الجهات أو احذفها أولاً")
        self.db.execute("DELETE FROM categories WHERE id=?", (cid,))
        self.audit("category_delete", f"category:{cid}")

    # ------------------------------------------------------ countries/cities
    @require(VIEW_ENTITIES)
    def countries(self):
        return self.db.query("SELECT * FROM countries ORDER BY name_ar")

    @require(MANAGE_ENTITIES)
    def add_country(self, name_ar: str, name_en: str = "", iso2: str = "") -> int:
        i = self.db.insert("INSERT INTO countries(name_ar,name_en,iso2) VALUES (?,?,?)",
                           (name_ar.strip(), name_en.strip(), iso2.strip().upper()))
        self.audit("country_add", f"country:{i}", name_ar)
        return i

    @require(MANAGE_ENTITIES)
    def update_country(self, cid: int, name_ar: str, name_en: str = "", iso2: str = "") -> None:
        self.db.execute("UPDATE countries SET name_ar=?,name_en=?,iso2=? WHERE id=?",
                        (name_ar, name_en, iso2, cid))
        self.audit("country_update", f"country:{cid}")

    @require(MANAGE_ENTITIES)
    def delete_country(self, cid: int) -> None:
        self.db.execute("DELETE FROM countries WHERE id=?", (cid,))
        self.audit("country_delete", f"country:{cid}")

    @require(VIEW_ENTITIES)
    def cities(self, country_id: int | None = None):
        if country_id:
            return self.db.query("SELECT * FROM cities WHERE country_id=? ORDER BY name", (country_id,))
        return self.db.query("SELECT * FROM cities ORDER BY name")

    @require(MANAGE_ENTITIES)
    def add_city(self, country_id: int, name: str) -> int:
        i = self.db.insert("INSERT INTO cities(country_id,name) VALUES (?,?)", (country_id, name.strip()))
        self.audit("city_add", f"city:{i}", name)
        return i

    @require(MANAGE_ENTITIES)
    def delete_city(self, cid: int) -> None:
        self.db.execute("DELETE FROM cities WHERE id=?", (cid,))
        self.audit("city_delete", f"city:{cid}")

    # -------------------------------------------------------------- entities
    _ENTITY_SELECT = """
        SELECT e.*, c.name AS category_name, co.name_ar AS country_name, ci.name AS city_name,
               (SELECT COUNT(*) FROM persons p WHERE p.entity_id=e.id) AS persons_count
        FROM entities e
        JOIN categories c ON c.id=e.category_id
        LEFT JOIN countries co ON co.id=e.country_id
        LEFT JOIN cities ci ON ci.id=e.city_id
    """

    @require(VIEW_ENTITIES)
    def entities(self, category_id: int | None = None, country_id: int | None = None,
                 text: str = "", active_only: bool = False):
        where, params = [], []
        if category_id:
            where.append("e.category_id=?"); params.append(category_id)
        if country_id:
            where.append("e.country_id=?"); params.append(country_id)
        if active_only:
            where.append("e.is_active=1")
        if text:
            where.append(f"({sql_like_ar('e.name')} LIKE ? OR lower(IFNULL(e.name_en,'')) LIKE ?)")
            t = f"%{normalize_ar(text)}%"
            params += [t, f"%{text.lower()}%"]
        q = self._ENTITY_SELECT + (" WHERE " + " AND ".join(where) if where else "")
        return self.db.query(q + " ORDER BY c.sort_order, e.name", params)

    @require(VIEW_ENTITIES)
    def entity(self, eid: int):
        return self.db.one(self._ENTITY_SELECT + " WHERE e.id=?", (eid,))

    @require(SEARCH)
    def search_entities(self, text: str):
        return self.entities(text=text)

    @require(MANAGE_ENTITIES)
    def add_entity(self, **data) -> int:
        data = {k: v for k, v in data.items() if k in ENTITY_FIELDS}
        if not data.get("name") or not data.get("category_id"):
            raise ValueError("اسم الجهة والتصنيف مطلوبان")
        cols = ",".join(data)
        eid = self.db.insert(f"INSERT INTO entities({cols}) VALUES ({','.join('?' * len(data))})",
                             tuple(data.values()))
        self.audit("entity_add", f"entity:{eid}", data["name"])
        return eid

    @require(MANAGE_ENTITIES)
    def update_entity(self, eid: int, **data) -> None:
        data = {k: v for k, v in data.items() if k in ENTITY_FIELDS}
        if data:
            sets = ",".join(f"{k}=?" for k in data)
            self.db.execute(f"UPDATE entities SET {sets} WHERE id=?", (*data.values(), eid))
            self.audit("entity_update", f"entity:{eid}")

    @require(MANAGE_ENTITIES)
    def delete_entity(self, eid: int) -> None:
        self.db.execute("DELETE FROM entities WHERE id=?", (eid,))
        self.audit("entity_delete", f"entity:{eid}")

    @require(MANAGE_ENTITIES)
    def find_or_create_entity(self, name: str, category_id: int, country_id: int | None = None) -> int:
        r = self.db.one("SELECT id FROM entities WHERE category_id=? AND name=?", (category_id, name.strip()))
        if r:
            return r["id"]
        return self.add_entity(name=name.strip(), category_id=category_id, country_id=country_id)
