import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

Deno.serve(async (request) => {
  if (request.method !== "POST") {
    return Response.json({ error: "Method not allowed" }, { status: 405 });
  }

  const authorization = request.headers.get("Authorization") ?? "";
  const accessToken = authorization.startsWith("Bearer ")
    ? authorization.slice("Bearer ".length)
    : "";
  const url = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !serviceRoleKey || !accessToken) {
    return Response.json({ error: "Account creation is not configured" }, { status: 500 });
  }

  const supabase = createClient(url, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  const { data: authResult, error: authError } = await supabase.auth.getUser(accessToken);
  if (authError || !authResult.user) {
    return Response.json({ error: "A valid signed-in admin session is required" }, { status: 401 });
  }

  const { data: callerProfile, error: callerError } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", authResult.user.id)
    .maybeSingle();
  if (callerError) {
    console.error("Could not verify requesting profile", callerError.message);
    return Response.json({ error: "Could not verify administrator access" }, { status: 500 });
  }
  if (callerProfile?.role !== "admin") {
    return Response.json({ error: "Administrator access is required" }, { status: 403 });
  }

  let payload: Record<string, unknown>;
  try {
    payload = await request.json();
  } catch {
    return Response.json({ error: "Invalid request body" }, { status: 400 });
  }

  const email = typeof payload.email === "string" ? payload.email.trim().toLowerCase() : "";
  const password = typeof payload.password === "string" ? payload.password : "";
  const fullName = typeof payload.full_name === "string" ? payload.full_name.trim() : "";
  const username = typeof payload.username === "string" ? payload.username.trim().toLowerCase() : "";
  const role = typeof payload.role === "string" ? payload.role : "";
  const department = typeof payload.department === "string" ? payload.department.trim() : "";
  const studentNumber = typeof payload.student_number === "string"
    ? payload.student_number.trim()
    : "";

  if (
    !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ||
    password.length < 8 ||
    !fullName ||
    !/^[a-z0-9][a-z0-9._-]{2,31}$/.test(username) ||
    !["student", "teacher", "hod"].includes(role) ||
    !department
  ) {
    return Response.json({ error: "Check the account details and required fields" }, { status: 400 });
  }
  if (role === "student" && !studentNumber) {
    return Response.json({ error: "A student number is required for student accounts" }, { status: 400 });
  }

  const { data: departmentRow, error: departmentError } = await supabase
    .from("departments")
    .select("name")
    .eq("name", department)
    .maybeSingle();
  if (departmentError) {
    console.error("Could not verify department", departmentError.message);
    return Response.json({ error: "Could not verify the department" }, { status: 500 });
  }
  if (!departmentRow) {
    return Response.json({ error: "Choose a department in the campus department list" }, { status: 400 });
  }

  const { data: createdUser, error: createError } = await supabase.auth.admin.createUser({
    email,
    password,
    email_confirm: true,
  });
  if (createError || !createdUser.user) {
    console.error("Could not create Auth account", createError?.message ?? "No user returned");
    return Response.json({ error: "Could not create the login. Check for an existing email or password policy." }, { status: 400 });
  }

  const profile: Record<string, string> = {
    id: createdUser.user.id,
    full_name: fullName,
    username,
    role,
    department,
  };
  if (studentNumber) {
    profile.student_number = studentNumber;
  }

  const { error: profileError } = await supabase.from("profiles").insert(profile);
  if (profileError) {
    const { error: deleteError } = await supabase.auth.admin.deleteUser(createdUser.user.id);
    if (deleteError) {
      console.error("Failed to roll back Auth account after profile creation failed", deleteError.message);
    }
    console.error("Could not create profile", profileError.message);
    return Response.json({ error: "Could not create the campus profile. Check username and student-number uniqueness." }, { status: 400 });
  }

  return Response.json({ user_id: createdUser.user.id }, { status: 201 });
});
