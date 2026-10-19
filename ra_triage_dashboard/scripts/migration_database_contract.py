#!/usr/bin/env python3
"""Read schema, sequence state and effective role properties for cutover review.

Sequence reads are not MVCC snapshots. Exact sequence comparison is authoritative
only after the final write freeze, or against isolated restored databases.
"""
import argparse
import hashlib
import json
from pathlib import Path


def contract(conn):
    from psycopg import sql
    queries = {
        'columns': """SELECT c.relname,a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),
            a.attnotnull,pg_get_expr(d.adbin,d.adrelid),a.attidentity,a.attgenerated
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid
            LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m') AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY c.relname,a.attnum""",
        'constraints': """SELECT c.relname,k.conname,k.contype,pg_get_constraintdef(k.oid,true),k.convalidated
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname,k.conname""",
        'indexes': "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname",
        'triggers': """SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid,true),t.tgenabled
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname""",
        'views': "SELECT viewname,definition FROM pg_views WHERE schemaname='public' ORDER BY viewname",
        'functions': """SELECT p.proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid)
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind='f'
            ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)""",
        'sequence_definitions': """SELECT sequencename,data_type,start_value,min_value,max_value,increment_by,cycle,cache_size
            FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename""",
    }
    objects = {key: conn.execute(query).fetchall() for key, query in queries.items()}
    sequences = {}
    for row in objects['sequence_definitions']:
        sequences[row[0]] = conn.execute(sql.SQL('SELECT last_value,is_called FROM {}.{}').format(
            sql.Identifier('public'),sql.Identifier(row[0]))).fetchone()
    privileges = conn.execute("""SELECT c.relname,c.relkind,pg_get_userbyid(c.relowner)=current_user,
        CASE WHEN c.relkind='S' THEN has_sequence_privilege(c.oid,'USAGE') ELSE has_table_privilege(c.oid,'SELECT') END,
        CASE WHEN c.relkind='S' THEN has_sequence_privilege(c.oid,'UPDATE') ELSE has_table_privilege(c.oid,'INSERT,UPDATE,DELETE') END
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S') ORDER BY c.relname""").fetchall()
    role = conn.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolcanlogin,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
    encoded = json.dumps(objects,sort_keys=True,default=str,separators=(',',':')).encode()
    return {'schema_sha256':hashlib.sha256(encoded).hexdigest(), 'objects':objects,'sequences':sequences,
            'effective_relation_privileges':privileges, 'role_attributes':dict(zip(
                ['superuser','create_database','create_role','login','replication','bypass_rls'],role)),
            'sequence_scope':'Exact comparison requires frozen writers or isolated restored databases'}


if __name__ == '__main__':
    import psycopg
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url-file',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    with psycopg.connect(a.url_file.read_text().strip()) as conn:
        conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        result=contract(conn)
    a.output.write_text(json.dumps(result,indent=2,default=str))
    print(json.dumps({'schema_sha256':result['schema_sha256'],'objects':{k:len(v) for k,v in result['objects'].items()},
                      'sequences':len(result['sequences']),'role_attributes':result['role_attributes']}))
