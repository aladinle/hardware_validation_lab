"""Durable local dedup ledger. Never the platform reservation authority."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import sys

from contracts.journal_v1 import canonical, checksum, parse_delivery
from contracts.runner_v1 import Limits, strict_json
from contracts.v1 import ContractError, identifier
from .process_identity import identity, inspect
from .runner import bounded_read, run_can, safe_path


class JournalError(ValueError):
    pass


SCHEMA = '''
CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1), agent_id TEXT NOT NULL, project_id TEXT NOT NULL,
 platform TEXT NOT NULL, quota INTEGER NOT NULL, max_records INTEGER NOT NULL);
CREATE TABLE executions (
 execution_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, request_hash TEXT NOT NULL, packet TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('ACCEPTED','LAUNCH_INTENT','STARTING','RUNNING','UNCERTAIN','COMPLETE','ACKNOWLEDGED')),
 supervisor TEXT NOT NULL, worker TEXT, launch_intents INTEGER NOT NULL DEFAULT 0 CHECK(launch_intents IN (0,1)),
 spawn_records INTEGER NOT NULL DEFAULT 0 CHECK(spawn_records IN (0,1)), reserved_bytes INTEGER NOT NULL,
 completion_hash TEXT, result TEXT, ack_source TEXT, reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE device_owners (device_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL REFERENCES executions(execution_id));
'''


def now():
    return datetime.now(timezone.utc)


def durable_write(path, data):
    with Path(path).open('xb') as stream:
        if os.name != 'nt':
            os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(Path(path).parent)


def sync_directory(path):
    # Windows has no portable directory-fsync through Python. File flushes and
    # SQLite FULL are used; process-restart tests are not power-cut guarantees.
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def initialize(root, agent_id, project_id, *, quota_mb=256, max_records=1000):
    agent_id, project_id = identifier(agent_id), identifier(project_id)
    if type(quota_mb) is not int or not 64 <= quota_mb <= 1024 or type(max_records) is not int or not 1 <= max_records <= 1000:
        raise JournalError('Invalid bounded journal capacity.')
    root = safe_path(root)
    if str(root).startswith('\\\\'):
        raise JournalError('Use a private local filesystem, not a network share.')
    root.mkdir(mode=0o700, exist_ok=False)
    (root/'spool').mkdir(mode=0o700)
    durable_write(root/'journal.sqlite3', b'')
    connection = sqlite3.connect(root/'journal.sqlite3', isolation_level=None)
    try:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute('PRAGMA application_id=1213615156')
        connection.execute('PRAGMA user_version=1')
        connection.executescript(SCHEMA)
        connection.execute('INSERT INTO meta VALUES(1,?,?,?,?,?)', (agent_id,project_id,sys.platform,quota_mb*1024*1024,max_records))
    finally:
        connection.close()
    sync_directory(root)
    return Journal(root)


class Journal:
    def __init__(self, root):
        self.root = safe_path(root)
        self.db = self.root/'journal.sqlite3'
        self.spool = self.root/'spool'
        if not self.db.is_file() or not self.spool.is_dir():
            raise JournalError('Journal missing; never recreate a ledger over existing evidence.')
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM meta WHERE id=1').fetchone()
            if row is None or row['platform'] != sys.platform:
                raise JournalError('Journal identity/platform mismatch.')
            self.meta = dict(row)

    @contextmanager
    def connect(self, *, write=False):
        connection = None
        try:
            for path in (self.db, Path(str(self.db)+'-wal'), Path(str(self.db)+'-shm'), self.spool):
                safe_path(path)
            connection = sqlite3.connect(self.db.as_uri()+'?mode=rw', uri=True, timeout=5, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA busy_timeout=5000')
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('PRAGMA max_page_count=32768')
            if connection.execute('PRAGMA application_id').fetchone()[0] != 1213615156 or connection.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise JournalError('Unsupported or corrupt journal schema.')
            if connection.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                raise JournalError('Journal durability configuration unavailable.')
            if write:
                connection.execute('BEGIN IMMEDIATE')
            yield connection
            if write:
                connection.commit()
        except sqlite3.Error as exc:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            raise JournalError('Local journal unavailable; no new launch is permitted.') from exc
        except BaseException:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    def row(self, execution_id):
        execution_id = identifier(execution_id)
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM executions WHERE execution_id=?', (execution_id,)).fetchone()
        if row is None:
            raise JournalError('Unknown local execution.')
        return dict(row)

    def status(self, execution_id):
        row = self.row(execution_id)
        return {key:row[key] for key in ('execution_id','epoch','state','request_hash','launch_intents','spawn_records','completion_hash','ack_source','reason')} | {
            'source':strict_json(row['packet'])['source'], 'result':strict_json(row['result']) if row['result'] else None,
            'worker':strict_json(row['worker']) if row['worker'] else None,
            'spool_retained':(self.spool/row['execution_id']).is_dir(), 'dispatch_available':False}

    def accept(self, packet, *, _server=False):
        packet = parse_delivery(packet,source='server_simulated_assignment' if _server else 'local_journal_demo')
        if packet['agent_id'] != self.meta['agent_id'] or packet['project_id'] != self.meta['project_id']:
            raise JournalError('Delivery is outside this journal identity.')
        request_hash = checksum(packet)
        limits = Limits(**packet['limits'])
        reserve = 2*1024*1024 + 20*1024*1024 + limits.disk_bytes + 3*limits.stdout_bytes + limits.stderr_bytes + 131072
        with self.connect(write=True) as connection:
            old = connection.execute('SELECT * FROM executions WHERE execution_id=?',(packet['execution_id'],)).fetchone()
            if old:
                if old['request_hash'] != request_hash or old['epoch'] != packet['epoch']:
                    raise JournalError('Execution ID/epoch was already accepted with different content.')
                return packet, False
            if datetime.fromisoformat(packet['deadline']) <= now():
                raise JournalError('New delivery deadline expired.')
            count, reserved = connection.execute('SELECT count(*),coalesce(sum(reserved_bytes),0) FROM executions').fetchone()
            if count >= self.meta['max_records'] or reserved + reserve > self.meta['quota']:
                raise JournalError('Journal/spool capacity reached; retained evidence will not be evicted.')
            connection.execute('INSERT INTO executions(execution_id,epoch,request_hash,packet,state,supervisor,reserved_bytes,created_at) VALUES(?,?,?,?,?,?,?,?)',
                               (packet['execution_id'],packet['epoch'],request_hash,canonical(packet),'ACCEPTED',canonical(identity()),reserve,now().isoformat()))
            try:
                for device in packet['device_ids']:
                    connection.execute('INSERT INTO device_owners VALUES(?,?)',(device,packet['execution_id']))
            except sqlite3.IntegrityError as exc:
                raise JournalError('Overlapping local device scope is active or uncertain.') from exc
        return packet, True

    def transition(self, execution_id, state, *, worker=None):
        previous = {'LAUNCH_INTENT':'ACCEPTED','STARTING':'LAUNCH_INTENT','RUNNING':'STARTING'}[state]
        with self.connect(write=True) as connection:
            row = connection.execute('SELECT * FROM executions WHERE execution_id=?',(execution_id,)).fetchone()
            if row is None or row['state'] != previous or strict_json(row['supervisor']) != identity():
                raise JournalError('Local launch ownership/state changed.')
            connection.execute('UPDATE executions SET state=?,worker=coalesce(?,worker),launch_intents=launch_intents+?,spawn_records=spawn_records+? WHERE execution_id=?',
                               (state,canonical(worker) if worker else None,int(state=='LAUNCH_INTENT'),int(state=='STARTING'),execution_id))

    def inventory(self, execution_id, *, flush=False):
        folder = safe_path(self.spool/identifier(execution_id))
        files, total = {}, 0
        for path in folder.rglob('*'):
            safe_path(path)
            if path.is_dir():
                continue
            if path == folder/'completion.json':
                continue
            if not path.is_file() or len(files) >= 128:
                raise JournalError('Unexpected spool entry/count.')
            size = path.stat().st_size
            total += size
            if total > self.meta['quota']:
                raise JournalError('Spool exceeds capacity.')
            with path.open('r+b' if flush else 'rb') as stream:
                digest = hashlib.file_digest(stream,'sha256').hexdigest()
                if flush:
                    os.fsync(stream.fileno())
            files[path.relative_to(folder).as_posix()] = {'size':size,'sha256':digest}
        return files, total

    def read_completion(self, execution_id):
        execution_id = identifier(execution_id)
        row = self.row(execution_id)
        raw = bounded_read(self.spool/execution_id/'completion.json',65536)
        sealed = strict_json(raw)
        if not isinstance(sealed,dict) or set(sealed) != {'schema_version','execution_id','epoch','request_hash','result','files'}:
            raise JournalError('Invalid completion seal.')
        if type(sealed['schema_version']) is not int or sealed['schema_version'] != 1 or type(sealed['epoch']) is not int or (sealed['execution_id'],sealed['epoch'],sealed['request_hash']) != (row['execution_id'],row['epoch'],row['request_hash']):
            raise JournalError('Completion identity conflict.')
        files, total = self.inventory(execution_id)
        if not files or sealed['files'] != files:
            raise JournalError('Retained spool checksum conflict.')
        packet = strict_json(row['packet'])
        if files.get('delivery.json',{}).get('sha256') != row['request_hash']:
            raise JournalError('Retained delivery differs from accepted context.')
        for reference in packet['inputs']:
            if files.get('inputs/'+reference['role']+'.hex') != {'size':reference['size'],'sha256':reference['sha256']}:
                raise JournalError('Retained input differs from accepted artifact.')
        if files.get('inputs/plugin.whl',{}).get('sha256') != packet['manifest']['plugin_package_sha256']:
            raise JournalError('Retained package differs from accepted version.')
        result = sealed['result']
        if not isinstance(result,dict) or result.get('termination_confirmed') is not True or result.get('outcome') not in {'PASS','FAIL','ERROR','TIMEOUT','CANCELLED'}:
            raise JournalError('Completion does not prove terminated local work.')
        if result != strict_json(bounded_read(self.spool/execution_id/'run/run.json',32768)):
            raise JournalError('Sealed result differs from the retained runner record.')
        digest = hashlib.sha256(raw).hexdigest()
        if row['completion_hash'] and row['completion_hash'] != digest:
            raise JournalError('Completion replay conflict.')
        return sealed, digest, total + len(raw)

    def commit_completion(self, execution_id, *, recovering=False):
        execution_id = identifier(execution_id)
        sealed, digest, total = self.read_completion(execution_id)
        with self.connect(write=True) as connection:
            row = connection.execute('SELECT * FROM executions WHERE execution_id=?',(execution_id,)).fetchone()
            if row['state'] in ('COMPLETE','ACKNOWLEDGED'):
                if row['completion_hash'] != digest:
                    raise JournalError('Completion conflict.')
                return
            owner_state = inspect(strict_json(row['supervisor']))
            if recovering and owner_state == 'ALIVE':
                raise JournalError('Cannot take over an active supervisor.')
            if not recovering and strict_json(row['supervisor']) != identity():
                raise JournalError('Completion supervisor mismatch.')
            connection.execute('UPDATE executions SET state=?,completion_hash=?,result=?,reserved_bytes=?,reason=? WHERE execution_id=?',
                               ('COMPLETE',digest,canonical(sealed['result']),total,'DURABLE_COMPLETION',execution_id))
            if sealed['result'].get('quarantine_required') is False:
                connection.execute('DELETE FROM device_owners WHERE execution_id=?',(execution_id,))

    def reconcile(self, execution_id):
        execution_id = identifier(execution_id)
        row = self.row(execution_id)
        if row['state'] in ('COMPLETE','ACKNOWLEDGED'):
            self.read_completion(execution_id)
            return self.status(execution_id)
        if inspect(strict_json(row['supervisor'])) == 'ALIVE':
            return self.status(execution_id)
        try:
            self.commit_completion(execution_id,recovering=True)
        except (OSError,ContractError,JournalError):
            with self.connect(write=True) as connection:
                connection.execute("UPDATE executions SET state='UNCERTAIN',reason='RECONCILIATION_REQUIRED' WHERE execution_id=? AND state NOT IN ('COMPLETE','ACKNOWLEDGED')",(execution_id,))
        return self.status(execution_id)

    def acknowledge_local(self, execution_id, epoch, completion_hash):
        """Trusted local demonstration only; no backend upload is claimed."""
        execution_id = identifier(execution_id)
        row = self.row(execution_id)
        if strict_json(row['packet'])['source']!='local_journal_demo':
            raise JournalError('Server assignments require a verified backend evidence acknowledgement, not a demo ACK.')
        _, digest, _ = self.read_completion(execution_id)
        with self.connect(write=True) as connection:
            current = connection.execute('SELECT * FROM executions WHERE execution_id=?',(execution_id,)).fetchone()
            if type(epoch) is not int or epoch != row['epoch'] or completion_hash != digest or current['state'] not in ('COMPLETE','ACKNOWLEDGED'):
                raise JournalError('Stale or conflicting local acknowledgement.')
            connection.execute("UPDATE executions SET state='ACKNOWLEDGED',ack_source='local_demo' WHERE execution_id=?",(execution_id,))
        return self.status(execution_id)

    def acknowledge_server(self, reply, origin):
        from contracts.agents_v1 import schema
        schema(reply,{'execution_id','epoch','completion_sha256','evidence_acknowledged','leases_released','hardware_ready'})
        if reply['evidence_acknowledged'] is not True or reply['leases_released'] is not False or reply['hardware_ready'] is not False or type(reply['epoch']) is not int:
            raise JournalError('Invalid backend evidence acknowledgement.')
        row=self.row(identifier(reply['execution_id']))
        _,value,_=self.read_completion(row['execution_id'])
        with self.connect(write=True) as connection:
            binding=connection.execute('SELECT origin FROM server_binding WHERE id=1').fetchone()
            if not binding or binding['origin']!=origin or strict_json(row['packet'])['source']!='server_simulated_assignment' or row['state'] not in ('COMPLETE','ACKNOWLEDGED') or (reply['epoch'],reply['completion_sha256'])!=(row['epoch'],value):
                raise JournalError('Backend ACK differs from accepted identity/completion.')
            connection.execute("UPDATE executions SET state='ACKNOWLEDGED',ack_source='authenticated_backend' WHERE execution_id=?",(row['execution_id'],))
        return self.status(row['execution_id'])

    def deliver(self, value, expected, actual, wheel, *, _checkpoint=None, _server=False):
        checkpoint = _checkpoint if _checkpoint is not None else lambda stage, info: None
        packet = parse_delivery(value,source='server_simulated_assignment' if _server else 'local_journal_demo')
        if packet['agent_id'] != self.meta['agent_id'] or packet['project_id'] != self.meta['project_id']:
            raise JournalError('Delivery is outside this journal identity.')
        with self.connect() as connection:
            exists = connection.execute('SELECT 1 FROM executions WHERE execution_id=?',(packet['execution_id'],)).fetchone()
        prepared = {}
        if not exists:
            # Validate before taking local ownership. Replays need no original
            # source files; their accepted spool is the authority for evidence.
            for reference in packet['inputs']:
                raw = bounded_read(expected if reference['role']=='expected' else actual,1024*1024)
                if len(raw) != reference['size'] or hashlib.sha256(raw).hexdigest() != reference['sha256']:
                    raise JournalError('Local input differs from declared reference.')
                prepared[reference['role']+'.hex'] = raw
            from workloads.registry import verify_wheel, MAX_WHEEL_BYTES
            if verify_wheel(wheel) != packet['manifest']['plugin_package_sha256']:
                raise JournalError('Package differs from accepted version.')
            prepared['plugin.whl'] = bounded_read(wheel,MAX_WHEEL_BYTES)
            if hashlib.sha256(prepared['plugin.whl']).hexdigest() != packet['manifest']['plugin_package_sha256']:
                raise JournalError('Package changed during validation.')
        packet, accepted = self.accept(packet,_server=_server)
        execution_id = packet['execution_id']
        if not accepted:
            return {'newly_accepted':False, **self.reconcile(execution_id)}
        checkpoint('accepted',{'execution_id':execution_id})
        folder = self.spool/execution_id
        try:
            folder.mkdir(mode=0o700)
            durable_write(folder/'delivery.json',canonical(packet).encode())
            staged = folder/'inputs'
            staged.mkdir(mode=0o700)
            for name,raw in prepared.items():
                durable_write(staged/name,raw)
            if datetime.fromisoformat(packet['deadline']) <= now():
                raise JournalError('Delivery expired during preparation.')
            self.transition(execution_id,'LAUNCH_INTENT')
            checkpoint('launch_intent',{'execution_id':execution_id})

            def observe(event, process):
                if event == 'spawned':
                    worker = identity(process.pid)
                    checkpoint('spawned_before_record',worker)
                    self.transition(execution_id,'STARTING',worker=worker)
                    checkpoint('spawned_recorded',worker)
                elif event == 'gate':
                    self.transition(execution_id,'RUNNING')
                    checkpoint('gate_recorded',{'execution_id':execution_id})
                elif event == 'launched':
                    checkpoint('launched',{'execution_id':execution_id})

            result = run_can(packet['manifest'],staged/'expected.hex',staged/'actual.hex',staged/'plugin.whl',folder/'run',
                             parameters=packet['parameters'],limits=Limits(**packet['limits']),_observer=observe)
            if result['termination_confirmed'] is not True:
                raise JournalError('Runner termination remains uncertain.')
            files, _ = self.inventory(execution_id,flush=True)
            sealed = {'schema_version':1,'execution_id':execution_id,'epoch':packet['epoch'],
                      'request_hash':checksum(packet),'result':result,'files':files}
            durable_write(folder/'completion.json',canonical(sealed).encode())
            checkpoint('completion_sealed',{'execution_id':execution_id})
            self.commit_completion(execution_id)
            checkpoint('completion_committed',{'execution_id':execution_id})
        except (Exception,KeyboardInterrupt):
            # Never infer stopped work or retry from a missing PID/result.
            with self.connect(write=True) as connection:
                connection.execute("UPDATE executions SET state='UNCERTAIN',reason='RECONCILIATION_REQUIRED' WHERE execution_id=? AND state NOT IN ('COMPLETE','ACKNOWLEDGED')",(execution_id,))
        return {'newly_accepted':True, **self.status(execution_id)}
