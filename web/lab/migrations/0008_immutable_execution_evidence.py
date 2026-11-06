from django.db import migrations


def install(apps,schema_editor):
    if schema_editor.connection.vendor=='postgresql':
        schema_editor.execute('''CREATE FUNCTION lab_execution_evidence_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Execution evidence and outcome are immutable'; END; $$;''')
        for table in ('lab_executionevent','lab_outputartifact','lab_executionresult'):
            schema_editor.execute(f'CREATE TRIGGER immutable_execution_evidence BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION lab_execution_evidence_immutable();')


def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor=='postgresql':
        for table in ('lab_executionevent','lab_outputartifact','lab_executionresult'):
            schema_editor.execute(f'DROP TRIGGER IF EXISTS immutable_execution_evidence ON {table};')
        schema_editor.execute('DROP FUNCTION IF EXISTS lab_execution_evidence_immutable();')


class Migration(migrations.Migration):
    dependencies=[('lab','0007_alter_attempt_state_alter_job_state_executionresult_and_more')]
    operations=[migrations.RunPython(install,uninstall)]
