from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from api.app import create_app


class PlatformApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "test.sqlite3"
        self.client_context = TestClient(create_app(database_path=self.database_path))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_health_dashboard_and_partial_crud(self) -> None:
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Campus<span>Scheduler</span>", page.text)
        self.assertEqual(
            self.client.get("/static/app.js").status_code,
            200,
        )
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        terms = self.client.get("/api/academic/terms").json()
        self.assertEqual(terms["total"], 1)
        term_id = terms["items"][0]["id"]
        response = self.client.patch(
            f"/api/academic/terms/{term_id}", json={"name": "Updated demo"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Updated demo")
        dashboard = self.client.get("/api/dashboard").json()
        self.assertEqual(dashboard["counts"]["classes"], 3)

    def test_csv_import_is_transactional_and_template_is_available(self) -> None:
        template = self.client.get("/api/templates/rooms")
        self.assertEqual(template.status_code, 200)
        self.assertEqual(template.text.splitlines()[0], "name,building,capacity")

        source = "name,building,capacity\nTEMP,East,20\nN101,East,22\n"
        response = self.client.post(
            "/api/import/csv/rooms",
            content=source,
            headers={"Content-Type": "text/csv"},
        )
        self.assertEqual(response.status_code, 409)
        rooms = self.client.get("/api/academic/rooms").json()
        self.assertEqual(rooms["total"], 2)
        self.assertNotIn("TEMP", {row["name"] for row in rooms["items"]})

        created = self.client.post(
            "/api/import/csv/instructors",
            content="name,email\nTaylor,first@example.edu\n",
            headers={"Content-Type": "text/csv"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["imported"], 1)

    def test_generation_history_current_schedule_edit_and_exports(self) -> None:
        term_id = self.client.get("/api/academic/terms").json()["items"][0]["id"]
        created = self.client.post(
            "/api/jobs",
            json={"term_id": term_id, "algorithm": "cp-sat", "time_limit_s": 10},
        )
        self.assertEqual(created.status_code, 202, created.text)
        identifier = created.json()["id"]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            run = self.client.get(f"/api/jobs/{identifier}").json()
            if run["status"] not in {"queued", "running", "cancel_requested"}:
                break
            time.sleep(0.02)
        self.assertEqual(run["status"], "complete", run)
        self.assertTrue(run["result"]["validation"]["valid_complete"])
        self.assertEqual(run["result"]["assignment_coverage"], 1.0)
        self.assertEqual(
            self.client.get("/api/schedules/current").json()["id"], identifier
        )

        assignments = run["result"]["assignments"]
        class_one, class_two = assignments[0], assignments[1]
        domain = self.client.get(
            f"/api/schedules/{identifier}/domains/{class_two['class_id']}"
        ).json()["placements"]
        colliding_index = next(
            index
            for index, placement in enumerate(domain)
            if placement["room_id"] == class_one["room_id"]
            and placement["days"] == class_one["days"]
            and placement["weeks"] == class_one["weeks"]
            and placement["start"] == class_one["start"]
            and placement["length"] == class_one["length"]
        )
        rejected = self.client.put(
            f"/api/schedules/{identifier}/assignments/{class_two['class_id']}",
            json={"placement_index": colliding_index},
        )
        self.assertEqual(rejected.status_code, 409)
        still_current = self.client.get("/api/schedules/current").json()
        self.assertEqual(still_current["id"], identifier)
        self.assertTrue(still_current["result"]["validation"]["valid_complete"])

        csv_export = self.client.get(f"/api/exports/{identifier}.csv")
        self.assertEqual(csv_export.status_code, 200)
        self.assertIn("class_id,class_name", csv_export.text)
        xlsx_export = self.client.get(f"/api/exports/{identifier}.xlsx")
        self.assertEqual(xlsx_export.status_code, 200)
        self.assertTrue(xlsx_export.content.startswith(b"PK"))

        accepted_edit = None
        for assignment in assignments:
            class_id = assignment["class_id"]
            placement_list = self.client.get(
                f"/api/schedules/{identifier}/domains/{class_id}"
            ).json()["placements"]
            for placement in placement_list:
                if (
                    placement["room_id"] == assignment["room_id"]
                    and placement["days"] == assignment["days"]
                    and placement["start"] == assignment["start"]
                    and placement["length"] == assignment["length"]
                    and placement["weeks"] == assignment["weeks"]
                ):
                    continue
                response = self.client.put(
                    f"/api/schedules/{identifier}/assignments/{class_id}",
                    json={"placement_index": placement["placement_index"]},
                )
                if response.status_code == 200:
                    accepted_edit = (class_id, placement)
                    break
                self.assertEqual(response.status_code, 409, response.text)
            if accepted_edit is not None:
                break
        self.assertIsNotNone(accepted_edit, "Expected at least one valid manual edit")
        persisted = self.client.get(f"/api/schedules/{identifier}").json()
        self.assertTrue(persisted["result"]["validation"]["valid_complete"])
        edited_assignment = next(
            item
            for item in persisted["result"]["assignments"]
            if item["class_id"] == accepted_edit[0]
        )
        self.assertEqual(edited_assignment["start"], accepted_edit[1]["start"])
        edited_export = self.client.get(f"/api/exports/{identifier}.csv")
        self.assertIn(str(accepted_edit[1]["start"]), edited_export.text)

        self.client_context.__exit__(None, None, None)
        self.client_context = TestClient(
            create_app(database_path=self.database_path)
        )
        self.client = self.client_context.__enter__()
        after_restart = self.client.get("/api/schedules/current").json()
        self.assertEqual(after_restart["id"], identifier)
        self.assertTrue(after_restart["result"]["validation"]["valid_complete"])
        restarted_assignment = next(
            item
            for item in after_restart["result"]["assignments"]
            if item["class_id"] == accepted_edit[0]
        )
        self.assertEqual(restarted_assignment["start"], accepted_edit[1]["start"])

    def test_infeasible_job_does_not_replace_existing_schedule(self) -> None:
        term_id = self.client.get("/api/academic/terms").json()["items"][0]["id"]
        timeslots = self.client.get("/api/academic/timeslots").json()["items"]
        only_slot = timeslots[0]["id"]
        classes = self.client.get("/api/academic/classes").json()["items"][:2]
        for cls in classes:
            response = self.client.patch(
                f"/api/academic/classes/{cls['id']}",
                json={"allowed_timeslot_ids": str(only_slot)},
            )
            self.assertEqual(response.status_code, 200, response.text)
        created = self.client.post(
            "/api/jobs", json={"term_id": term_id, "time_limit_s": 5}
        )
        self.assertEqual(created.status_code, 202, created.text)
        identifier = created.json()["id"]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            run = self.client.get(f"/api/jobs/{identifier}").json()
            if run["status"] not in {"queued", "running", "cancel_requested"}:
                break
            time.sleep(0.02)
        self.assertEqual(run["status"], "infeasible_proven", run)
        self.assertFalse(run["result"]["validation"]["valid_complete"])
        self.assertEqual(self.client.get("/api/schedules/current").status_code, 404)

    def test_itc_xml_import_validates_before_persisting(self) -> None:
        source = """<problem name="tiny" nrDays="1" slotsPerDay="4" nrWeeks="1">
          <optimization time="1" room="1" distribution="1" student="0"/>
          <rooms><room id="1" capacity="20"/></rooms>
          <courses><course id="1"><config id="1"><subpart id="1">
            <class id="1" limit="10"><time days="1" start="0" length="1" weeks="1"/>
              <room id="1"/></class>
          </subpart></config></course></courses>
          <distributions/><students/>
        </problem>"""
        invalid = self.client.post(
            "/api/import/itc",
            content="<broken",
            headers={"Content-Type": "application/xml"},
        )
        self.assertEqual(invalid.status_code, 422)
        response = self.client.post(
            "/api/import/itc",
            content=source,
            headers={"Content-Type": "application/xml"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["classes"], 1)
        self.assertEqual(len(self.client.get("/api/datasets").json()["items"]), 1)


if __name__ == "__main__":
    unittest.main()
