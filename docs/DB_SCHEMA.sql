-- Receiper SaaS PostgreSQL schema (reference)

create table if not exists users (
  id uuid primary key,
  email varchar(255) not null unique,
  password_hash varchar(255) not null,
  full_name varchar(120) not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists mobile_devices (
  id uuid primary key,
  user_id uuid not null references users(id) on delete cascade,
  device_name varchar(120) not null,
  platform varchar(40) not null default 'android',
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique (user_id, device_name)
);

create table if not exists pairing_codes (
  id uuid primary key,
  user_id uuid not null references users(id) on delete cascade,
  code varchar(12) not null unique,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  consumed_at timestamptz null,
  consumed_by_device_id uuid null references mobile_devices(id) on delete set null
);

create table if not exists receipts (
  id uuid primary key,
  user_id uuid not null references users(id) on delete cascade,
  device_id uuid null references mobile_devices(id) on delete set null,
  source_file_name varchar(255) not null,
  source_image_path varchar(500) not null,
  uploaded_at timestamptz not null default now(),

  kod varchar(20) not null default 'MS',
  hesap_kodu varchar(20) not null default 'MS',
  evrak_tarihi_text varchar(16) not null default '',
  evrak_tarihi date null,
  evrak_no varchar(80) not null default '',
  vergi_tc_no varchar(20) not null default '',
  gider_aciklama varchar(255) not null default '',
  kdv_orani double precision null,
  alinan_mal_masraf double precision null,
  ind_kdv double precision null,
  toplam double precision null,

  merchant varchar(160) not null default '',
  payment_type varchar(30) not null default '',
  receipt_time varchar(16) not null default '',
  raw_text text not null default ''
);

create index if not exists ix_receipts_user_uploaded_at on receipts(user_id, uploaded_at desc);
create index if not exists ix_pairing_codes_expires_at on pairing_codes(expires_at);

