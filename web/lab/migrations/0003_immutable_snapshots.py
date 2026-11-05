from django.db import migrations


def install(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute("""CREATE FUNCTION lab_reject_snapshot_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Immutable snapshot: create a new identity'; END; $$;""")
        for table in ("lab_testversion", "lab_artifact"):
            schema_editor.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION lab_reject_snapshot_change();")
    elif vendor == "sqlite":
        # SQLite is quick-start only. DELETE is left available for Django's test flush.
        for table in ("lab_testversion", "lab_artifact"):
            schema_editor.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'Immutable snapshot'); END;")


def uninstall(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    for table in ("lab_testversion", "lab_artifact"):
        if vendor == "postgresql":
            schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table};")
        elif vendor == "sqlite":
            schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_immutable;")
    if vendor == "postgresql":
        schema_editor.execute("DROP FUNCTION IF EXISTS lab_reject_snapshot_change();")


class Migration(migrations.Migration):
    dependencies = [("lab", "0002_artifact_batch_job_run_serviceprincipal_servicetoken_and_more")]
    operations = [migrations.RunPython(install, uninstall)]
