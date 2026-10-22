from __future__ import annotations

import os
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncio

import httpx

COLUMN_CACHE_TTL = 60.0  # วินาที — ผลของการตรวจสอบว่าตารางมีคอลัมน์นี้จริงไหม


def _load_env_file() -> None:
    """Load ../.env into os.environ so the app works however uvicorn is launched."""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


class SupabaseRepository:
    def __init__(self) -> None:
        self.url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.anon_key = os.getenv("SUPABASE_ANON_KEY", "")
        self.service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.auth_configured = bool(self.url and self.anon_key)
        self.configured = bool(self.url and self.anon_key and self.service_key)
        self.last_database_error: str | None = None
        self._column_cache: dict[str, tuple[datetime, bool]] = {}
        self._role_column: str | None = None
        # client เดียวใช้ร่วมกัน — เปิดใหม่ทุกครั้งแพง (TLS handshake ~400ms) ทำให้ API ช้า
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """client เดียวที่ใช้ซ้ำทั้งแอป (keep-alive) — ต้องปิดตอนแอปหยุด

        ถ้า event loop เปลี่ยน (เช่นในเทสต์) ต้องสร้าง client ใหม่ ไม่งั้นจะใช้ connection ของ loop เก่า
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._client is None or self._client.is_closed or self._client_loop is not loop:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0, read=30.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
            self._client_loop = loop
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """ยิง request พร้อม retry — Supabase ในโตเกียวเป็น latency สูง และ connection หลุดได้"""
        client = self._get_client()
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                return await client.request(method, f"{self.url}/rest/v1/{path}", **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(0.4 * (attempt + 1))  # backoff สั้น ๆ
        raise last_exc if last_exc else RuntimeError("request failed")

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }

    async def insert(self, table: str, payload: dict[str, Any]) -> bool:
        if not self.configured:
            return False
        try:
            response = await self._request(
                "POST", table,
                headers={**self._headers(), "Prefer": "return=minimal"},
                json=payload,
            )
            if response.is_error:
                self.last_database_error = f"insert {table} failed: {response.status_code} {response.text[:300]}"
                print(self.last_database_error)
                return False
            self.last_database_error = None
            return True
        except httpx.HTTPError as exc:
            self.last_database_error = f"insert {table} error: {exc}"
            print(self.last_database_error)
            return False

    def _fail(self, step: str, response: "httpx.Response") -> bool:
        self.last_database_error = f"users {step} failed: {response.status_code} {response.text[:300]}"
        print(self.last_database_error)
        return False

    async def sync_user(self, payload: dict[str, Any]) -> bool:
        """บันทึก/อัปเดตผู้ใช้ในตาราง public.users (คอลัมน์ openId เป็นตัวระบุ)."""
        if not self.configured:
            return False
        headers = {**self._headers(), "Prefer": "return=minimal"}
        # คอลัมน์บทบาทต่างกันตาม schema ที่ deploy — ใช้ชื่อที่มีจริง
        role_column = await self.user_role_column()
        record = {k: v for k, v in payload.items() if k != "accountRole"}
        if payload.get("accountRole"):
            record[role_column] = payload["accountRole"]
        try:
            client = self._get_client()
            lookup = await client.get(
                f"{self.url}/rest/v1/users",
                headers=self._headers(),
                params={"select": "id", "openId": f"eq.{payload['openId']}", "limit": "1"},
            )
            if lookup.is_error:
                return self._fail("lookup", lookup)
            rows = lookup.json()
            if rows:
                response = await client.patch(
                    f"{self.url}/rest/v1/users", headers=headers,
                    params={"id": f"eq.{rows[0]['id']}"}, json=record,
                )
            else:
                response = await client.post(f"{self.url}/rest/v1/users", headers=headers, json=record)
            if response.is_error:
                return self._fail("write", response)
            self.last_database_error = None
            return True
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            self.last_database_error = f"users sync error: {exc}"
            print(self.last_database_error)
            return False

    async def touch_presence(self, visitor_id: str) -> bool:
        if not self.configured:
            return False
        try:
            client = self._get_client()
            response = await client.post(
                f"{self.url}/rest/v1/online_visitors",
                headers={**self._headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
                params={"on_conflict": "id"},
                json={"id": visitor_id, "last_seen": datetime.now(timezone.utc).isoformat()},
            )
            response.raise_for_status()
            self.last_database_error = None
            return True
        except httpx.HTTPError:
            self.last_database_error = "presence_table_unavailable"
            print("presence failed")
            return False

    async def _count(self, table: str, filters: dict[str, str] | None = None) -> int | None:
        if not self.configured:
            return None
        headers = {**self._headers(), "Prefer": "count=exact"}
        params = {"select": "id", "limit": "1", **(filters or {})}
        try:
            client = self._get_client()
            response = await client.get(f"{self.url}/rest/v1/{table}", headers=headers, params=params)
            response.raise_for_status()
            total = response.headers.get("content-range", "*/0").rsplit("/", 1)[-1]
            return int(total) if total.isdigit() else 0
        except (httpx.HTTPError, ValueError) as exc:
            self.last_database_error = f"count {table} failed: {exc}"
            print(self.last_database_error)
            return None

    async def stats(self) -> dict[str, int | None]:
        self.last_database_error = None
        online_since = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        return {
            "users": await self._count("users"),  # ผู้สมัคร = แถวในตาราง users
            "views": await self._count("page_views"),  # ยอดเข้าชมสะสม
            "online": await self._count("online_visitors", {"last_seen": f"gt.{online_since}"}),
        }

    # ---------- helpers ทั่วไป (ใช้กับระบบบัญชี) ----------
    async def select(self, table: str, params: dict[str, str], quiet: bool = False) -> list[dict[str, Any]] | None:
        """อ่านแถวจากตาราง คืน None เมื่อล้มเหลว (ดู last_database_error).

        quiet=True ใช้ตอนเช็คว่าตาราง/view มีอยู่จริงไหม — ไม่ต้องพิมพ์ error รกหน้าจอ
        """
        if not self.configured:
            return None
        try:
            response = await self._request("GET", table, headers=self._headers(), params=params)
            if response.is_error:
                self.last_database_error = f"select {table} failed: {response.status_code} {response.text[:300]}"
                if not quiet:
                    print(self.last_database_error)
                return None
            self.last_database_error = None
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self.last_database_error = f"select {table} error: {exc}"
            if not quiet:
                print(self.last_database_error)
            return None

    async def upsert(self, table: str, record: dict[str, Any], on_conflict: str) -> dict[str, Any] | None:
        """เพิ่มหรืออัปเดตแถวตาม on_conflict คืนแถวที่บันทึก หรือ None เมื่อล้มเหลว."""
        if not self.configured:
            return None
        try:
            response = await self._request(
                "POST", table,
                headers={**self._headers(), "Prefer": "resolution=merge-duplicates,return=representation"},
                params={"on_conflict": on_conflict},
                json=record,
            )
            if response.is_error:
                self.last_database_error = f"upsert {table} failed: {response.status_code} {response.text[:300]}"
                print(self.last_database_error)
                return None
            rows = response.json()
            self.last_database_error = None
            return rows[0] if rows else {}
        except (httpx.HTTPError, ValueError) as exc:
            self.last_database_error = f"upsert {table} error: {exc}"
            print(self.last_database_error)
            return None

    async def upsert_many(self, table: str, records: list[dict[str, Any]], on_conflict: str, batch_size: int = 200) -> int:
        """อัปเดตหลายแถวทีเดียว (upsert ตาม on_conflict) คืนจำนวนแถวที่บันทึกสำเร็จ

        ใช้เมื่อซิงก์ข้อมูลจำนวนมาก (เช่น myTCAS) — ลดจำนวน request ลงเหลือไม่กี่สิบครั้ง
        """
        if not self.configured or not records:
            return 0
        saved = 0
        for start in range(0, len(records), batch_size):
            chunk = records[start:start + batch_size]
            try:
                response = await self._request(
                    "POST", table,
                    headers={**self._headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
                    params={"on_conflict": on_conflict},
                    json=chunk,
                )
                if response.is_error:
                    self.last_database_error = f"upsert_many {table} failed: {response.status_code} {response.text[:300]}"
                    print(self.last_database_error)
                    continue
                saved += len(chunk)
            except (httpx.HTTPError, ValueError) as exc:
                self.last_database_error = f"upsert_many {table} error: {exc}"
                print(self.last_database_error)
        return saved

    async def insert_returning(self, table: str, payload: dict[str, Any], on_conflict: str | None = None) -> dict[str, Any] | None:
        """เพิ่มแถวแล้วคืนแถวที่บันทึก (None เมื่อล้มเหลว)."""
        if not self.configured:
            return None
        params: dict[str, str] = {}
        if on_conflict:
            params["on_conflict"] = on_conflict
        try:
            response = await self._request(
                "POST", table,
                headers={**self._headers(), "Prefer": "return=representation"},
                params=params,
                json=payload,
            )
            if response.is_error:
                self.last_database_error = f"insert {table} failed: {response.status_code} {response.text[:300]}"
                print(self.last_database_error)
                return None
            rows = response.json()
            self.last_database_error = None
            return rows[0] if rows else {}
        except (httpx.HTTPError, ValueError) as exc:
            self.last_database_error = f"insert {table} error: {exc}"
            print(self.last_database_error)
            return None

    async def delete(self, table: str, params: dict[str, str]) -> bool:
        """ลบแถวที่ตรงกับ params (ใช้กับ like/vote ที่ผู้ใช้กดออก)"""
        if not self.configured:
            return False
        try:
            response = await self._request(
                "DELETE", table,
                headers={**self._headers(), "Prefer": "return=minimal"},
                params=params,
            )
            if response.is_error:
                self.last_database_error = f"delete {table} failed: {response.status_code} {response.text[:300]}"
                print(self.last_database_error)
                return False
            self.last_database_error = None
            return True
        except httpx.HTTPError as exc:
            self.last_database_error = f"delete {table} error: {exc}"
            print(self.last_database_error)
            return False

    async def user_role(self, open_id: str) -> str | None:
        """บทบาทของผู้ใช้จากตาราง users (None ถ้าอ่านไม่ได้/ไม่มีข้อมูล)"""
        column = await self.user_role_column()
        rows = await self.select("users", {"select": f"name,{column}", "openId": f"eq.{open_id}", "limit": "1"})
        if not rows:
            return None
        return rows[0].get(column)

    async def column_exists(self, table: str, column: str) -> bool:
        """เช็คว่าตารางมีคอลัมน์นี้จริงไหม — แคชผลไว้ 60 วินาที (คอลัมน์ที่เพิ่ง migration เพิ่มเข้ามาจะได้โดยไม่ต้องรีสตาร์ท)"""
        key = f"{table}.{column}"
        cached = self._column_cache.get(key)
        if cached and (datetime.now(timezone.utc) - cached[0]).total_seconds() < COLUMN_CACHE_TTL:
            return cached[1]
        saved_error = self.last_database_error
        rows = await self.select(table, {"select": column, "limit": "1"})
        self.last_database_error = saved_error  # ไม่ให้การตรวจสอบคอลัมน์ไปกวนข้อความ error จริง
        exists = rows is not None
        self._column_cache[key] = (datetime.now(timezone.utc), exists)
        return exists

    async def user_role_column(self) -> str:
        """คอลัมน์บทบาทในตาราง users — รองรับทั้ง accountRole (schema เดิม) และ role (schema ที่ deploy จริง)"""
        if self._role_column:
            return self._role_column
        for candidate in ("accountRole", "role"):
            if await self.column_exists("users", candidate):
                self._role_column = candidate
                return candidate
        self._role_column = "role"
        return self._role_column

    async def update(self, table: str, params: dict[str, str], record: dict[str, Any]) -> bool:
        if not self.configured:
            return False
        try:
            response = await self._request(
                "PATCH", table,
                headers={**self._headers(), "Prefer": "return=minimal"},
                params=params,
                json=record,
            )
            if response.is_error:
                self.last_database_error = f"update {table} failed: {response.status_code} {response.text[:300]}"
                print(self.last_database_error)
                return False
            self.last_database_error = None
            return True
        except httpx.HTTPError as exc:
            self.last_database_error = f"update {table} error: {exc}"
            print(self.last_database_error)
            return False

    # ---------- Supabase Storage ----------
    async def storage_upload(self, bucket: str, path: str, data: bytes, content_type: str) -> bool:
        """อัปโหลดไฟล์ขึ้น Supabase Storage (เขียนผ่าน service role — ข้าม RLS)"""
        if not self.configured:
            return False
        try:
            client = self._get_client()
            response = await client.post(
                f"{self.url}/storage/v1/object/{bucket}/{path}",
                headers={
                    "apikey": self.service_key,
                    "Authorization": f"Bearer {self.service_key}",
                    "Content-Type": content_type,
                    "x-upsert": "false",
                },
                content=data,
            )
            if response.is_error:
                self.last_database_error = f"storage upload failed: {response.status_code} {response.text[:300]}"
                print(self.last_database_error)
                return False
            self.last_database_error = None
            return True
        except httpx.HTTPError as exc:
            self.last_database_error = f"storage upload error: {exc}"
            print(self.last_database_error)
            return False

    async def storage_delete(self, bucket: str, path: str) -> bool:
        """ลบไฟล์ใน Supabase Storage (ล้มเหลวไม่ทำให้อะไรพัง)"""
        if not self.configured:
            return False
        try:
            client = self._get_client()
            response = await client.delete(
                f"{self.url}/storage/v1/object/{bucket}/{path}",
                headers={"apikey": self.service_key, "Authorization": f"Bearer {self.service_key}"},
            )
            return not response.is_error
        except httpx.HTTPError:
            return False

    async def storage_bucket_exists(self, bucket: str) -> bool:
        """เช็คว่ามี bucket ใน Storage หรือยัง (ใช้บอกว่าระบบแนบรูปใช้ได้หรือไม่)"""
        if not self.configured:
            return False
        try:
            client = self._get_client()
            response = await client.get(
                f"{self.url}/storage/v1/bucket/{bucket}",
                headers={"apikey": self.service_key, "Authorization": f"Bearer {self.service_key}"},
            )
            return not response.is_error
        except httpx.HTTPError:
            return False
