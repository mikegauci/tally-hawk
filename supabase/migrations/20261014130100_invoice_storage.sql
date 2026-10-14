-- A private Supabase Storage bucket for uploaded invoice files. Skipped on plain Postgres
-- (local development and CI), where the API stores files on disk instead.
do $$
begin
    if exists (select 1 from pg_namespace where nspname = 'storage') then
        insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
        values (
            'invoices', 'invoices', false, 20971520,
            array['application/pdf', 'image/png', 'image/jpeg', 'image/webp']
        )
        on conflict (id) do nothing;
    end if;
end
$$;
