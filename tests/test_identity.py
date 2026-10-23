"""ทดสอบระบบข้อสอบจำลองอาชีพ (Identity Discovery)

ส่วนที่ 1 ทดสอบตรรกะคิดคะแนน/ข้อมูล (ไม่ต้องมี FastAPI)
ส่วนที่ 2 ทดสอบ API ด้วย repo จำลอง (ต้องติดตั้ง fastapi — ถ้าไม่มีจะข้ามพร้อมแจ้งเตือน)

รัน: python tests/test_identity.py
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.identity_data import (  # noqa: E402
    CAREER_BY_ID,
    CAREERS,
    DISCOVER_COUNT,
    DISCOVER_QUESTIONS,
    TRAITS,
    IdentityInputError,
    archetype_for,
    build_profile,
    evaluate,
    evaluate_discover,
    fit_label,
    public_careers,
    public_discover,
)
from app.identity_extra import GROUPS  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


def raises(func: Any, *args: Any) -> bool:
    try:
        func(*args)
    except IdentityInputError:
        return True
    return False


def test_logic() -> None:
    print("\n=== ข้อมูลอาชีพ ===")
    check("มีอย่างน้อย 8 อาชีพ", len(CAREERS) >= 8)
    check("id อาชีพไม่ซ้ำ", len({c["id"] for c in CAREERS}) == len(CAREERS))
    check("ทุกอาชีพมี 5 สถานการณ์ × 4 ตัวเลือก", all(len(c["scenarios"]) == 5 and all(len(s["choices"]) == 4 for s in c["scenarios"]) for c in CAREERS))
    check("น้ำหนักครบทุกมิติ", all(set(c["weights"]) == set(TRAITS) for c in CAREERS))
    check("ทุกอาชีพมีคณะแนะนำและข้อควรรู้", all(c["faculties"] and c["reality"] for c in CAREERS))

    print("\n=== ข้อมูลที่ส่งให้หน้าเว็บ ===")
    public = public_careers()
    flat = repr(public)
    check("ไม่เปิดเผยน้ำหนัก/คะแนนของตัวเลือก", "weights" not in flat and "traits" not in flat and "faculties" not in flat)
    check("มีสถานการณ์และตัวเลือกเป็นข้อความ", all(isinstance(ch, str) for c in public for s in c["scenarios"] for ch in s["choices"]))

    print("\n=== การคิดคะแนน ===")
    for career in CAREERS:
        fits = [evaluate(career["id"], list(a), 3)["fit"] for a in itertools.product(range(4), repeat=5)]
        check(f"{career['name']}: คะแนนอยู่ใน 0-100 และกระจายตัวกว้าง (ต่ำสุด<=20, สูงสุด>=80)",
              min(fits) >= 0 and max(fits) <= 100 and min(fits) <= 20 and max(fits) >= 80, f"{min(fits)}-{max(fits)}")

    answers = [0, 1, 2, 3, 0]
    first = evaluate("doctor", answers, 4)
    check("คำตอบเดิมได้ผลเดิม (deterministic)", first == evaluate("doctor", answers, 4))
    check("ความชอบสูงขึ้น คะแนนเหมาะสมไม่ลดลง",
          evaluate("doctor", answers, 5)["fit"] >= evaluate("doctor", answers, 1)["fit"])
    check("ความชอบมีผลจริง (1 vs 5 ต่างกัน)", evaluate("doctor", answers, 5)["fit"] > evaluate("doctor", answers, 1)["fit"])
    check("ผลมี label/จุดแข็ง/ข้อควรฝึก/คณะ/ข้อสงวนสิทธิ์", all(first.get(k) is not None for k in ("label", "strengths", "to_grow", "faculties", "disclaimer", "traits")))
    check("ข้อสงวนสิทธิ์ระบุว่าไม่ใช่การวินิจฉัย", "ไม่ใช่การวินิจฉัย" in first["disclaimer"])
    check("คะแนนมิติอยู่ใน 0-100", all(0 <= t["score"] <= 100 for t in first["traits"]))
    check("ไม่แสดงมิติที่สถานการณ์ไม่ได้วัด (เช่น 'ลงมือ' ของนักจิตวิทยา)",
          "T" not in {t["key"] for t in evaluate("psychologist", [0] * 5, 3)["traits"]})

    # ชุดคำตอบที่ตรงสไตล์อาชีพที่สุด ต้องได้ผลดีกว่าชุดที่ตรงข้ามที่สุด
    for career in CAREERS:
        results = {a: evaluate(career["id"], list(a), 3)["fit"] for a in itertools.product(range(4), repeat=5)}
        best, worst = max(results, key=results.get), min(results, key=results.get)
        check(f"{career['name']}: คำตอบที่เข้ากับอาชีพที่สุด ({results[best]}) > คำตอบที่เข้ากับน้อยที่สุด ({results[worst]})", results[best] > results[worst])

    check("fit_label ครบทุกช่วง", fit_label(90) != fit_label(60) != fit_label(40) != fit_label(10))

    print("\n=== การตรวจสอบข้อมูลนำเข้า ===")
    check("อาชีพที่ไม่มีอยู่ถูกปฏิเสธ", raises(evaluate, "astronaut", [0] * 5, 3))
    check("ตอบไม่ครบถูกปฏิเสธ", raises(evaluate, "doctor", [0, 1, 2], 3))
    check("ตอบเกินถูกปฏิเสธ", raises(evaluate, "doctor", [0] * 6, 3))
    check("ตัวเลือกนอกช่วงถูกปฏิเสธ", raises(evaluate, "doctor", [0, 1, 2, 3, 4], 3))
    check("ตัวเลือกติดลบถูกปฏิเสธ", raises(evaluate, "doctor", [0, 1, 2, 3, -1], 3))
    check("ตัวเลือกไม่ใช่ตัวเลขถูกปฏิเสธ", raises(evaluate, "doctor", [0, 1, 2, 3, "1"], 3))
    check("ค่า bool ถูกปฏิเสธ", raises(evaluate, "doctor", [True, 1, 2, 3, 0], 3))
    check("answers ไม่ใช่ list ถูกปฏิเสธ", raises(evaluate, "doctor", "01230", 3))
    check("ความชอบ 0 ถูกปฏิเสธ", raises(evaluate, "doctor", [0] * 5, 0))
    check("ความชอบ 6 ถูกปฏิเสธ", raises(evaluate, "doctor", [0] * 5, 6))
    check("ความชอบไม่ใช่ตัวเลขถูกปฏิเสธ", raises(evaluate, "doctor", [0] * 5, "5"))
    check("ไม่มี career_id ถูกปฏิเสธ", raises(evaluate, None, [0] * 5, 3))
    check("career_id เป็น list ไม่ทำให้พัง", raises(evaluate, ["doctor"], [0] * 5, 3))
    assert CAREER_BY_ID


def _answers_for(trait: str) -> list[int]:
    """ชุดคำตอบแบบสำรวจภาพรวมที่เลือกตัวเลือกของมิติ trait ทุกครั้งที่มี (ข้อที่ไม่มีเลือกข้อแรก)"""
    return [next((i for i, c in enumerate(q["choices"]) if trait in c["traits"]), 0) for q in DISCOVER_QUESTIONS]


def test_expanded() -> None:
    print("\n=== อาชีพและหมวด (ชุดขยาย) ===")
    check("มีอย่างน้อย 20 อาชีพ", len(CAREERS) >= 20, str(len(CAREERS)))
    check("ทุกอาชีพอยู่ในหมวดที่มีจริง และทุกหมวดมีอาชีพ", all(c["group"] in GROUPS for c in CAREERS) and {c["group"] for c in CAREERS} == set(GROUPS))
    check("related ชี้ไปอาชีพที่มีจริง ไม่ชี้ตัวเอง", all(r in CAREER_BY_ID and r != c["id"] for c in CAREERS for r in c["related"]))
    check("ทุกอาชีพมีวิธีลองจริง (try_it) อย่างน้อย 2 ข้อ", all(len(c["try_it"]) >= 2 for c in CAREERS))
    check("ทุกอาชีพมีคณะแนะนำอย่างน้อย 3 คณะ", all(len(c["faculties"]) >= 3 for c in CAREERS))
    check("สถานการณ์ในอาชีพเดียวกันไม่ซ้ำกัน", all(len({s["situation"] for s in c["scenarios"]}) == 5 for c in CAREERS))
    check("ข้อความตัวเลือกในสถานการณ์เดียวกันไม่ซ้ำกัน", all(len({ch["text"] for ch in s["choices"]}) == 4 for c in CAREERS for s in c["scenarios"]))
    check("แต่ละมิติมีน้ำหนัก >= 2 อย่างน้อยหนึ่งอาชีพ (ไม่มีมิติตกหล่น)", all(any(c["weights"][t] >= 2 for c in CAREERS) for t in TRAITS))

    print("\n=== ผลต่ออาชีพ (ฟิลด์วิเคราะห์ใหม่) ===")
    result = evaluate("nurse", [1, 1, 0, 2, 0], 5)
    check("ผลมีชื่อสไตล์ ข้อสังเกต วิธีลองจริง อาชีพที่เกี่ยวข้อง ความมั่นใจ", all(result.get(k) for k in ("archetype", "insight", "try_it", "related", "confidence", "group_label")))
    check("ผลส่งคำตอบดิบกลับมาด้วย (เพื่อสรุปรวมได้โดยไม่เชื่อคะแนนจาก client)", result["answers"] == [1, 1, 0, 2, 0] and result["kind"] == "career")
    check("อาชีพที่เกี่ยวข้องมีชื่อและไอคอน", all(r["name"] and r["icon"] for r in result["related"]))
    check("ชื่อสไตล์เหมือนเดิมเมื่อคะแนนเท่ากัน (deterministic)", archetype_for({"A": 50, "C": 50, "H": 50, "L": 50, "T": 50, "O": 50}) == archetype_for({"O": 50, "T": 50, "L": 50, "H": 50, "C": 50, "A": 50}))
    public = public_careers()
    check("public_careers มีหมวดแต่ไม่รั่ว try_it/related/น้ำหนัก", all("group" in c and "try_it" not in c and "related" not in c and "weights" not in c for c in public))

    print("\n=== แบบสำรวจภาพรวม ===")
    check("มี 18 ข้อ ข้อละ 4 ตัวเลือก", DISCOVER_COUNT == 18 and all(len(q["choices"]) == 4 for q in DISCOVER_QUESTIONS))
    appearances = {t: sum(1 for q in DISCOVER_QUESTIONS for c in q["choices"] if t in c["traits"]) for t in TRAITS}
    check("ทุกมิติโผล่ในตัวเลือกเท่ากัน (ไม่เอนเอียง)", len(set(appearances.values())) == 1, str(appearances))
    check("ทุกข้อมีตัวเลือกจากมิติต่างกัน 4 มิติ", all(len({t for c in q["choices"] for t in c["traits"]}) == 4 for q in DISCOVER_QUESTIONS))
    public_q = repr(public_discover())
    check("คำถามที่ส่งหน้าเว็บไม่เปิดเผยมิติ/คะแนน", "traits" not in public_q and "'A'" not in public_q)
    res = evaluate_discover([0] * 18)
    check("ผลมีโปรไฟล์ 6 มิติ อันดับอาชีพ คณะ ข้อสงวนสิทธิ์", len(res["traits"]) == 6 and len(res["top_careers"]) == 8 and res["faculties"] and "ไม่ใช่การวินิจฉัย" in res["disclaimer"])
    check("คะแนนมิติอยู่ใน 0-100", all(0 <= t["score"] <= 100 for t in res["traits"]))
    check("คำตอบเดิมได้ผลเดิม", res == evaluate_discover([0] * 18))
    check("เลือกแต่ตัวเลือกด้านนั้น ได้มิตินั้นเด่นที่สุด", all(max(evaluate_discover(_answers_for(t))["traits"], key=lambda x: x["score"])["key"] == t for t in TRAITS))
    top = {t: [c["career_id"] for c in evaluate_discover(_answers_for(t))["top_careers"][:5]] for t in TRAITS}
    check("สายใส่ใจผู้อื่น → อาชีพสายดูแลคนขึ้นอันดับต้น", {"psychologist", "social_worker", "nurse", "teacher"} & set(top["H"]))
    check("สายวิเคราะห์ → อาชีพสายข้อมูล/เทคนิคขึ้นอันดับต้น", {"developer", "data_analyst", "accountant", "scientist"} & set(top["A"]))
    check("สายสร้างสรรค์ → อาชีพสร้างสรรค์ขึ้นอันดับต้น", {"designer", "architect", "marketer"} & set(top["C"]))
    check("สายลงมือ → อาชีพปฏิบัติขึ้นอันดับต้น", {"vet", "sports", "engineer"} & set(top["T"]))
    check("โปรไฟล์ต่างกันได้อันดับต้นต่างกัน", len({c[0] for c in top.values()}) >= 4)
    check("แบบสำรวจ: ตอบไม่ครบ/นอกช่วง/ชนิดผิดถูกปฏิเสธ",
          raises(evaluate_discover, [0] * 17) and raises(evaluate_discover, [0] * 17 + [4]) and raises(evaluate_discover, [0] * 17 + [True])
          and raises(evaluate_discover, "x") and raises(evaluate_discover, None))

    print("\n=== โปรไฟล์รวม ===")
    entries = [{"career_id": "doctor", "answers": [0, 0, 0, 0, 0], "enjoyment": 4}, {"career_id": "engineer", "answers": [1, 0, 2, 3, 1], "enjoyment": 2}]
    prof = build_profile(entries, _answers_for("A"))
    check("จัดอันดับอาชีพ 10 อันดับแรกจากทุกอาชีพ", len(prof["ranking"]) == 10 and prof["ranking"] == sorted(prof["ranking"], key=lambda r: (-r["score"], r["name"])))
    check("อาชีพที่เคยลองถูกทำเครื่องหมายและมีคะแนนจริง", all(r["tried"] == (r["career_id"] in ("doctor", "engineer")) for r in prof["ranking"] + prof["explore_next"]) and all((r["fit"] is not None) == r["tried"] for r in prof["ranking"]))
    check("explore_next เป็นอาชีพที่ยังไม่เคยลองเท่านั้น ไม่เกิน 3", 1 <= len(prof["explore_next"]) <= 3 and not any(r["tried"] for r in prof["explore_next"]))
    check("โปรไฟล์มีชื่อสไตล์ คณะ ข้อควรฝึก ระดับความมั่นใจ", all(prof.get(k) for k in ("archetype", "faculties", "low_traits", "confidence", "confidence_level")))
    check("คะแนนอยู่ใน 0-100", all(0 <= r["score"] <= 100 for r in prof["ranking"]) and all(0 <= t["score"] <= 100 for t in prof["traits"]))
    check("ความมั่นใจเพิ่มตามจำนวนแหล่งข้อมูล", build_profile(entries[:1])["confidence_level"] == "low" and prof["confidence_level"] == "good")
    check("อาชีพซ้ำใช้เฉพาะรายการแรก (ใหม่สุด)", build_profile([entries[0], {**entries[0], "answers": [3, 3, 3, 3, 3]}])["sources"]["careers"] == 1)
    check("แบบสำรวจอย่างเดียวก็สรุปได้", build_profile([], _answers_for("H"))["sources"] == {"careers": 0, "discover": True})
    check("ไม่มีข้อมูลเลยถูกปฏิเสธ", raises(build_profile, [], None) and raises(build_profile, None, None))
    check("รายการที่ผิดรูปแบบถูกปฏิเสธ", raises(build_profile, ["x"]) and raises(build_profile, [{"career_id": "doctor", "answers": [9] * 5, "enjoyment": 3}]) and raises(build_profile, "x"))
    check("ส่งรายการเกิน 30 ถูกปฏิเสธ", raises(build_profile, [entries[0]] * 31))
    spoof = build_profile([{**entries[0], "fit": 100, "traits": [{"key": "A", "score": 100}]}])
    check("ไม่เชื่อคะแนนที่ client ส่งมา (คำนวณจากคำตอบดิบ)", spoof["ranking"] and spoof == build_profile([entries[0]]))


def test_api() -> None:
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ModuleNotFoundError:
        print("\n=== API === ข้าม: ยังไม่ได้ติดตั้ง fastapi (pip install -r requirements.txt)")
        return

    import app.identity as identity_module

    class FakeRepo:
        configured = True
        auth_configured = True
        last_database_error = None

        def __init__(self) -> None:
            self.rows: list[dict[str, Any]] = []
            self.fail_insert = False

        async def insert_returning(self, table: str, payload: dict[str, Any], on_conflict: str | None = None) -> dict[str, Any] | None:
            if self.fail_insert:
                return None
            row = {"id": f"00000000-0000-0000-0000-{len(self.rows) + 1:012d}", "created_at": "2026-10-23T00:00:00+00:00", **payload}
            self.rows.append(row)
            return row

        async def select(self, table: str, params: dict[str, str], quiet: bool = False) -> list[dict[str, Any]]:
            owner = params["open_id"].removeprefix("eq.")
            return [r for r in self.rows if r["open_id"] == owner]

        async def delete(self, table: str, params: dict[str, str]) -> bool:
            owner, rid = params["open_id"].removeprefix("eq."), params["id"].removeprefix("eq.")
            self.rows = [r for r in self.rows if not (r["open_id"] == owner and r["id"] == rid)]
            return True

    async def fake_require_user(request: Any, repo_arg: Any) -> dict[str, Any]:
        header = request.headers.get("x-test-user")
        if not header:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบก่อน")
        return {"id": header, "email": f"{header}@example.com"}

    identity_module.require_user = fake_require_user
    repo = FakeRepo()
    app = FastAPI()
    app.include_router(identity_module.build_router(repo))
    client = TestClient(app)
    body = {"career_id": "engineer", "answers": [1, 0, 2, 3, 1], "enjoyment": 4}
    user_a, user_b = {"x-test-user": "user-a"}, {"x-test-user": "user-b"}

    print("\n=== API ===")
    listing = client.get("/api/identity/careers")
    check("GET careers ใช้ได้โดยไม่ล็อกอิน", listing.status_code == 200 and len(listing.json()["careers"]) >= 20)
    check("careers ไม่รั่วน้ำหนักคะแนน", "weights" not in listing.text and "traits" not in listing.text)

    guest = client.post("/api/identity/evaluate", json=body)
    check("ผู้เยี่ยมชมคำนวณผลได้ (ไม่บันทึก)", guest.status_code == 200 and guest.json()["saved"] is False and not repo.rows)
    check("ผลตรงกับตัวคิดคะแนนกลาง", guest.json()["result"] == evaluate("engineer", [1, 0, 2, 3, 1], 4))
    check("evaluate: คำตอบไม่ครบได้ 422", client.post("/api/identity/evaluate", json={**body, "answers": [0]}).status_code == 422)
    check("evaluate: body ไม่ใช่ JSON ได้ 400", client.post("/api/identity/evaluate", content="x").status_code == 400)
    check("evaluate: body เป็น list ได้ 400", client.post("/api/identity/evaluate", json=[1, 2]).status_code == 400)

    check("บันทึกผลต้องล็อกอิน", client.post("/api/identity/results", json=body).status_code == 401)
    check("ดูประวัติต้องล็อกอิน", client.get("/api/identity/results").status_code == 401)
    saved = client.post("/api/identity/results", json=body, headers=user_a)
    check("บันทึกผลสำเร็จ 201", saved.status_code == 201 and saved.json()["saved"] is True and saved.json()["result"]["id"])
    check("บันทึกลงตารางพร้อม open_id ของผู้ใช้จาก token ไม่ใช่จาก body",
          len(repo.rows) == 1 and repo.rows[0]["open_id"] == "user-a" and repo.rows[0]["career_id"] == "engineer")
    spoof = client.post("/api/identity/results", json={**body, "open_id": "user-b", "fit": 100, "result": {"fit": 100}}, headers=user_a)
    check("ไม่เชื่อ open_id/คะแนนที่ client ส่งมา", spoof.status_code == 201 and repo.rows[-1]["open_id"] == "user-a" and repo.rows[-1]["result"]["fit"] != 100)
    check("บันทึกคำตอบผิดได้ 422 และไม่เพิ่มแถว", client.post("/api/identity/results", json={**body, "enjoyment": 9}, headers=user_a).status_code == 422 and len(repo.rows) == 2)

    mine = client.get("/api/identity/results", headers=user_a).json()["results"]
    check("ประวัติของตัวเองมาครบ", len(mine) == 2 and all(r["career_id"] == "engineer" and r["id"] for r in mine))
    check("ผู้ใช้อื่นไม่เห็นผลของเรา", client.get("/api/identity/results", headers=user_b).json()["results"] == [])

    target = mine[0]["id"]
    check("ลบผลของคนอื่นไม่ได้ (ข้อมูลยังอยู่)", client.delete(f"/api/identity/results/{target}", headers=user_b).status_code == 200 and len(repo.rows) == 2)
    check("id แปลกปลอมถูกปฏิเสธ 404", client.delete("/api/identity/results/..%2F..%2Fx;drop", headers=user_a).status_code in (404, 405))
    check("ลบผลของตัวเองได้", client.delete(f"/api/identity/results/{target}", headers=user_a).status_code == 200 and len(repo.rows) == 1)

    repo.fail_insert = True
    check("บันทึกล้มเหลวได้ 503 พร้อมข้อความ", client.post("/api/identity/results", json=body, headers=user_a).status_code == 503)

    print("\n=== API ส่วนขยาย (แบบสำรวจภาพรวม / โปรไฟล์รวม) ===")
    repo.fail_insert = False
    repo.rows.clear()
    listing = client.get("/api/identity/careers").json()
    check("careers มีรายการหมวดอาชีพ", len(listing["groups"]) == len(GROUPS) and len(listing["careers"]) >= 20)
    questions = client.get("/api/identity/discover").json()["questions"]
    check("GET discover ได้ 18 ข้อโดยไม่ล็อกอินและไม่รั่วมิติ", len(questions) == 18 and "traits" not in repr(questions))
    d_body = {"answers": _answers_for("H")}
    d_guest = client.post("/api/identity/discover/evaluate", json=d_body)
    check("ผู้เยี่ยมชมสรุปผลแบบสำรวจได้ (ไม่บันทึก)", d_guest.status_code == 200 and d_guest.json()["saved"] is False and not repo.rows)
    check("ผลตรงกับตัวคิดคะแนนกลาง", d_guest.json()["result"] == evaluate_discover(d_body["answers"]))
    check("discover: ตอบไม่ครบได้ 422", client.post("/api/identity/discover/evaluate", json={"answers": [0]}).status_code == 422)
    check("discover: body ผิดรูปแบบได้ 400", client.post("/api/identity/discover/evaluate", content="x").status_code == 400 and client.post("/api/identity/discover/evaluate", json=[1]).status_code == 400)
    check("บันทึกผลแบบสำรวจต้องล็อกอิน", client.post("/api/identity/discover/results", json=d_body).status_code == 401)
    d_saved = client.post("/api/identity/discover/results", json=d_body, headers=user_a)
    check("บันทึกผลแบบสำรวจสำเร็จเป็น career_id = discover ของผู้ใช้จาก token", d_saved.status_code == 201 and repo.rows[0]["career_id"] == "discover" and repo.rows[0]["open_id"] == "user-a")
    check("ผลที่บันทึกมี kind = discover และประวัติดึงกลับมาได้", client.get("/api/identity/results", headers=user_a).json()["results"][0]["kind"] == "discover")

    p_guest = client.post("/api/identity/profile", json={"entries": [body], "discover": d_body["answers"]})
    check("ผู้เยี่ยมชมสรุปรวมได้จากคำตอบดิบ", p_guest.status_code == 200 and p_guest.json()["profile"] == build_profile([body], d_body["answers"]))
    check("profile: ไม่มีข้อมูลได้ 422", client.post("/api/identity/profile", json={}).status_code == 422)
    check("profile: ข้อมูลผิดได้ 422 / body ผิดได้ 400", client.post("/api/identity/profile", json={"entries": [{"career_id": "x"}]}).status_code == 422 and client.post("/api/identity/profile", content="x").status_code == 400)

    check("GET profile ต้องล็อกอิน", client.get("/api/identity/profile").status_code == 401)
    client.post("/api/identity/results", json=body, headers=user_a)
    mine_profile = client.get("/api/identity/profile", headers=user_a)
    check("สรุปรวมจากผลที่บันทึกไว้ (รวมแบบสำรวจ)", mine_profile.status_code == 200 and mine_profile.json()["profile"]["sources"] == {"careers": 1, "discover": True})
    check("ผู้ใช้อื่นไม่มีข้อมูลได้ 422 ไม่เห็นของเรา", client.get("/api/identity/profile", headers=user_b).status_code == 422)
    repo.rows.append({"id": "00000000-0000-0000-0000-0000000000ff", "created_at": "2026-10-23T00:00:00+00:00", "open_id": "user-a", "career_id": "retired_job", "answers": [0] * 5, "result": {"enjoyment": 3}})
    check("แถวอาชีพที่ถูกเอาออกจากระบบไม่ทำให้สรุปรวมพัง", client.get("/api/identity/profile", headers=user_a).status_code == 200)


def main() -> int:
    test_logic()
    test_expanded()
    test_api()
    print()
    if FAILURES:
        print(f"ไม่ผ่าน {len(FAILURES)} ข้อ:")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("ผ่านทั้งหมด")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
