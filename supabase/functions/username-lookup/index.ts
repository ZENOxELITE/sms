import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

Deno.serve(async (request) => {
  if (request.method !== "POST") {
    return Response.json({ error: "Method not allowed" }, { status: 405 });
  }

  const expectedSecret = Deno.env.get("USERNAME_LOOKUP_SECRET");
  const suppliedSecret = request.headers.get("X-Username-Lookup-Secret");
  if (!expectedSecret || suppliedSecret !== expectedSecret) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  let payload: { username?: unknown };
  try {
    payload = await request.json();
  } catch {
    return Response.json({ error: "Invalid request" }, { status: 400 });
  }

  const username = typeof payload.username === "string"
    ? payload.username.trim().toLowerCase()
    : "";
  if (!/^[a-z0-9][a-z0-9._-]{2,31}$/.test(username)) {
    return Response.json({ error: "Invalid request" }, { status: 400 });
  }

  const url = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !serviceRoleKey) {
    return Response.json({ error: "Lookup is not configured" }, { status: 500 });
  }

  const supabase = createClient(url, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  const { data: profile, error: profileError } = await supabase
    .from("profiles")
    .select("id")
    .eq("username", username)
    .maybeSingle();
  if (profileError) {
    console.error("Username profile lookup failed", profileError.message);
    return Response.json({ error: "Lookup failed" }, { status: 500 });
  }
  if (!profile) {
    return Response.json({ email: null });
  }

  const { data: userResult, error: userError } = await supabase.auth.admin.getUserById(profile.id);
  if (userError) {
    console.error("Auth user lookup failed", userError.message);
    return Response.json({ error: "Lookup failed" }, { status: 500 });
  }

  return Response.json({ email: userResult.user.email ?? null });
});
