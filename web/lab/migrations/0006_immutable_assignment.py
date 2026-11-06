from django.db import migrations


def install(apps,schema_editor):
    if schema_editor.connection.vendor=='postgresql':
        schema_editor.execute('''CREATE FUNCTION lab_assignment_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.job_id IS DISTINCT FROM OLD.job_id OR NEW.agent_id IS DISTINCT FROM OLD.agent_id
             OR NEW.epoch IS DISTINCT FROM OLD.epoch OR NEW.assignment IS DISTINCT FROM OLD.assignment
             OR NEW.claim_digest IS DISTINCT FROM OLD.claim_digest OR NEW.deadline IS DISTINCT FROM OLD.deadline THEN
            RAISE EXCEPTION 'Immutable assignment identity';
          END IF;
          RETURN NEW;
        END; $$;''')
        schema_editor.execute('CREATE TRIGGER lab_attempt_identity BEFORE UPDATE ON lab_attempt FOR EACH ROW EXECUTE FUNCTION lab_assignment_identity_guard();')


def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor=='postgresql':
        schema_editor.execute('DROP TRIGGER IF EXISTS lab_attempt_identity ON lab_attempt;')
        schema_editor.execute('DROP FUNCTION IF EXISTS lab_assignment_identity_guard();')


class Migration(migrations.Migration):
    dependencies=[('lab','0005_simulator_allocation')]
    operations=[migrations.RunPython(install,uninstall)]
