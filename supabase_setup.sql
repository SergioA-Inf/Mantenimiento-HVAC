-- =============================================================================
-- Script de configuracion inicial para Supabase
-- Sistema de Gestion de Mantenimiento HVAC - Terminal de Cruceros de Amador
--
-- COMO USAR:
-- 1. Entra a tu proyecto en https://supabase.com
-- 2. Ve a "Storage" (menu izquierdo) > "New bucket" y crea uno llamado
--    exactamente: evidencias  (marca la opcion "Public bucket" - el aviso
--    que aparece es normal, solo advierte que las fotos se podran LEER via
--    URL publica; la SUBIDA queda controlada por las politicas de este script)
-- 3. Ve a "SQL Editor" (menu izquierdo) > "New query"
-- 4. Pega todo este archivo y dale "Run" (puede ser antes o despues del
--    paso 2, no importa el orden)
--
-- Este script se puede correr mas de una vez sin problema (usa "if not
-- exists" y "drop ... if exists" antes de crear cada cosa).
-- =============================================================================

create table if not exists equipos (
  tag text primary key,
  categoria text,
  especificaciones text,
  modelo text,
  tiene_vfd boolean default false,
  zona text,
  nivel text,
  estado_operativo text,
  ultimo_mantenimiento text,
  proximo_mantenimiento text
);

create table if not exists modelos (
  modelo_id text primary key,
  nombre text,
  componentes text,
  parametros text,
  umbral_dias integer,
  preventivo_json text,
  correctivo_json text
);

create table if not exists ordenes (
  orden_id text primary key,
  fecha_creacion text,
  equipos_json text,
  estado text,
  tecnico_asignado text
);

create table if not exists reportes (
  reporte_id text primary key,
  orden_id text,
  tag_equipo text,
  categoria text,
  modelo_id text,
  modelo_referencia text,
  zona text,
  nivel text,
  tecnico text,
  fecha_servicio text,
  hora_inicio text,
  hora_fin text,
  estado_final text,
  sintomas_detectados text,
  tareas_completadas integer,
  tareas_totales integer,
  checklist_json text,
  observaciones text,
  proximo_mantenimiento text,
  evidencia_urls text,
  firma_url text,
  fecha_registro text
);

-- Si ya habias corrido una version anterior de este script (sin la columna
-- firma_url), esta linea la agrega sin afectar los datos que ya tengas.
alter table reportes add column if not exists firma_url text;

-- -----------------------------------------------------------------------------
-- GRANTS explicitos para el Data API.
--
-- Desde 2026, los proyectos nuevos de Supabase (segun cuando se creo el tuyo
-- y si dejaste marcada "Automatically expose new tables" o no) YA NO exponen
-- una tabla nueva a la API automaticamente: hace falta un GRANT explicito de
-- Postgres, o la API devuelve "permission denied" (codigo 42501) sin
-- importar que tan permisivas sean las politicas de RLS de abajo - el grant
-- se revisa ANTES que las politicas de RLS.
--
-- Estas lineas cubren ambos escenarios (proyecto viejo o nuevo, con o sin
-- "Automatically expose new tables" marcado), asi que el script funciona
-- igual sin importar esa eleccion.
-- -----------------------------------------------------------------------------
grant usage on schema public to anon, authenticated;
grant select, insert, update, delete on equipos to anon, authenticated;
grant select, insert, update, delete on modelos to anon, authenticated;
grant select, insert, update, delete on ordenes to anon, authenticated;
grant select, insert, update, delete on reportes to anon, authenticated;

-- -----------------------------------------------------------------------------
-- Seguridad (RLS): estas politicas permiten leer/escribir a cualquiera que
-- tenga tu URL y llave "anon" de Supabase (que solo viven en tu secrets.toml,
-- nunca en el codigo publico). Es un punto de partida razonable para una
-- herramienta interna sin login de usuarios. Si mas adelante agregas
-- autenticacion de usuarios, puedes reemplazar "using (true)" por reglas mas
-- estrictas (por ejemplo, solo usuarios autenticados).
-- -----------------------------------------------------------------------------
alter table equipos enable row level security;
alter table modelos enable row level security;
alter table ordenes enable row level security;
alter table reportes enable row level security;

drop policy if exists "Permitir todo (lectura/escritura)" on equipos;
drop policy if exists "Permitir todo (lectura/escritura)" on modelos;
drop policy if exists "Permitir todo (lectura/escritura)" on ordenes;
drop policy if exists "Permitir todo (lectura/escritura)" on reportes;

create policy "Permitir todo (lectura/escritura)" on equipos
  for all using (true) with check (true);
create policy "Permitir todo (lectura/escritura)" on modelos
  for all using (true) with check (true);
create policy "Permitir todo (lectura/escritura)" on ordenes
  for all using (true) with check (true);
create policy "Permitir todo (lectura/escritura)" on reportes
  for all using (true) with check (true);

-- -----------------------------------------------------------------------------
-- Storage (fotos de evidencia): marcar el bucket "evidencias" como Publico en
-- el dashboard SOLO habilita la LECTURA por URL publica (para que el PDF
-- pueda descargar la foto). La SUBIDA de archivos es un permiso aparte: por
-- defecto Supabase Storage no permite subir nada a ningun bucket hasta que
-- exista una politica de RLS explicita para la operacion INSERT sobre
-- storage.objects. Sin esto, el bucket puede verse "publico" en el
-- dashboard pero la app recibira un error de RLS al intentar subir una foto.
-- -----------------------------------------------------------------------------
drop policy if exists "Subir evidencias" on storage.objects;
drop policy if exists "Actualizar evidencias" on storage.objects;
drop policy if exists "Leer evidencias" on storage.objects;

create policy "Subir evidencias" on storage.objects
  for insert to anon, authenticated
  with check (bucket_id = 'evidencias');

create policy "Actualizar evidencias" on storage.objects
  for update to anon, authenticated
  using (bucket_id = 'evidencias')
  with check (bucket_id = 'evidencias');

create policy "Leer evidencias" on storage.objects
  for select to anon, authenticated
  using (bucket_id = 'evidencias');
