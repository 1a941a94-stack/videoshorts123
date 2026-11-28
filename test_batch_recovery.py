import sqlite3
import unittest
from production_runs import init, create, summary, record, snapshot
from batch_worker import recover_tasks

class RecoveryTest(unittest.TestCase):
    def test_interrupted_tasks_reconciled_idempotently(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE clips(id INTEGER PRIMARY KEY, run_id INTEGER, status TEXT, attempts INTEGER, error TEXT, updated INTEGER)')
        init(db)
        run=create(db,4,snapshot('short'))
        other=create(db,1,snapshot('short'))
        db.executemany('INSERT INTO clips VALUES(?,?,?,?,NULL,0)',[(1,run,'running',1),(2,run,'running',3),(3,run,'done',1),(4,other,'running',1)])
        for cid in (1,2,3):
            record(db,run,cid,'running')
        recover_tasks(db,run)
        recover_tasks(db,run)
        self.assertEqual(summary(db,run)['counts'],{'pending':1,'failed':1,'done':1})
        self.assertEqual([tuple(r) for r in db.execute('SELECT id,status,attempts FROM clips ORDER BY id')],[(1,'pending',1),(2,'failed',3),(3,'done',1),(4,'running',1)])
