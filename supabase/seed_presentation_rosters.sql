begin;

do $$
declare
  cohort record;
  student_count integer;
  teacher_count integer;
begin
  if not exists (
    select 1 from public.departments where name = 'Software Engineering'
  ) then
    raise exception
      'The Software Engineering department is missing; add it before seeding the HOD presentation data.';
  end if;

  select count(*)
  into teacher_count
  from public.profiles
  where is_demo
    and role = 'teacher'
    and department = 'Computer Science'
    and username like 'demo.teacher.%';

  if teacher_count <> 25 then
    raise exception
      'Expected 25 synthetic Computer Science teachers; found %.',
      teacher_count;
  end if;

  for cohort in
    select *
    from (values
      ('BS Cyber Security Technology', 1::smallint),
      ('BS Cyber Security Technology', 2::smallint),
      ('BS Cyber Security Technology', 3::smallint),
      ('BS Cyber Security Technology', 4::smallint),
      ('BS Cyber Security Technology', 5::smallint),
      ('BS Cyber Security Technology', 6::smallint),
      ('BS Cyber Security Technology', 7::smallint),
      ('BS Cyber Security Technology', 8::smallint),
      ('BS Software Engineering', 1::smallint),
      ('BS Software Engineering', 2::smallint),
      ('BS Software Engineering', 3::smallint),
      ('BS Software Engineering', 4::smallint),
      ('BS Software Engineering', 5::smallint),
      ('BS Software Engineering', 6::smallint),
      ('BS Software Engineering', 7::smallint),
      ('BS Software Engineering', 8::smallint),
      ('BS Software Engineering Technology', 1::smallint),
      ('BS Software Engineering Technology', 2::smallint),
      ('BS Software Engineering Technology', 3::smallint),
      ('BS Software Engineering Technology', 4::smallint),
      ('BS Software Engineering Technology', 5::smallint),
      ('BS Software Engineering Technology', 6::smallint),
      ('BS Software Engineering Technology', 7::smallint),
      ('BS Software Engineering Technology', 8::smallint)
    ) as cohorts(program, semester)
  loop
    select count(*)
    into student_count
    from public.profiles
    where is_demo
      and role = 'student'
      and username like 'demo.%'
      and program = cohort.program
      and semester = cohort.semester;

    if student_count <> 40 then
      raise exception
        'Expected 40 synthetic students in % semester %; found %.',
        cohort.program, cohort.semester, student_count;
    end if;
  end loop;
end
$$;

update public.profiles
set department = 'Software Engineering'
where is_demo
  and role = 'student'
  and program = 'BS Software Engineering'
  and username like 'demo.se.%';

insert into public.courses
  (code, name, department, credits, program, semester, is_sample, is_demo)
values
  ('DEMO-CYS-S01', 'Programming Fundamentals', 'Computer Science', 3, 'BS Cyber Security Technology', 1, false, true),
  ('DEMO-CYS-S02', 'Data Structures and Algorithms', 'Computer Science', 3, 'BS Cyber Security Technology', 2, false, true),
  ('DEMO-CYS-S03', 'Computer Networks and Security', 'Computer Science', 3, 'BS Cyber Security Technology', 3, false, true),
  ('DEMO-CYS-S04', 'Secure Software Development', 'Computer Science', 3, 'BS Cyber Security Technology', 4, false, true),
  ('DEMO-CYS-S05', 'Digital Forensics Fundamentals', 'Computer Science', 3, 'BS Cyber Security Technology', 5, false, true),
  ('DEMO-CYS-S06', 'Ethical Hacking Fundamentals', 'Computer Science', 3, 'BS Cyber Security Technology', 6, false, true),
  ('DEMO-CYS-S07', 'Incident Response and Threat Analysis', 'Computer Science', 3, 'BS Cyber Security Technology', 7, false, true),
  ('DEMO-CYS-S08', 'Cybersecurity Capstone Project', 'Computer Science', 3, 'BS Cyber Security Technology', 8, false, true),
  ('DEMO-SE-S01', 'Programming Fundamentals', 'Software Engineering', 3, 'BS Software Engineering', 1, false, true),
  ('DEMO-SE-S02', 'Object-Oriented Programming', 'Software Engineering', 3, 'BS Software Engineering', 2, false, true),
  ('DEMO-SE-S03', 'Data Structures and Algorithms', 'Software Engineering', 3, 'BS Software Engineering', 3, false, true),
  ('DEMO-SE-S04', 'Database Systems', 'Software Engineering', 3, 'BS Software Engineering', 4, false, true),
  ('DEMO-SE-S05', 'Software Requirements Engineering', 'Software Engineering', 3, 'BS Software Engineering', 5, false, true),
  ('DEMO-SE-S06', 'Software Architecture and Design', 'Software Engineering', 3, 'BS Software Engineering', 6, false, true),
  ('DEMO-SE-S07', 'Software Quality and Testing', 'Software Engineering', 3, 'BS Software Engineering', 7, false, true),
  ('DEMO-SE-S08', 'Software Engineering Capstone Project', 'Software Engineering', 3, 'BS Software Engineering', 8, false, true),
  ('DEMO-SET-S01', 'Programming for Software Technology', 'Computer Science', 3, 'BS Software Engineering Technology', 1, false, true),
  ('DEMO-SET-S02', 'Web Application Development', 'Computer Science', 3, 'BS Software Engineering Technology', 2, false, true),
  ('DEMO-SET-S03', 'Mobile Application Development', 'Computer Science', 3, 'BS Software Engineering Technology', 3, false, true),
  ('DEMO-SET-S04', 'User Experience Design', 'Computer Science', 3, 'BS Software Engineering Technology', 4, false, true),
  ('DEMO-SET-S05', 'Cloud Computing Foundations', 'Computer Science', 3, 'BS Software Engineering Technology', 5, false, true),
  ('DEMO-SET-S06', 'DevOps and Software Deployment', 'Computer Science', 3, 'BS Software Engineering Technology', 6, false, true),
  ('DEMO-SET-S07', 'Software Testing Automation', 'Computer Science', 3, 'BS Software Engineering Technology', 7, false, true),
  ('DEMO-SET-S08', 'Applied Software Technology Project', 'Computer Science', 3, 'BS Software Engineering Technology', 8, false, true)
