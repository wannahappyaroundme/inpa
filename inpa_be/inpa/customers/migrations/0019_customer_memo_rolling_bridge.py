from django.db import migrations


TRIM_FUNCTION = r"""
CREATE OR REPLACE FUNCTION inpa_trim_python_whitespace(p_value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $function$
    SELECT btrim(
        COALESCE(p_value, ''),
        U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
    )
$function$;
"""


RECONCILE_FUNCTION = r"""
CREATE OR REPLACE FUNCTION inpa_reconcile_customer_memo_bridge(
    p_customer_id bigint,
    p_owner_id bigint,
    p_memo text
) RETURNS void
LANGUAGE plpgsql
AS $function$
DECLARE
    v_memo_id bigint;
BEGIN
    IF inpa_trim_python_whitespace(p_memo) = '' THEN
        DELETE FROM customer_memo
        WHERE customer_id = p_customer_id
          AND is_legacy_mirror = TRUE;
        RETURN;
    END IF;

    SELECT id
      INTO v_memo_id
      FROM customer_memo
     WHERE customer_id = p_customer_id
       AND is_legacy_mirror = TRUE
     ORDER BY id
     LIMIT 1
     FOR UPDATE;

    IF FOUND THEN
        UPDATE customer_memo
           SET owner_id = p_owner_id,
               body = p_memo,
               revision = revision + CASE
                   WHEN body IS DISTINCT FROM p_memo THEN 1 ELSE 0 END,
               edited_at = CASE
                   WHEN body IS DISTINCT FROM p_memo THEN CURRENT_TIMESTAMP
                   ELSE edited_at END,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = v_memo_id
           AND (owner_id IS DISTINCT FROM p_owner_id
                OR body IS DISTINCT FROM p_memo);
        RETURN;
    END IF;

    SELECT id
      INTO v_memo_id
      FROM customer_memo
     WHERE customer_id = p_customer_id
       AND (
           source = 'legacy_migrated'
           OR (
               source = 'manual'
               AND inpa_trim_python_whitespace(body)
                   = inpa_trim_python_whitespace(p_memo)
           )
       )
     ORDER BY CASE WHEN source = 'legacy_migrated' THEN 0 ELSE 1 END, id
     LIMIT 1
     FOR UPDATE;

    IF FOUND THEN
        UPDATE customer_memo
           SET owner_id = p_owner_id,
               body = p_memo,
               is_legacy_mirror = TRUE,
               revision = revision + CASE
                   WHEN body IS DISTINCT FROM p_memo THEN 1 ELSE 0 END,
               edited_at = CASE
                   WHEN body IS DISTINCT FROM p_memo THEN CURRENT_TIMESTAMP
                   ELSE edited_at END,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = v_memo_id;
        RETURN;
    END IF;

    INSERT INTO customer_memo (
        owner_id,
        customer_id,
        source,
        body,
        is_legacy_mirror,
        occurred_at,
        edited_at,
        revision,
        created_at,
        updated_at
    ) VALUES (
        p_owner_id,
        p_customer_id,
        'legacy_migrated',
        p_memo,
        TRUE,
        NULL,
        NULL,
        1,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    );
END;
$function$;
"""


TRIGGER_FUNCTION = r"""
CREATE OR REPLACE FUNCTION inpa_customer_memo_bridge_trigger()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_owner_id bigint;
    v_memo text;
BEGIN
    SELECT owner_id, memo
      INTO v_owner_id, v_memo
      FROM customer
     WHERE id = NEW.id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    PERFORM inpa_reconcile_customer_memo_bridge(
        NEW.id,
        v_owner_id,
        v_memo
    );
    RETURN NULL;
END;
$function$;
"""


def install_rolling_bridge(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(TRIM_FUNCTION)
        cursor.execute(RECONCILE_FUNCTION)
        cursor.execute(TRIGGER_FUNCTION)
        cursor.execute("""
            CREATE CONSTRAINT TRIGGER customer_memo_rolling_bridge
            AFTER INSERT OR UPDATE OF memo ON customer
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW
            EXECUTE FUNCTION inpa_customer_memo_bridge_trigger()
        """)
        # CREATE TRIGGER keeps a conflicting table lock until this atomic
        # migration commits. Writes completed before the lock are reconciled
        # here; blocked writes resume with the deferred bridge installed.
        cursor.execute("""
            SELECT inpa_reconcile_customer_memo_bridge(id, owner_id, memo)
            FROM customer
            ORDER BY id
        """)


def uninstall_rolling_bridge(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            'DROP TRIGGER IF EXISTS customer_memo_rolling_bridge ON customer')
        cursor.execute(
            'DROP FUNCTION IF EXISTS inpa_customer_memo_bridge_trigger()')
        cursor.execute(
            'DROP FUNCTION IF EXISTS '
            'inpa_reconcile_customer_memo_bridge(bigint, bigint, text)')
        cursor.execute(
            'DROP FUNCTION IF EXISTS inpa_trim_python_whitespace(text)')


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0018_customermemo_mirror_constraint'),
    ]

    operations = [
        migrations.RunPython(
            install_rolling_bridge,
            uninstall_rolling_bridge,
        ),
    ]
