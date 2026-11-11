import json
import uuid

from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient


def uid():
    return str(uuid.uuid4())


class ApiTests(TestCase):
    def setUp(self):
        self.c = APIClient(HTTP_X_KERN="1")

    def make_doc(self, **kw):
        r = self.c.post("/api/documents", kw, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def sync(self, doc, upserts=(), deletes=()):
        return self.c.post(
            f"/api/documents/{doc['id']}/blocks/sync",
            {"upserts": list(upserts), "deletes": list(deletes)},
            format="json",
        )

    def test_guard_header_required(self):
        r = APIClient().post("/api/documents", {"title": "x"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_sync_nesting_and_sanitising(self):
        doc = self.make_doc(title="Alpha")
        a, b = uid(), uid()
        r = self.sync(doc, [
            {"id": b, "parent": a, "position": 1, "type": "bullet", "html": "child"},
            {"id": a, "parent": None, "position": 1, "type": "paragraph",
             "html": 'hi <script>alert(1)</script><b onclick="x()">bold</b>'},
        ])
        self.assertEqual(r.status_code, 200, r.content)
        blocks = {x["id"]: x for x in self.c.get(f"/api/documents/{doc['id']}").json()["blocks"]}
        self.assertEqual(blocks[b]["parent"], a)
        self.assertEqual(blocks[a]["html"], "hi <b>bold</b>")

    def test_sync_rejects_cycles_and_rolls_back(self):
        doc = self.make_doc(title="Alpha")
        a, b = uid(), uid()
        r = self.sync(doc, [
            {"id": a, "parent": b, "position": 1, "type": "paragraph", "html": "a"},
            {"id": b, "parent": a, "position": 1, "type": "paragraph", "html": "b"},
        ])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.get(f"/api/documents/{doc['id']}").json()["blocks"], [])

    def test_delete_keeps_children_moved_in_same_sync(self):
        doc = self.make_doc(title="Alpha")
        a, b = uid(), uid()
        self.sync(doc, [
            {"id": a, "parent": None, "position": 1, "type": "paragraph", "html": "a"},
            {"id": b, "parent": a, "position": 1, "type": "paragraph", "html": "b"},
        ])
        r = self.sync(doc, [{"id": b, "parent": None, "position": 1, "type": "paragraph",
                             "html": "b"}], [a])
        self.assertEqual(r.status_code, 200)
        blocks = self.c.get(f"/api/documents/{doc['id']}").json()["blocks"]
        self.assertEqual([x["id"] for x in blocks], [b])

    def test_backlinks_follow_edits(self):
        target = self.make_doc(title="Target")
        source = self.make_doc(title="Source")
        blk = uid()
        html = f'see <a data-ref="doc:{target["id"]}" href="/doc/{target["id"]}">Target</a>'
        self.sync(source, [{"id": blk, "parent": None, "position": 1, "type": "paragraph",
                            "html": html}])
        bl = self.c.get(f"/api/documents/{target['id']}/backlinks").json()
        self.assertEqual(bl[0]["doc"]["id"], source["id"])
        self.assertEqual(bl[0]["items"][0]["block"], blk)
        refs = self.c.get(f"/api/documents/{source['id']}").json()["refs"]
        self.assertEqual(refs[f"doc:{target['id']}"]["title"], "Target")
        self.sync(source, [{"id": blk, "parent": None, "position": 1, "type": "paragraph",
                            "html": "no link"}])
        self.assertEqual(self.c.get(f"/api/documents/{target['id']}/backlinks").json(), [])

    def test_search_and_trash(self):
        doc = self.make_doc(title="Quantum notes")
        self.sync(doc, [{"id": uid(), "parent": None, "position": 1, "type": "paragraph",
                         "html": "Entanglement is <b>spooky</b>"}])
        r = self.c.get("/api/search", {"q": "spook"}).json()
        self.assertEqual(r["results"][0]["kind"], "block")
        self.assertIn("\x01spooky\x02", r["results"][0]["snippet"])
        self.assertEqual(self.c.get("/api/search", {"q": "quant"}).json()["results"][0]["kind"], "doc")
        self.c.post(f"/api/documents/{doc['id']}/trash")
        self.assertEqual(self.c.get("/api/search", {"q": "spook"}).json()["results"], [])
        self.c.post(f"/api/documents/{doc['id']}/restore")
        self.assertEqual(len(self.c.get("/api/search", {"q": "spook"}).json()["results"]), 1)
        self.c.post(f"/api/documents/{doc['id']}/trash")
        self.assertEqual(self.c.delete(f"/api/documents/{doc['id']}").status_code, 204)
        self.assertEqual(self.c.get("/api/search", {"q": "quant"}).json()["results"], [])

    def test_move_prevents_cycles_and_orders(self):
        a = self.make_doc(title="A")
        b = self.make_doc(title="B", parent=a["id"])
        c = self.make_doc(title="C")
        r = self.c.post(f"/api/documents/{a['id']}/move", {"parent": b["id"]}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.c.post(f"/api/documents/{c['id']}/move", {"parent": None, "index": 0},
                        format="json")
        self.assertEqual(r.json()["order"], [c["id"], a["id"]])

    def test_tags_and_properties(self):
        doc = self.make_doc(title="Ada")
        tag = self.c.post("/api/tags", {"name": "Person"}, format="json").json()
        prop = self.c.post("/api/properties", {"name": "Email", "type": "text", "tag": tag["id"]},
                           format="json").json()
        self.c.patch(f"/api/documents/{doc['id']}", {"tags": [tag["id"]]}, format="json")
        r = self.c.put(f"/api/documents/{doc['id']}/properties/{prop['id']}",
                       {"value": "ada@example.org"}, format="json").json()
        self.assertEqual(r["values"][prop["id"]], "ada@example.org")
        payload = self.c.get(f"/api/documents/{doc['id']}").json()
        self.assertEqual(payload["properties"]["defs"][0]["name"], "Email")
        self.assertEqual(self.c.get("/api/search", {"q": "ada@example"}).json()["results"][0]["id"],
                         doc["id"])
        detail = self.c.get(f"/api/tags/{tag['id']}").json()
        self.assertEqual(detail["documents"][0]["id"], doc["id"])

    def test_duplicate_copies_blocks_and_children(self):
        a = self.make_doc(title="A")
        self.make_doc(title="Child", parent=a["id"])
        self.sync(a, [{"id": uid(), "parent": None, "position": 1, "type": "paragraph",
                       "html": "body"}])
        copy = self.c.post(f"/api/documents/{a['id']}/duplicate").json()
        self.assertEqual(copy["title"], "A (copy)")
        self.assertEqual(len(self.c.get(f"/api/documents/{copy['id']}").json()["blocks"]), 1)
        tree = self.c.get("/api/tree").json()
        self.assertEqual(len([d for d in tree if d["parent"] == copy["id"]]), 1)


class DatabaseTests(TestCase):
    def setUp(self):
        self.c = APIClient(HTTP_X_KERN="1")

    def db(self, title):
        r = self.c.post("/api/databases", {"title": title}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def prop(self, db, **kw):
        r = self.c.post("/api/properties", {"database": db["database"]["id"], **kw}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def entry(self, db, title, values=None):
        r = self.c.post(f"/api/databases/{db['database']['id']}/entries",
                        {"title": title, "values": values or {}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def rows(self, db):
        data = self.c.get(f"/api/databases/{db['database']['id']}").json()
        return {r["title"]: r["values"] for r in data["rows"]}

    def test_relation_rollup_formula(self):
        projects = self.db("Projects")
        tasks = self.db("Tasks")
        rel = self.prop(tasks, name="Project", type="relation",
                        config={"target": projects["database"]["id"]})
        reverse = rel["config"]["reverse"]
        self.assertTrue(reverse)
        hours = self.prop(tasks, name="Hours", type="number")
        done = self.prop(tasks, name="Done", type="boolean")
        p = self.entry(projects, "Kern")
        self.entry(tasks, "Write", {rel["id"]: [p["id"]], hours["id"]: 3, done["id"]: True})
        self.entry(tasks, "Test", {rel["id"]: [p["id"]], hours["id"]: 2})
        total = self.prop(projects, name="Total", type="rollup",
                          config={"relation": reverse, "target": hours["id"], "fn": "sum"})
        pct = self.prop(projects, name="Pct", type="rollup",
                        config={"relation": reverse, "target": done["id"], "fn": "percent_checked"})
        f = self.prop(projects, name="Label", type="formula",
                      config={"expr": 'prop("Name") + ": " + prop("Total") + "h" + if(prop("Pct") >= 50, " ✓", "")'})
        row = self.rows(projects)["Kern"]
        self.assertEqual(len(row[reverse]), 2)
        self.assertEqual(row[total["id"]], 5)
        self.assertEqual(row[pct["id"]], 50)
        self.assertEqual(row[f["id"]], "Kern: 5h ✓")
        bad = self.prop(projects, name="Bad", type="formula", config={"expr": "1 +"})
        self.assertIn("error", self.rows(projects)["Kern"][bad["id"]])

    def test_relation_sync_and_delete_scrub(self):
        a, b = self.db("A"), self.db("B")
        rel = self.prop(a, name="Links", type="relation", config={"target": b["database"]["id"]})
        x = self.entry(b, "x")
        y = self.entry(a, "y")
        self.c.put(f"/api/documents/{y['id']}/properties/{rel['id']}", {"value": [x["id"]]}, format="json")
        self.assertEqual(self.rows(b)["x"][rel["config"]["reverse"]], [y["id"]])
        self.c.put(f"/api/documents/{y['id']}/properties/{rel['id']}", {"value": []}, format="json")
        self.assertFalse(self.rows(b)["x"].get(rel["config"]["reverse"]))
        self.c.put(f"/api/documents/{y['id']}/properties/{rel['id']}", {"value": [x["id"]]}, format="json")
        self.c.post(f"/api/documents/{x['id']}/trash")
        self.assertEqual(self.rows(a)["y"][rel["id"]], [])
        self.c.delete(f"/api/documents/{x['id']}")
        from notes.models import PropertyValue
        self.assertIsNone(PropertyValue.objects.get(document_id=y["id"], definition_id=rel["id"]).value)

    def test_trash_database_trashes_entries(self):
        a = self.db("A")
        e = self.entry(a, "e")
        self.c.post(f"/api/documents/{a['database']['page']}/trash")
        self.assertEqual(self.c.get(f"/api/documents/{e['id']}").json()["document"]["trashed_at"] is not None, True)
        self.assertEqual([d["id"] for d in self.c.get("/api/trash").json()], [a["database"]["page"]])
        self.c.post(f"/api/documents/{a['database']['page']}/restore")
        self.assertIsNone(self.c.get(f"/api/documents/{e['id']}").json()["document"]["trashed_at"])

    def test_templates(self):
        tag = self.c.post("/api/tags", {"name": "Meeting"}, format="json").json()
        tpl = self.c.post("/api/templates", {"title": "Meeting notes", "template_tag": tag["id"]},
                          format="json").json()
        self.c.post(f"/api/documents/{tpl['id']}/blocks/sync", {"upserts": [
            {"id": uid(), "parent": None, "position": 1, "type": "h2", "html": "Agenda"}]}, format="json")
        self.assertEqual(self.c.get("/api/search", {"q": "agenda"}).json()["results"], [])
        doc = self.c.post("/api/documents", {"template": tpl["id"]}, format="json").json()
        self.assertEqual(doc["title"], "Meeting notes")
        self.assertFalse(doc["is_template"])
        other = self.c.post("/api/documents", {"title": "Standup"}, format="json").json()
        r = self.c.patch(f"/api/documents/{other['id']}", {"tags": [tag["id"]]}, format="json").json()
        self.assertEqual(r["templates_applied"], [tpl["id"]])
        blocks = self.c.get(f"/api/documents/{other['id']}").json()["blocks"]
        self.assertEqual([b["html"] for b in blocks], ["Agenda"])
        tree_ids = [d["id"] for d in self.c.get("/api/tree").json()]
        self.assertNotIn(tpl["id"], tree_ids)

    def test_duplicate_database(self):
        a = self.db("A")
        n = self.prop(a, name="N", type="number")
        self.entry(a, "one", {n["id"]: 1})
        page = a["database"]["page"]
        copy = self.c.post(f"/api/documents/{page}/duplicate").json()
        self.assertTrue(copy["database"])
        data = self.c.get(f"/api/databases/{copy['database']}").json()
        self.assertEqual(data["rows"][0]["title"], "one")
        self.assertEqual(list(data["rows"][0]["values"].values()), [1])

    def test_graph(self):
        a = self.c.post("/api/documents", {"title": "A"}, format="json").json()
        b = self.c.post("/api/documents", {"title": "B", "parent": a["id"]}, format="json").json()
        self.c.post(f"/api/documents/{a['id']}/blocks/sync", {"upserts": [
            {"id": uid(), "parent": None, "position": 1, "type": "embed", "html": "",
             "props": {"kind": "doc", "target": b["id"]}}]}, format="json")
        g = self.c.get("/api/graph").json()
        kinds = sorted(e["kind"] for e in g["edges"])
        self.assertEqual(kinds, ["child", "ref"])


class FormulaTests(TestCase):
    def ev(self, expr, props=None):
        from notes.formula import Evaluator, compile_formula
        return Evaluator(lambda n: (props or {})[n]).run(compile_formula(expr))

    def test_basics(self):
        self.assertEqual(self.ev("1 + 2 * 3"), 7)
        self.assertEqual(self.ev("2 ^ 3 ^ 2"), 512)
        self.assertEqual(self.ev('if(1 > 2, "a", "b")'), "b")
        self.assertEqual(self.ev('prop("x") > 3 ? "big" : "small"', {"x": 5}), "big")
        self.assertEqual(self.ev('concat("a", round(2.456, 1))'), "a2.5")
        self.assertEqual(self.ev('not true or length("abc") == 3'), True)
        self.assertEqual(self.ev('formatDate(dateAdd("2026-01-31", 1, "months"), "YYYY-MM-DD")'), "2026-02-28")
        self.assertEqual(self.ev('dateBetween("2026-03-10", "2026-03-01", "days")'), 9)

    def test_errors(self):
        from notes.formula import FormulaError
        for bad in ["1 +", "foo", "1 / 0", 'prop(x)', "nope(1)", "(1"]:
            with self.assertRaises(FormulaError):
                self.ev(bad)


class FsrsTests(TestCase):
    def test_intervals_grow_and_lapse(self):
        import datetime as dt
        from notes import fsrs
        now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        c = fsrs.State()
        c, _ = fsrs.review(c, fsrs.GOOD, now)  # new -> learning step
        self.assertEqual(c.state, "learning")
        now += dt.timedelta(minutes=10)
        c, ivl1 = fsrs.review(c, fsrs.GOOD, now)
        self.assertEqual(c.state, "review")
        now = c.due
        c, ivl2 = fsrs.review(c, fsrs.GOOD, now)
        self.assertGreater(ivl2, ivl1)
        p = fsrs.preview(c, c.due)
        self.assertLess(p[2], p[3])
        self.assertLess(p[3], p[4])
        s_before = c.stability
        c, _ = fsrs.review(c, fsrs.AGAIN, c.due)
        self.assertEqual((c.state, c.lapses), ("relearning", 1))
        self.assertLess(c.stability, s_before)


class LearningTests(TestCase):
    def setUp(self):
        self.c = APIClient(HTTP_X_KERN="1")
        self.doc = self.c.post("/api/documents", {"title": "Bio"}, format="json").json()

    def sync(self, *blocks, deletes=()):
        r = self.c.post(f"/api/documents/{self.doc['id']}/blocks/sync",
                        {"upserts": list(blocks), "deletes": list(deletes)}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_block_syntax_makes_cards(self):
        a, b, c, kid = uid(), uid(), uid(), uid()
        r = self.sync(
            {"id": a, "parent": None, "position": 1, "type": "paragraph", "html": "Capital of France :: Paris"},
            {"id": b, "parent": None, "position": 2, "type": "paragraph", "html": "{{Mitochondria}} make {{ATP}}"},
            {"id": c, "parent": None, "position": 3, "type": "paragraph", "html": "Osmosis ;;"},
            {"id": kid, "parent": c, "position": 1, "type": "bullet", "html": "water through a membrane"},
        )
        self.assertEqual(r["block_cards"], {a: 1, b: 2, c: 2})
        cards = self.c.get("/api/cards").json()
        self.assertEqual(cards["total"], 5)
        cloze = [x for x in cards["cards"] if x["kind"] == "cloze" and x["ordinal"] == 1][0]
        self.assertIn('[…]', cloze["front"])
        self.assertIn("Mitochondria", cloze["front"])
        self.assertIn('class="cloze shown">ATP', cloze["back"])
        concept = [x for x in cards["cards"] if x["kind"] == "concept"]
        self.assertEqual(sorted(x["front"] for x in concept), ["Osmosis", "water through a membrane"])
        # Removing the syntax keeps history but stops reviews; restoring brings it back.
        self.sync({"id": a, "parent": None, "position": 1, "type": "paragraph", "html": "Capital of France"})
        self.assertEqual(self.c.get("/api/cards").json()["total"], 4)
        self.sync({"id": a, "parent": None, "position": 1, "type": "paragraph", "html": "Capital of France :: Paris!"})
        self.assertEqual(self.c.get("/api/cards").json()["total"], 5)
        self.assertEqual(self.c.get("/api/search", {"q": "mitochondria", "kind": "card"}).json()["results"][0]["kind"], "card")

    def test_queue_review_undo_and_limits(self):
        self.c.patch("/api/settings", {"flashcards": {"new_per_day": 2}}, format="json")
        for i in range(3):
            self.c.post("/api/notes", {"kind": "basic", "front": f"Q{i}", "back": f"A{i}"}, format="json")
        q = self.c.get("/api/cards/queue").json()
        self.assertEqual(q["counts"]["new"], 2)
        card = q["card"]
        self.assertEqual(set(card["intervals"].keys()), {"1", "2", "3", "4"})
        r = self.c.post(f"/api/cards/{card['id']}/review", {"rating": 4}, format="json").json()
        self.assertEqual(r["state"], "review")
        q = self.c.get("/api/cards/queue").json()
        self.assertEqual(q["counts"]["new"], 1)
        undone = self.c.post("/api/cards/undo").json()
        self.assertEqual(undone["state"], "new")
        stats = self.c.get("/api/cards/stats").json()
        self.assertEqual(stats["reviewed_today"], 0)
        self.assertEqual(stats["counts"]["new"], 3)

    def test_occlusion_and_validation(self):
        r = self.c.post("/api/notes", {"kind": "cloze", "front": "no gaps"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/api/notes", {"kind": "occlusion", "image": "/media/x.png", "regions": [
            {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1, "label": "Heart"},
            {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.1, "label": "Lung"}]}, format="json")
        self.assertEqual(r.status_code, 201)
        note = self.c.get(f"/api/notes/{r.json()['id']}").json()
        self.assertEqual([c["ordinal"] for c in note["cards"]], [0, 1])


class TaskTests(TestCase):
    def setUp(self):
        self.c = APIClient(HTTP_X_KERN="1")

    def test_views_and_recurrence(self):
        t1 = self.c.post("/api/tasks", {"title": "Inbox thing"}, format="json").json()
        t2 = self.c.post("/api/tasks", {"title": "Pay rent", "due": "2026-11-10",
                                        "recurrence": {"freq": "month", "interval": 1}}, format="json").json()
        self.c.post("/api/tasks", {"title": "Later", "due": "2026-12-01", "priority": 3}, format="json")
        view = lambda v: [t["title"] for t in self.c.get("/api/tasks", {"view": v, "today": "2026-11-10"}).json()]
        self.assertEqual(view("inbox"), ["Inbox thing"])
        self.assertEqual(view("today"), ["Pay rent"])
        self.assertEqual(view("upcoming"), ["Later"])
        r = self.c.patch(f"/api/tasks/{t2['id']}", {"done": True, "today": "2026-11-10"}, format="json").json()
        self.assertEqual((r["done"], r["due"]), (False, "2026-12-10"))
        self.c.patch(f"/api/tasks/{t1['id']}", {"done": True}, format="json")
        self.assertEqual(view("completed"), ["Inbox thing"])
        s = self.c.get("/api/tasks/summary", {"today": "2026-11-10"}).json()
        self.assertEqual((s["inbox"], s["today"]), (0, 0))

    def test_checklist_block_sync(self):
        doc = self.c.post("/api/documents", {"title": "Plan"}, format="json").json()
        bid = uid()
        url = f"/api/documents/{doc['id']}/blocks/sync"
        self.c.post(url, {"upserts": [{"id": bid, "parent": None, "position": 1, "type": "todo",
                                       "html": "Write report", "props": {"checked": False}}]}, format="json")
        t = self.c.post("/api/tasks", {"block": bid}, format="json").json()
        self.assertEqual((t["title"], t["document"]), ("Write report", doc["id"]))
        # Ticking the block completes the task…
        self.c.post(url, {"upserts": [{"id": bid, "parent": None, "position": 1, "type": "todo",
                                       "html": "Write report", "props": {"checked": True, "task": t["id"]}}]}, format="json")
        self.assertTrue(self.c.get(f"/api/tasks/{t['id']}").json()["done"])
        # …and reopening the task un-ticks the block.
        self.c.patch(f"/api/tasks/{t['id']}", {"done": False}, format="json")
        block = self.c.get(f"/api/documents/{doc['id']}").json()["blocks"][0]
        self.assertFalse(block["props"]["checked"])
        # A recurring task un-ticks its block itself and reports the change.
        self.c.patch(f"/api/tasks/{t['id']}", {"due": "2026-11-10", "recurrence": {"freq": "week"}}, format="json")
        r = self.c.post(url, {"upserts": [{"id": bid, "parent": None, "position": 1, "type": "todo",
                                           "html": "Write report", "props": {"checked": True, "task": t["id"]}}]}, format="json").json()
        self.assertEqual(r["patched"][0]["props"]["checked"], False)
        self.assertFalse(self.c.get(f"/api/tasks/{t['id']}").json()["done"])

    def test_entry_task_marks_entry_done(self):
        db = self.c.post("/api/databases", {"title": "Projects"}, format="json").json()
        st = self.c.post("/api/properties", {"database": db["database"]["id"], "name": "Status", "type": "status"},
                         format="json").json()
        e = self.c.post(f"/api/databases/{db['database']['id']}/entries", {"title": "Ship"}, format="json").json()
        t = self.c.post("/api/tasks", {"title": "Finish Ship", "document": e["id"]}, format="json").json()
        self.c.patch(f"/api/tasks/{t['id']}", {"done": True}, format="json")
        rows = self.c.get(f"/api/databases/{db['database']['id']}").json()["rows"]
        self.assertEqual(rows[0]["values"][st["id"]], "done")


class DataTests(TestCase):
    def setUp(self):
        self.c = APIClient(HTTP_X_KERN="1")
        import tempfile
        from django.conf import settings
        self.media = tempfile.mkdtemp()
        self._old_media = settings.MEDIA_ROOT
        settings.MEDIA_ROOT = self.media

    def tearDown(self):
        import shutil
        from django.conf import settings
        settings.MEDIA_ROOT = self._old_media
        shutil.rmtree(self.media, ignore_errors=True)

    def upload(self, files):
        from django.core.files.uploadedfile import SimpleUploadedFile
        payload = {"files": [SimpleUploadedFile(n, d) for n, d in files], "paths": [n for n, _ in files]}
        r = self.c.post("/api/import", payload, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def test_markdown_folder_import_and_export(self):
        md_a = b"---\ntags: [science, notes]\n---\n# Cells\n\nThe **cell** is the unit of life. See [[Atoms]].\n\n- Parts\n  - Nucleus\n  - [x] Membrane\n\n```py\nprint(1)\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nWhat is ATP :: energy currency\n"
        md_b = b"# Atoms\n\nSmall #physics things.\n"
        s = self.upload([("Biology/Cells.md", md_a), ("Biology/Atoms.md", md_b)])
        self.assertEqual(s["skipped"], [])
        tree = {d["title"]: d for d in self.c.get("/api/tree").json()}
        self.assertEqual(tree["Cells"]["parent"], tree["Biology"]["id"])
        cells = self.c.get(f"/api/documents/{tree['Cells']['id']}").json()
        types = [b["type"] for b in cells["blocks"]]
        self.assertIn("code", types)
        self.assertIn("table", types)
        self.assertIn("todo", types)
        first = [b for b in cells["blocks"] if b["type"] == "paragraph"][0]["html"]
        self.assertIn("<b>cell</b>", first)
        self.assertIn(f'data-ref="doc:{tree["Atoms"]["id"]}"', first)
        nested = [b for b in cells["blocks"] if b["html"] == "Nucleus"][0]
        self.assertEqual([b for b in cells["blocks"] if b["id"] == nested["parent"]][0]["html"], "Parts")
        self.assertEqual(len(cells["document"]["tags"]), 2)
        self.assertEqual(sum(cells["block_cards"].values()), 1)
        # Export round trip
        r = self.c.get(f"/api/export/document/{tree['Cells']['id']}", {"as": "md"})
        text = r.content.decode()
        self.assertIn("**cell**", text)
        self.assertIn("[[Atoms]]", text)
        self.assertIn("- [x] Membrane", text)
        r = self.c.get(f"/api/export/document/{tree['Biology']['id']}", {"as": "md", "children": "1"})
        self.assertEqual(r["Content-Type"], "application/zip")
        import io, zipfile
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        self.assertIn("Biology/Cells.md", names)
        html = self.c.get(f"/api/export/document/{tree['Cells']['id']}", {"as": "html"}).content.decode()
        self.assertIn("<table>", html)

    def test_html_opml_csv_import(self):
        html = b"<html><head><title>Recipe</title></head><body><h1>Recipe</h1><p>Mix <em>well</em>.</p><ul><li>Flour<ul><li>Sifted</li></ul></li></ul></body></html>"
        opml = b'<?xml version="1.0"?><opml version="2.0"><head><title>Plan</title></head><body><outline text="Phase 1"><outline text="Research"/></outline></body></opml>'
        csvb = b"Name,Pages,Read,Genre\nDune,612,yes,SF\nEmma,400,no,Classic\nIt,1100,no,Horror\nUlysses,700,yes,Classic\nNeuromancer,270,yes,SF\n"
        s = self.upload([("recipe.html", html), ("plan.opml", opml), ("books.csv", csvb)])
        self.assertEqual((s["pages"], s["databases"]), (2, 1))
        tree = {d["title"]: d for d in self.c.get("/api/tree").json()}
        recipe = self.c.get(f"/api/documents/{tree['Recipe']['id']}").json()["blocks"]
        self.assertEqual(recipe[0]["html"], "Mix <i>well</i>.")
        plan = self.c.get(f"/api/documents/{tree['Plan']['id']}").json()["blocks"]
        self.assertEqual(len(plan), 2)
        db = self.c.get(f"/api/databases/{tree['books']['database']}").json()
        types = {p["name"]: p["type"] for p in db["properties"]}
        self.assertEqual(types, {"Pages": "number", "Read": "boolean", "Genre": "select"})
        csv_out = self.c.get(f"/api/export/database/{tree['books']['database']}").content.decode("utf-8-sig")
        self.assertIn("Dune,SF,612,true".split(",")[0], csv_out)
        self.assertEqual(csv_out.splitlines()[0], "Name,Pages,Read,Genre")

    def test_json_round_trip(self):
        a = self.c.post("/api/documents", {"title": "Root"}, format="json").json()
        b = self.c.post("/api/documents", {"title": "Child", "parent": a["id"]}, format="json").json()
        self.c.post(f"/api/documents/{a['id']}/blocks/sync", {"upserts": [
            {"id": uid(), "parent": None, "position": 1, "type": "paragraph",
             "html": f'go <a class="ref" data-ref="doc:{b["id"]}" href="/doc/{b["id"]}" contenteditable="false">Child</a>'}]}, format="json")
        data = self.c.get(f"/api/export/document/{a['id']}", {"as": "json", "children": "1"}).content
        s = self.upload([("export.json", data)])
        self.assertEqual(s["pages"], 2)
        roots = [d for d in self.c.get("/api/tree").json() if d["title"] == "Root"]
        self.assertEqual(len(roots), 2)
        new_root = [d for d in roots if d["id"] != a["id"]][0]
        new_child = [d for d in self.c.get("/api/tree").json() if d["parent"] == new_root["id"]][0]
        html = self.c.get(f"/api/documents/{new_root['id']}").json()["blocks"][0]["html"]
        self.assertIn(new_child["id"], html)

    def test_anki_round_trip(self):
        self.c.post("/api/notes", {"kind": "basic", "front": "Q1", "back": "A1"}, format="json")
        self.c.post("/api/notes", {"kind": "cloze", "front": "{{Paris}} is in {{France}}"}, format="json")
        apkg = self.c.get("/api/export/cards", {"as": "apkg"}).content
        from notes.models import CardNote
        CardNote.objects.all().delete()
        s = self.upload([("deck.apkg", apkg)])
        self.assertEqual(s["cards"], 3)
        kinds = sorted(CardNote.objects.values_list("kind", flat=True))
        self.assertEqual(kinds, ["basic", "cloze"])
        self.assertIn("{{c2::France}}", CardNote.objects.get(kind="cloze").front)

    def test_versions_and_conflicts(self):
        from notes.models import DocVersion
        doc = self.c.post("/api/documents", {"title": "V"}, format="json").json()
        bid = uid()
        url = f"/api/documents/{doc['id']}/blocks/sync"
        r = self.c.post(url, {"upserts": [{"id": bid, "parent": None, "position": 1, "type": "paragraph", "html": "one"}]}, format="json").json()
        base = r["version"]
        v = self.c.post(f"/api/documents/{doc['id']}/versions").json()
        self.c.post(url, {"upserts": [{"id": bid, "parent": None, "position": 1, "type": "paragraph", "html": "two"}], "base": base}, format="json")
        # A second client still holding the old base gets a conflict instead of overwriting.
        r = self.c.post(url, {"upserts": [{"id": bid, "parent": None, "position": 1, "type": "paragraph", "html": "stale"}], "base": base}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["blocks"][0]["html"], "two")
        r = self.c.post(url, {"upserts": [{"id": bid, "parent": None, "position": 1, "type": "paragraph", "html": "forced"}], "base": base, "force": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.c.post(f"/api/versions/{v['id']}/restore")
        blocks = self.c.get(f"/api/documents/{doc['id']}").json()["blocks"]
        self.assertEqual(blocks[0]["html"], "one")
        self.assertTrue(DocVersion.objects.filter(reason="restore").exists())


class BackupTests(TransactionTestCase):
    """Outside a test transaction: SQLite cannot copy a database mid-transaction."""

    def setUp(self):
        self.c = APIClient(HTTP_X_KERN="1")
        import tempfile
        from django.conf import settings
        self.media = tempfile.mkdtemp()
        self._old_media = settings.MEDIA_ROOT
        settings.MEDIA_ROOT = self.media

    def tearDown(self):
        import shutil
        from django.conf import settings
        settings.MEDIA_ROOT = self._old_media
        shutil.rmtree(self.media, ignore_errors=True)

    def test_library_and_backup(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = self.c.post("/api/files", {"file": SimpleUploadedFile("pic.png", b"\x89PNG....", "image/png")}, format="multipart").json()
        doc = self.c.post("/api/documents", {"title": "Pics"}, format="json").json()
        self.c.post(f"/api/documents/{doc['id']}/blocks/sync", {"upserts": [
            {"id": uid(), "parent": None, "position": 1, "type": "image", "html": "", "props": {"url": f["url"]}}]}, format="json")
        lib = self.c.get("/api/library").json()
        self.assertEqual(lib[0]["used_in"][0]["title"], "Pics")
        import tempfile
        from unittest import mock
        from pathlib import Path
        from notes import backup
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(backup, "BACKUP_DIR", Path(tmp)):
            b = self.c.post("/api/backups").json()
            self.assertTrue(b["name"].startswith("kern-"))
            manifest = backup.validate(Path(tmp) / b["name"])
            self.assertEqual(manifest["counts"]["files"], 1)
            import zipfile
            self.assertIn("media/" + f["url"].split("/media/")[1], zipfile.ZipFile(Path(tmp) / b["name"]).namelist())
        st = self.c.get("/api/storage").json()
        self.assertEqual(st["counts"]["files"], 1)


class AITests(TestCase):
    def setUp(self):
        self.c = APIClient(HTTP_X_KERN="1")

    def test_config_hides_key_and_requires_setup(self):
        r = self.c.post("/api/ai/write", {"prompt": "hi"}, format="json")
        self.assertEqual((r.status_code, r.json()["setup"]), (409, True))
        cfg = self.c.put("/api/ai/config", {"provider": "anthropic", "api_key": "sk-ant-test-123456789"}, format="json").json()
        self.assertTrue(cfg["configured"])
        self.assertEqual((cfg["model"], cfg["key_hint"]), ("claude-opus-5-5", "6789"))
        self.assertNotIn("sk-ant", json.dumps(self.c.get("/api/ai/config").json()))
        self.assertNotIn("ai_secret", self.c.get("/api/settings").json())
        self.c.patch("/api/settings", {"ai_secret": {"api_key": "evil"}}, format="json")
        self.assertEqual(self.c.get("/api/ai/config").json()["key_hint"], "6789")

    def test_tasks_with_mocked_model(self):
        from unittest import mock
        self.c.put("/api/ai/config", {"provider": "anthropic", "api_key": "sk-ant-test-123456789"}, format="json")
        doc = self.c.post("/api/documents", {"title": "Cells"}, format="json").json()
        reply = '```json\n[{"kind": "basic", "front": "What makes ATP?", "back": "Mitochondria"},' \
                ' {"kind": "cloze", "front": "DNA lives in the {{nucleus}}.", "back": ""}, {"kind": "basic", "front": "bad"}]\n```'
        with mock.patch("notes.ai.complete", return_value=reply) as m:
            r = self.c.post("/api/ai/cards", {"doc": doc["id"], "count": 5}, format="json").json()
        self.assertEqual([c["kind"] for c in r["cards"]], ["basic", "cloze"])
        self.assertIn("Current page: Cells", m.call_args[0][1])
        with mock.patch("notes.ai.complete", return_value='{"title": "Meeting", "icon": "🗓️", "markdown": "## Agenda\\n- [ ] item"}'):
            t = self.c.post("/api/ai/template", {"prompt": "meeting notes"}, format="json").json()
        self.assertTrue(t["is_template"])
        blocks = self.c.get(f"/api/documents/{t['id']}").json()["blocks"]
        self.assertEqual([b["type"] for b in blocks], ["h2", "todo"])
        with mock.patch("notes.ai.complete", return_value="Hello **world**"):
            w = self.c.post("/api/ai/write", {"prompt": "greet", "doc": doc["id"]}, format="json").json()
        self.assertEqual(w["markdown"], "Hello **world**")


class AgentTests(TestCase):
    def setUp(self):
        self.c = APIClient(HTTP_X_KERN="1")

    def test_tools_edit_pages_boards_and_tasks(self):
        from notes import agent
        from notes.models import Block, Document, DocVersion
        run = agent.Run()
        call = lambda name, **a: json.loads(r) if (r := agent.execute(run, name, a)).startswith(("{", "[")) else r
        page = call("create_page", title="Biology", markdown="# Cells\n- Mitochondria\n  - makes ATP\n- [ ] read ch. 2\nATP :: energy")
        self.assertIn("id", page)
        doc = Document.objects.get(id=page["id"])
        self.assertEqual([b.type for b in Block.objects.filter(document=doc, parent=None).order_by("position")],
                         ["h1", "bullet", "todo", "paragraph"])
        self.assertEqual(doc.card_notes.count(), 1)
        read = call("read_page", page_id=page["id"])
        self.assertIn("Mitochondria", read["content"])
        mito = Block.objects.get(document=doc, html="Mitochondria")
        self.assertIn(f"[{mito.id}]", read["content"])
        call("add_to_page", page_id=page["id"], markdown="- Nucleus", after_block_id=str(mito.id))
        roots = [b.html for b in Block.objects.filter(document=doc, parent=None).order_by("position")]
        self.assertEqual(roots[1:3], ["Mitochondria", "Nucleus"])
        self.assertEqual(DocVersion.objects.filter(document=doc, reason="ai").count(), 1)
        call("replace_block", block_id=str(mito.id), markdown="- Mitochondrion")
        self.assertFalse(Block.objects.filter(id=mito.id).exists())
        # Kanban: create, add a card, move it.
        board = call("create_database", title="Homework", preset="kanban")
        entry = call("add_entry", database_id=board["database_id"], title="Essay", values={"Status": "To do", "Tags": ["english"]})
        self.assertNotIn("warnings", entry)
        res = call("update_entry", entry_id=entry["entry_id"], values={"Status": "Done"})
        self.assertNotIn("warnings", res)
        rows = call("query_database", database_id=board["database_id"])
        self.assertEqual(rows[0]["values"]["Status"], "Done")
        bad_status = call("update_entry", entry_id=entry["entry_id"], values={"Status": "Nope"})
        self.assertIn("warnings", bad_status)
        # Tasks and errors.
        t = call("create_task", title="Study", due="2030-01-02", priority=2)
        call("update_task", task_id=t["task_id"], done=True)
        self.assertIn("error", call("read_page", page_id=str(uuid.uuid4())))
        self.assertIn("error", call("nope"))
        call("trash_page", page_id=page["id"])
        self.assertIsNotNone(Document.objects.get(id=page["id"]).trashed_at)
        self.assertTrue(len(run.actions) >= 6)

    def test_chat_turn_with_mocked_openai_provider(self):
        from unittest import mock
        self.c.put("/api/ai/config", {"provider": "ollama", "model": "llama"}, format="json")
        chat = self.c.post("/api/chats", {}, format="json").json()
        replies = iter([
            {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "create_page", "arguments": json.dumps({"title": "Physics", "kind": "group", "icon": "⚛️"})}}]}}]},
            {"choices": [{"message": {"content": "Created your Physics group."}}]},
        ])
        sent = []

        class Res:
            def __init__(self, data): self.data = data
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(self.data).encode()

        def fake(req, timeout=None):
            sent.append(json.loads(req.data))
            return Res(next(replies))

        with mock.patch("urllib.request.urlopen", fake):
            r = self.c.post(f"/api/chats/{chat['id']}/message", {"text": "make a physics group"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        msgs = r.json()["messages"]
        self.assertEqual(msgs[-1]["text"], "Created your Physics group.")
        self.assertEqual(msgs[-1]["actions"][0]["verb"], "Created group")
        self.assertEqual(sent[1]["messages"][-1]["role"], "tool")
        listing = self.c.get("/api/chats").json()
        self.assertEqual(listing[0]["title"], "make a physics group")
        self.assertEqual(self.c.delete(f"/api/chats/{chat['id']}").status_code, 204)

    def test_chat_needs_setup(self):
        chat = self.c.post("/api/chats", {}, format="json").json()
        r = self.c.post(f"/api/chats/{chat['id']}/message", {"text": "hi"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()["setup"])


class GroupTests(TestCase):
    def setUp(self):
        self.c = APIClient(HTTP_X_KERN="1")

    def test_group_with_calendar_and_agenda(self):
        import datetime as dt
        g = self.c.post("/api/documents", {"title": "Chem 101", "kind": "group"}, format="json").json()
        self.assertEqual(g["kind"], "group")
        cal = self.c.post("/api/databases", {"title": "Exams", "parent": g["id"], "preset": "calendar"}, format="json").json()
        self.assertEqual({v["type"] for v in cal["views"]}, {"calendar", "table"})
        date_prop = next(p for p in cal["properties"] if p["type"] == "date")
        soon = (dt.date.today() + dt.timedelta(days=3)).isoformat()
        self.c.post(f"/api/databases/{cal['database']['id']}/entries",
                    {"title": "Midterm", "values": {date_prop["id"]: soon}}, format="json")
        self.c.post(f"/api/databases/{cal['database']['id']}/entries", {"title": "Undated"}, format="json")
        self.c.post("/api/tasks", {"title": "Lab report", "due": soon, "project": g["id"]}, format="json")
        a = self.c.get(f"/api/documents/{g['id']}/agenda").json()
        self.assertEqual([x["title"] for x in a["events"]], ["Midterm"])
        self.assertEqual([t["title"] for t in a["tasks"]], ["Lab report"])
        p = self.c.patch(f"/api/documents/{g['id']}", {"kind": "page"}, format="json").json()
        self.assertEqual(p["doc"]["kind"] if "doc" in p else p["kind"], "page")


class AgentClaudeTests(TestCase):
    def setUp(self):
        self.c = APIClient(HTTP_X_KERN="1")

    def test_web_search_sources_and_page_context(self):
        from unittest import mock

        class Block:
            def __init__(self, **kw):
                self.__dict__.update(kw)
            def model_dump(self, **_):
                return {k: v for k, v in self.__dict__.items() if v is not None}

        class Msg:
            def __init__(self, content, stop):
                self.content, self.stop_reason, self.container = content, stop, None

        doc = self.c.post("/api/documents", {"title": "Photosynthesis"}, format="json").json()
        replies = [
            Msg([Block(type="tool_use", id="t1", name="read_page", input={"page_id": doc["id"]})], "tool_use"),
            Msg([Block(type="server_tool_use", id="s1", name="web_search", input={"query": "chlorophyll"}),
                 Block(type="web_search_tool_result", tool_use_id="s1", content=[
                     {"type": "web_search_result", "url": "https://example.org/a", "title": "A"}]),
                 Block(type="text", text="Chlorophyll absorbs ", citations=None),
                 Block(type="text", text="red and blue light.", citations=[
                     {"type": "web_search_result_location", "url": "https://example.org/a", "title": "A", "cited_text": "x"}])],
                "end_turn"),
        ]
        calls = []

        def create(**kw):
            calls.append(kw)
            return replies[len(calls) - 1]

        fake = mock.MagicMock()
        fake.beta.messages.create.side_effect = create
        self.c.put("/api/ai/config", {"provider": "anthropic", "api_key": "sk-ant-test-123456789"}, format="json")
        chat = self.c.post("/api/chats", {}, format="json").json()
        with mock.patch("anthropic.Anthropic", return_value=fake):
            r = self.c.post(f"/api/chats/{chat['id']}/message", {"text": "more on this?", "page": doc["id"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        last = r.json()["messages"][-1]
        self.assertEqual(last["text"], "Chlorophyll absorbs red and blue light.")
        self.assertEqual(last["sources"], [{"url": "https://example.org/a", "title": "A"}])
        names = [t.get("name") for t in calls[0]["tools"]]
        self.assertIn("web_search", names)
        self.assertIn("web_fetch", names)
        self.assertIn("search the web", calls[0]["system"])
        sent = calls[-1]["messages"]  # one list, extended turn by turn
        self.assertIn("Photosynthesis", sent[0]["content"])
        self.assertEqual(sent[2]["content"][0]["type"], "tool_result")
        self.assertIn("Photosynthesis", sent[2]["content"][0]["content"])
        self.assertTrue(self.c.get("/api/ai/config").json()["web_search"])