on conflict (code) do update
set name = excluded.name,
    department = excluded.department,
    credits = excluded.credits,
    program = excluded.program,
    semester = excluded.semester,
    is_sample = false,
    is_demo = true
where courses.is_demo;

do $$
begin
  if (
    select count(*)
    from public.courses
    where is_demo
      and code in (
        'DEMO-CYS-S01', 'DEMO-CYS-S02', 'DEMO-CYS-S03', 'DEMO-CYS-S04',
        'DEMO-CYS-S05', 'DEMO-CYS-S06', 'DEMO-CYS-S07', 'DEMO-CYS-S08',
        'DEMO-SE-S01', 'DEMO-SE-S02', 'DEMO-SE-S03', 'DEMO-SE-S04',
        'DEMO-SE-S05', 'DEMO-SE-S06', 'DEMO-SE-S07', 'DEMO-SE-S08',
        'DEMO-SET-S01', 'DEMO-SET-S02', 'DEMO-SET-S03', 'DEMO-SET-S04',
        'DEMO-SET-S05', 'DEMO-SET-S06', 'DEMO-SET-S07', 'DEMO-SET-S08'
      )
  ) <> 24 then
    raise exception
      'A course code is already used by a non-synthetic course; no roster changes were made.';
  end if;
end
$$;

with ordered_courses as (
  select
    id,
    row_number() over (
      order by
        case program
          when 'BS Cyber Security Technology' then 1
          when 'BS Software Engineering' then 2
          when 'BS Software Engineering Technology' then 3
        end,
        semester
    ) as course_number
  from public.courses
  where is_demo
    and code ~ '^DEMO-(CYS|SE|SET)-S0[1-8]$'
),
ordered_teachers as (
  select
    id,
    row_number() over (order by username) as teacher_number
  from public.profiles
  where is_demo
    and role = 'teacher'
    and department = 'Computer Science'
    and username like 'demo.teacher.%'
)
insert into public.course_staff (course_id, profile_id)
select course.id, teacher.id
from ordered_courses course
join ordered_teachers teacher
  on teacher.teacher_number = mod(course.course_number - 1, 25) + 1
on conflict (course_id, profile_id) do nothing;

insert into public.enrollments (course_id, student_id, term)
select course.id, student.id, 'Fall 2026 (synthetic presentation)'
from public.courses course
join public.profiles student
  on student.program = course.program
  and student.semester = course.semester
  and student.department = course.department
where course.is_demo
  and course.code ~ '^DEMO-(CYS|SE|SET)-S0[1-8]$'
  and student.is_demo
  and student.role = 'student'
  and student.username like 'demo.%'
on conflict (course_id, student_id, term) do nothing;

commit;

select
  (
    select count(*)
    from public.courses
    where is_demo and code ~ '^DEMO-(CYS|SE|SET)-S0[1-8]$'
  ) as synthetic_courses,
  (
    select count(*)
    from public.course_staff assignment
    join public.courses course on course.id = assignment.course_id
    join public.profiles teacher on teacher.id = assignment.profile_id
    where course.is_demo
      and course.code ~ '^DEMO-(CYS|SE|SET)-S0[1-8]$'
      and teacher.is_demo
      and teacher.role = 'teacher'
  ) as teacher_assignments,
  (
    select count(*)
    from public.enrollments enrollment
    join public.courses course on course.id = enrollment.course_id
    join public.profiles student on student.id = enrollment.student_id
    where course.is_demo
      and course.code ~ '^DEMO-(CYS|SE|SET)-S0[1-8]$'
      and student.is_demo
      and student.role = 'student'
      and enrollment.term = 'Fall 2026 (synthetic presentation)'
  ) as student_enrollments;
