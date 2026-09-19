-- Schema tabella spese (piccolo, incollalo tutto in Supabase SQL Editor)
create table if not exists expenses (
  id bigint generated always as identity primary key,
  fingerprint text unique, persona text, data date, fonte text, canale text,
  descrizione text, importo_orig numeric, valuta text, importo_eur numeric,
  categoria text, tipo text, conta text);
alter table expenses enable row level security;
drop policy if exists exp_rw on expenses;
create policy exp_rw on expenses for all to authenticated
  using (is_app_user()) with check (is_app_user());
