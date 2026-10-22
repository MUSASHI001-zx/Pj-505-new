-- 011: เก็บข้อมูล myTCAS แบบเต็ม — รอบรับสมัคร โครงการ เกณฑ์คะแนน และข้อมูลหลักสูตร
-- รันใน Supabase SQL Editor (รันซ้ำได้ ไม่พัง)
-- เปิด RLS ไม่มี policy: เข้าถึงได้เฉพาะ backend ผ่าน service role เท่านั้น

-- ---------------------------------------------------------------------------
-- institutions: เติมข้อมูลจาก myTCAS (university_id / ชื่อไทย-อังกฤษ / ประเภท)
-- ---------------------------------------------------------------------------
alter table public.institutions add column if not exists name_en text;
alter table public.institutions add column if not exists tc_type text;

-- ---------------------------------------------------------------------------
-- faculties: ข้อมูลคณะ/หลักสูตรจาก myTCAS (courses.json)
-- ---------------------------------------------------------------------------
alter table public.faculties add column if not exists campus text;
alter table public.faculties add column if not exists program_id text;   -- program_id ของ myTCAS
alter table public.faculties add column if not exists program_name_en text;
alter table public.faculties add column if not exists program_type text;
alter table public.faculties add column if not exists field_name text;   -- สาขา/กลุ่มสาขา
alter table public.faculties add column if not exists degree_level text; -- ระดับ ป.ตรี/ปวส.
alter table public.faculties add column if not exists cost text;         -- ค่าเล่าเรียน
alter table public.faculties add column if not exists graduate_rate text;
alter table public.faculties add column if not exists employment_rate text;
alter table public.faculties add column if not exists median_salary text;
create index if not exists faculties_program_id_idx on public.faculties(program_id);
create index if not exists faculties_field_idx on public.faculties(field_name);

-- ---------------------------------------------------------------------------
-- admissions: ข้อมูลรอบรับสมัครจาก myTCAS (rounds/*.json) — เก็บรายละเอียดเกณฑ์คะแนน
-- ---------------------------------------------------------------------------
alter table public.admissions add column if not exists project_id text;
alter table public.admissions add column if not exists program_id text;
alter table public.admissions add column if not exists round_type text;   -- 1_2570 / 2_2570 / 3_2570
alter table public.admissions add column if not exists project_name text;
alter table public.admissions add column if not exists project_name_en text;
alter table public.admissions add column if not exists quota integer;     -- จำนวนที่รับ
alter table public.admissions add column if not exists min_gpax numeric;  -- เกณฑ์ GPA 10 วิชา
alter table public.admissions add column if not exists min_total_score numeric; -- เกณฑ์คะแนนรวม TGAT/TPAT
alter table public.admissions add column if not exists min_gpa22 numeric;
alter table public.admissions add column if not exists min_gpa23 numeric;
alter table public.admissions add column if not exists min_gpa24 numeric;
alter table public.admissions add column if not exists min_credit_gpa22 numeric;
alter table public.admissions add column if not exists min_credit_gpa23 numeric;
alter table public.admissions add column if not exists min_credit_gpa24 numeric;
alter table public.admissions add column if not exists min_age integer;
alter table public.admissions add column if not exists max_age integer;
alter table public.admissions add column if not exists condition text;      -- เงื่อนไขการรับ
alter table public.admissions add column if not exists description text;
alter table public.admissions add column if not exists interview_location text;
alter table public.admissions add column if not exists interview_date text;
alter table public.admissions add column if not exists interview_time text;
alter table public.admissions add column if not exists score_conditions text; -- JSON เกณฑ์คะแนน
alter table public.admissions add column if not exists scores text;          -- JSON คะแนนส่วน/สูงสุด
alter table public.admissions add column if not exists folio_criteria text;  -- เกณฑ์ Portfolio
alter table public.admissions add column if not exists closed_date date;     -- วันปิดรับ
alter table public.admissions add column if not exists academic_year text;   -- ปีการศึกษา เช่น 2570
alter table public.admissions add column if not exists source text;          -- mytcas

create index if not exists admissions_round_type_idx on public.admissions(round_type);
create index if not exists admissions_program_id_idx on public.admissions(program_id);
create index if not exists admissions_project_idx on public.admissions(project_id);
create index if not exists admissions_closed_date_idx on public.admissions(closed_date);

-- เก็บรายการรอบไว้ที่เดียวกัน (program_id + project_id + round_type)
-- upsert ด้วย tc_uid = "admission:{program_id}:{project_id}:{round_type}"
create unique index if not exists admissions_tc_uid_uidx on public.admissions(tc_uid) where tc_uid is not null;

alter table public.faculties enable row level security;
alter table public.admissions enable row level security;
