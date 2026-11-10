"""Which migration did a failed upgrade leave half applied?

MySQL and MariaDB cannot roll back DDL: every ALTER/CREATE commits on its
own. When a migration with several operations dies part way (a crash, a
killed process, an error in its third statement) the first operations stay
applied but the migration is not recorded in django_migrations. The next
`migrate` runs it again from the top and fails on "Duplicate column name" or
"Table ... already exists" (issues #128, #129). SQLite and PostgreSQL run
each migration in a transaction, so there it is applied completely or not
at all.

For the first unapplied migration of each app this compares each schema
operation with the live database:

    not_started          nothing of it is in the schema: just run migrate again
    applied_unrecorded   every checkable operation is in the schema: the
                         migration ran but was not recorded
    partial              some operations are in the schema, some are not
    unknown              only data / SQL operations, nothing to compare

and says what to do. Restoring the verified pre-upgrade backup is always
the safe answer; `--fake` is only offered when the schema shows the whole
migration already ran and it has no data steps.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import connection
from django.db.migrations import operations as ops
from django.db.migrations.executor import MigrationExecutor


@dataclass
class OpResult:
    description: str
    present: bool | None     # None: cannot tell from the schema


@dataclass
class Finding:
    app: str
    name: str
    state: str
    operations: list = field(default_factory=list)
    advice: str = ''

    @property
    def label(self):
        return f'{self.app}.{self.name}'


def _schema():
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
    return tables


def _columns(table):
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, table)}


def _constraint_names(table):
    with connection.cursor() as cursor:
        return set(connection.introspection.get_constraints(cursor, table).keys())


def _column_of(op_field, name):
    f = op_field.clone()
    f.set_attributes_from_name(name)
    return f.column, getattr(f, 'many_to_many', False)


def _check_operation(op, app, state, tables):
    """(description, present) for one operation, evaluated against `state`
    (the project state just before this operation)."""
    def table_for(model_name):
        try:
            return state.apps.get_model(app, model_name)._meta.db_table
        except LookupError:
            return None

    if isinstance(op, ops.CreateModel):
        table = (op.options or {}).get('db_table') or f'{app}_{op.name.lower()}'
        return f'create table {table}', table in tables
    if isinstance(op, ops.DeleteModel):
        table = table_for(op.name)
        return f'drop table {table}', (table not in tables) if table else None
    if isinstance(op, ops.AddField):
        table = table_for(op.model_name)
        column, m2m = _column_of(op.field, op.name)
        if m2m or not table or table not in tables:
            return f'add field {op.model_name}.{op.name}', None
        return f'add column {table}.{column}', column in _columns(table)
    if isinstance(op, ops.RemoveField):
        table = table_for(op.model_name)
        try:
            f = state.apps.get_model(app, op.model_name)._meta.get_field(op.name)
            column = f.column
        except Exception:
            return f'remove field {op.model_name}.{op.name}', None
        if not table or table not in tables or getattr(f, 'many_to_many', False):
            return f'remove field {op.model_name}.{op.name}', None
        return f'drop column {table}.{column}', column not in _columns(table)
    if isinstance(op, ops.RenameField):
        table = table_for(op.model_name)
        if not table or table not in tables:
            return f'rename field {op.model_name}.{op.old_name}', None
        try:
            old = state.apps.get_model(app, op.model_name)._meta.get_field(op.old_name)
        except Exception:
            return f'rename field {op.model_name}.{op.old_name}', None
        new_column = op.new_name if old.column == op.old_name else old.column
        cols = _columns(table)
        return f'rename column {table}.{old.column} -> {new_column}', (
            new_column in cols and old.column not in cols) if new_column != old.column else None
    if isinstance(op, ops.AlterModelTable):
        return f'rename table to {op.table}', (op.table in tables) if op.table else None
    if isinstance(op, (ops.AddIndex, ops.AddConstraint)):
        table = table_for(op.model_name)
        obj = getattr(op, 'index', None) or getattr(op, 'constraint', None)
        if not table or table not in tables or not getattr(obj, 'name', None):
            return f'add index/constraint on {op.model_name}', None
        return f'add index/constraint {obj.name}', obj.name in _constraint_names(table)
    if isinstance(op, (ops.RemoveIndex, ops.RemoveConstraint)):
        table = table_for(op.model_name)
        if not table or table not in tables:
            return f'remove index/constraint {op.name}', None
        return f'remove index/constraint {op.name}', op.name not in _constraint_names(table)
    if isinstance(op, (ops.RunPython, ops.RunSQL)):
        return f'{op.__class__.__name__} (data step, not visible in the schema)', None
    return f'{op.__class__.__name__} {getattr(op, "name", "") or getattr(op, "model_name", "")}'.strip(), None


def diagnose():
    """Findings for the first unapplied migration of every app that has one."""
    executor = MigrationExecutor(connection)
    loader = executor.loader
    # Walk the whole graph rather than executor.migration_plan(): the plan
    # treats a leaf that is recorded as applied as reached, so a gap before it
    # (a later migration recorded, an earlier one not; #128/#129) would be
    # missed.
    applied = set(loader.applied_migrations)
    order, seen_nodes = [], set()
    for leaf in loader.graph.leaf_nodes():
        for node in loader.graph.forwards_plan(leaf):
            if node not in seen_nodes:
                seen_nodes.add(node)
                order.append(node)
    plan = [(loader.graph.nodes[node], False) for node in order if node not in applied]
    tables = _schema()
    seen_apps, findings = set(), []
    for migration, backwards in plan:
        if backwards or migration.app_label in seen_apps:
            continue
        seen_apps.add(migration.app_label)
        node = (migration.app_label, migration.name)
        state = loader.project_state(node, at_end=False)
        results, has_data_step = [], False
        for op in migration.operations:
            desc, present = _check_operation(op, migration.app_label, state, tables)
            if isinstance(op, (ops.RunPython, ops.RunSQL)):
                has_data_step = True
            results.append(OpResult(desc, present))
            try:
                op.state_forwards(migration.app_label, state)
            except Exception:
                pass
        checkable = [r for r in results if r.present is not None]
        present = [r for r in checkable if r.present]
        if not checkable:
            st = 'unknown'
        elif not present:
            st = 'not_started'
        elif len(present) == len(checkable):
            st = 'applied_unrecorded'
        else:
            st = 'partial'
        findings.append(Finding(migration.app_label, migration.name, st, results,
                                _advice(migration.app_label, migration.name, st, has_data_step,
                                        connection.vendor)))
    return findings


def _advice(app, name, state, has_data_step, vendor):
    restore = ('Restore the verified pre-upgrade backup (`manage.py upgrade_status` shows it; '
               '`manage.py upgrade_restore <path>`), then apply again.')
    if state == 'not_started':
        return 'Nothing of it was applied. Re-running the upgrade (or `manage.py migrate`) continues from here.'
    if state == 'applied_unrecorded':
        if has_data_step:
            return ('Its schema changes are all present but it also has a data step that may not have run. '
                    + restore)
        return (f'Its schema changes are all present; only the record is missing. Either '
                f'`manage.py migrate {app} {name} --fake` then `manage.py migrate`, or (safer) ' + restore)
    if state == 'partial':
        txn = ' (MySQL/MariaDB do not roll back DDL)' if vendor == 'mysql' else ''
        return ('Half applied' + txn + ': some of its operations are in the database, some are not. '
                'Do not --fake it. ' + restore)
    return 'Only data steps; the schema cannot tell whether it ran. ' + restore


def report_lines(findings):
    lines = []
    if not findings:
        lines.append('All migrations are applied.')
        return lines
    for f in findings:
        lines.append(f'{f.label}: {f.state.replace("_", " ")}')
        for r in f.operations:
            mark = {True: 'present', False: 'missing', None: 'n/a'}[r.present]
            lines.append(f'    [{mark:7}] {r.description}')
        lines.append(f'    -> {f.advice}')
    return lines
