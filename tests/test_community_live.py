"""ทดสอบระบบกระทู้ชุมชนกับฐานข้อมูลจริง — เน้นกฎ 1 คนต่อ 1 ไลก์ / 1 โหวต และการแนบรูป

สร้างกระทู้ทดสอบแล้วลบทิ้งหลังทดสอบ (cascade ลบตัวเลือก/โหวต/ไลก์ที่ผูกไว้)
รัน: python tests/test_community_live.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.repository import SupabaseRepository  # noqa: E402

FAILURES: list[str] = []
USER_ID = "cfedb072-3ff7-4cea-8b5c-219ffcf4fce2"


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


def main() -> int:
    repo = SupabaseRepository()
    if not repo.configured:
        print("Supabase ไม่ได้ตั้งค่า — ข้าม")
        return 0

    import app.community as community_module

    async def fake_require_user(request, repo_arg):
        return {
            "id": request.headers.get("x-test-user") or USER_ID,
            "email": "probe@example.com",
            "user_metadata": {"full_name": "ผู้ทดสอบ"},
        }

    community_module.require_user = fake_require_user

    test_app = FastAPI()
    test_app.include_router(community_module.build_router(repo))
    client = TestClient(test_app)

    print("\n=== 1. สร้างกระทู้ทดสอบ ===")
    created = client.post("/api/community/posts", json={
        "title": "[ทดสอบระบบ] กระทู้ชั่วคราว",
        "body": "ทดสอบกฎ 1 คนต่อ 1 เสียง",
        "options": ["ตัวเลือก ก", "ตัวเลือก ข"],
    })
    check("สร้างกระทู้ได้", created.status_code == 201, created.text[:200])
    if created.status_code != 201:
        return 1
    post = created.json()["post"]
    post_id = post["id"]
    option_a = post["options"][0]["id"]
    option_b = post["options"][1]["id"]

    try:
        print("\n=== 2. กฎ 1 คน = 1 โหวต ===")
        first = client.post(f"/api/community/posts/{post_id}/vote", json={"option_id": option_a})
        check("โหวตครั้งแรกได้", first.status_code == 200, first.text[:200])
        check("ยอดรวมเป็น 1", first.json().get("total_votes") == 1, str(first.json().get("total_votes")))

        second = client.post(f"/api/community/posts/{post_id}/vote", json={"option_id": option_b})
        check("โหวตทับได้ (คนเดิมเปลี่ยนคำตอบ)", second.status_code == 200, second.text[:200])
        check("ยอดรวมยังเป็น 1 (ไม่ใช่ 2)", second.json().get("total_votes") == 1, str(second.json().get("total_votes")))

        rows = asyncio.run(repo.select("community_post_votes", {"select": "post_id,option_id,open_id", "post_id": f"eq.{post_id}"}))
        check("ในฐานข้อมูลมีโหวตของคนนี้แค่ 1 แถว", len(rows or []) == 1, str(rows))
        check("แถวที่เหลือเป็นตัวเลือกที่เปลี่ยนไป", bool(rows) and int(rows[0]["option_id"]) == option_b, str(rows))

        third = client.post(f"/api/community/posts/{post_id}/vote", json={"option_id": option_b})
        check("กดตัวเลือกเดิมซ้ำ = ยกเลิกโหวต", third.json().get("my_vote") is None, str(third.json().get("my_vote")))
        check("ยอดรวมกลับเป็น 0", third.json().get("total_votes") == 0, str(third.json().get("total_votes")))

        print("\n=== 3. กฎ 1 คน = 1 ไลก์ ===")
        liked = client.post(f"/api/community/posts/{post_id}/like")
        check("กดไลก์ได้", liked.status_code == 200 and liked.json().get("liked") is True, liked.text[:200])
        check("จำนวนไลก์ = 1", liked.json().get("likes") == 1, str(liked.json().get("likes")))
        again = client.post(f"/api/community/posts/{post_id}/like")
        check("กดซ้ำ = ยกเลิก (ไม่ใช่ไลก์ 2 ครั้ง)", again.json().get("liked") is False, str(again.json()))
        check("จำนวนไลก์กลับเป็น 0", again.json().get("likes") == 0, str(again.json().get("likes")))

        like_rows = asyncio.run(repo.select("community_post_likes", {"select": "post_id,open_id", "post_id": f"eq.{post_id}"}))
        check("ในฐานข้อมูลมีไลก์ของคนนี้แค่ 1 แถว", len(like_rows or []) <= 1, str(like_rows))

        print("\n=== 4. tag ที่ผู้ใช้ส่งมาต้องมีอยู่จริง ===")
        tagged = client.post("/api/community/posts", json={
            "title": "[ทดสอบระบบ] tag ปลอม", "tags": ["แท็กที่ไม่มีจริง-12345"],
        })
        check("tag ที่ไม่มีอยู่ถูกตัดออก", tagged.json()["post"]["tags"] == [], str(tagged.json()["post"]["tags"]))
        client.delete(f"/api/community/posts/{tagged.json()['post']['id']}")

        print("\n=== 5. อัปโหลดรูป ===")
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
            "00000049454e44ae426082"
        )
        bucket_ready = asyncio.run(repo.storage_bucket_exists("community-uploads"))
        if not bucket_ready:
            print("      SKIP  ยังไม่ได้รัน migration 014 — bucket 'community-uploads' ยังไม่มี")
            print("            (รัน supabase/migrations/014_community_images_and_votes.sql แล้วรันเทสต์นี้ซ้ำ)")
        else:
            uploaded = client.post("/api/community/uploads", files={"file": ("test.png", png, "image/png")})
            check("อัปโหลดรูปได้", uploaded.status_code == 201, uploaded.text[:250])
            if uploaded.status_code == 201:
                url = uploaded.json().get("url") or ""
                check("ได้ URL รูปกลับมา", url.startswith("http"), url)
                with_img = client.post("/api/community/posts", json={
                    "title": "[ทดสอบระบบ] กระทู้มีรูป", "image_url": url,
                })
                check("สร้างกระทู้พร้อมรูปได้", with_img.status_code == 201, with_img.text[:200])
                check("กระทู้เก็บ image_url", with_img.json()["post"].get("image_url") == url, str(with_img.json()["post"].get("image_url")))
                client.delete(f"/api/community/posts/{with_img.json()['post']['id']}")

        print("\n=== 6. รูปที่ไม่ใช่ไฟล์รูปถูกปฏิเสธ ===")
        fake = client.post("/api/community/uploads", files={"file": ("bad.txt", b"hello world", "text/plain")})
        check("ไฟล์ที่ไม่ใช่รูปถูกปฏิเสธ", fake.status_code == 400, fake.text[:200])

    finally:
        print("\n=== ล้างกระทู้ทดสอบ ===")
        removed = client.delete(f"/api/community/posts/{post_id}")
        check("ลบกระทู้ทดสอบได้", removed.status_code == 200, removed.text[:150])

    print("\n=== สรุป ===")
    if FAILURES:
        print(f"ผ่าน {len(FAILURES)} ข้อที่ไม่ผ่าน:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("ผ่านทั้งหมด")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
